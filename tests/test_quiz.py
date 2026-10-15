from conftest import ROOT, cmd, make_client, recv, recv_until

CONTENT = ROOT / "tests" / "fixtures" / "content"


def quiz_client(data_dir, speed=1.0):
    return make_client(data_dir, content_dir=str(CONTENT), speed=speed)


def join(c, name, avatar, as_host=False):
    r = c.post("/api/join", json={"name": name, "avatar_kind": "pumpkin", "avatar_ref": avatar, "as_host": as_host})
    return r.json()


def wait_quiz(ws, cond, limit=400):
    for _ in range(limit):
        m = recv(ws)
        q = m.get("quiz") if m.get("t") in ("quiz", "snapshot") else None
        if q and cond(q):
            return q
    raise AssertionError("не дождались состояния квиза")


def phase(name):
    return lambda q: q["phase"] == name


def correct_of(r, i):
    return (r + i) % 4  # см. tools/make_test_content.py


def setup(c, n=3, host_player=True):
    players = []
    if host_player:
        players.append(join(c, "Ведущий", "pumpkin-8", as_host=True))
    for i in range(n):
        players.append(join(c, f"Игрок {i + 1}", f"pumpkin-{i + 1}"))
    return players


def play_empty_round(host):
    """Сыграть текущий раунд без ответов: показать, закрыть, дальше — до итогов."""
    while True:
        r = cmd(host, "quiz_show")
        if not r["ok"]:
            break
        cmd(host, "quiz_close")
        if cmd(host, "quiz_next")["ok"] is False:
            break
        q = wait_quiz(host, lambda q: q["phase"] in ("question", "rating"))
        if q["phase"] == "rating":
            return
        cmd(host, "quiz_close")
        while True:
            r = cmd(host, "quiz_next")
            if not r["ok"]:
                return
            q = wait_quiz(host, lambda q: q["phase"] in ("question", "rating"))
            if q["phase"] == "rating":
                return
            cmd(host, "quiz_close")


def test_round1_scoring_bonus_and_autoclose(data_dir):
    with quiz_client(data_dir, speed=20) as c:
        ps = setup(c, 3)
        hostp, p1, p2, p3 = ps
        ev = c.app.state.ev
        with c.websocket_connect("/ws?role=host") as host, \
                c.websocket_connect(f"/ws?role=player&token={hostp['token']}") as wh, \
                c.websocket_connect(f"/ws?role=player&token={p1['token']}") as w1, \
                c.websocket_connect(f"/ws?role=player&token={p2['token']}") as w2, \
                c.websocket_connect(f"/ws?role=player&token={p3['token']}") as w3:
            for w in (host, wh, w1, w2, w3):
                recv_until(w, "snapshot")
            assert cmd(host, "quiz_show")["code"] == "wrong_scene"
            assert cmd(host, "set_scene", scene="quiz")["ok"]
            assert cmd(host, "quiz_start_round")["ok"]
            assert ev.settings["quiz_started"] is True
            assert cmd(host, "set_setting", key="host_in_scoring", value=True)["code"] == "locked"
            assert cmd(host, "quiz_show")["ok"]
            q = wait_quiz(w1, phase("question"))
            qid = q["question"]["id"]
            assert "correct" not in q["question"] and "image_url" not in q["question"]
            ok = correct_of(1, 1)
            # порядок прихода: ведущий (вне зачёта), игрок 1, игрок 2 (неверно), игрок 3
            assert cmd(wh, "quiz_answer", qid=qid, choice=ok)["ok"]
            assert cmd(w1, "quiz_answer", qid=qid, choice=ok)["ok"]
            assert cmd(w1, "quiz_answer", qid=qid, choice=(ok + 1) % 4)["code"] == "already"
            assert cmd(w2, "quiz_answer", qid=qid, choice=(ok + 1) % 4)["ok"]
            assert cmd(w3, "quiz_answer", qid=qid, choice=ok)["ok"]
            # ответили все подключённые → автозакрытие через 2 с (при x20 — 0,1 с)
            q = wait_quiz(host, phase("reveal"))
            rv = q["reveal"]
            assert rv["correct"] == ok and rv["counts"][ok] == 3 and sum(rv["counts"]) == 4
            assert [t["name"] for t in rv["top"]] == ["Игрок 1", "Игрок 3"]
            assert [t["bonus"] for t in rv["top"]] == [50, 25]
            my = wait_quiz(w1, phase("reveal"))["my"]
            assert my["result"] == {"points": 200, "bonus": 50, "correct": True, "skipped": False}
            assert wait_quiz(w2, phase("reveal"))["my"]["result"]["correct"] is False
        assert ev.total(hostp["me"]["id"]) == 200  # очки записаны, бонуса нет
        assert ev.total(p1["me"]["id"]) == 250
        assert ev.total(p2["me"]["id"]) == 0
        assert ev.total(p3["me"]["id"]) == 225


def test_late_joiner_and_deadline(data_dir):
    with quiz_client(data_dir, speed=60) as c:
        p1, p2 = setup(c, 2, host_player=False)
        with c.websocket_connect("/ws?role=host") as host, \
                c.websocket_connect(f"/ws?role=player&token={p1['token']}") as w1, \
                c.websocket_connect(f"/ws?role=player&token={p2['token']}") as w2:
            for w in (host, w1, w2):
                recv_until(w, "snapshot")
            cmd(host, "set_scene", scene="quiz")
            cmd(host, "quiz_start_round")
            cmd(host, "quiz_show")
            q = wait_quiz(host, phase("question"))
            # уход из сцены во время вопроса требует подтверждения
            assert cmd(host, "set_scene", scene="timer")["code"] == "confirm_required"
            late = join(c, "Опоздавший", "pumpkin-5")
            with c.websocket_connect(f"/ws?role=player&token={late['token']}") as wl:
                snap = recv_until(wl, "snapshot")
                assert snap["quiz"]["my"]["eligible"] is False
                assert cmd(wl, "quiz_answer", qid=q["question"]["id"], choice=0)["code"] == "late"
            assert cmd(w1, "quiz_answer", qid=q["question"]["id"], choice=0)["ok"]
            # игрок 2 молчит: закрытие по времени (60 с при x60 ≈ 1 с)
            q = wait_quiz(host, phase("reveal"))
            assert q["answered_count"] == 1
            assert cmd(w2, "quiz_answer", qid=q["question"]["id"], choice=0)["code"] == "closed"


def test_skip_question_gives_nothing(data_dir):
    with quiz_client(data_dir) as c:
        (p1,) = setup(c, 1, host_player=False)
        with c.websocket_connect("/ws?role=host") as host, \
                c.websocket_connect(f"/ws?role=player&token={p1['token']}") as w1:
            recv_until(host, "snapshot")
            recv_until(w1, "snapshot")
            cmd(host, "set_scene", scene="quiz")
            cmd(host, "quiz_start_round")
            cmd(host, "quiz_show")
            q = wait_quiz(w1, phase("question"))
            cmd(w1, "quiz_answer", qid=q["question"]["id"], choice=correct_of(1, 1))
            assert cmd(host, "skip_question")["ok"]
            q = wait_quiz(host, phase("reveal"))
            assert q["reveal"]["skipped"] is True
        assert c.app.state.ev.total(p1["me"]["id"]) == 0


def test_round4_verdicts_hidden_total_and_facts_lock(data_dir):
    with quiz_client(data_dir) as c:
        p1, p2, p3 = setup(c, 3, host_player=False)
        ev = c.app.state.ev
        for i in range(1, 16):  # все факты «показаны» головой
            ev.db.execute("INSERT INTO facts(id, shown_at) VALUES(?, 1)", (f"t{i:03d}",))
        with c.websocket_connect("/ws?role=host") as host, \
                c.websocket_connect(f"/ws?role=player&token={p1['token']}") as w1, \
                c.websocket_connect(f"/ws?role=player&token={p2['token']}") as w2, \
                c.websocket_connect(f"/ws?role=player&token={p3['token']}") as w3:
            for w in (host, w1, w2, w3):
                recv_until(w, "snapshot")
            cmd(host, "set_scene", scene="quiz")
            for r in (1, 2, 3):
                assert cmd(host, "quiz_start_round")["ok"]
                play_empty_round(host)
                q = wait_quiz(host, phase("rating"))
                assert q["round"] == r
                if r < 3:
                    assert q["rating"]["total"] is not None
            # после раунда 3 общий рейтинг скрыт
            assert ev.settings["hide_total"] is True
            assert q["rating"]["total"] is None
            assert cmd(host, "quiz_start_round")["ok"]
            q = wait_quiz(host, phase("intro"))
            assert q["round"] == 4 and q["q_count"] == 5 and q["facts_locked"]
            assert all(f["text"] is None for f in ev.facts_public())
            cmd(host, "quiz_show")
            q = wait_quiz(w1, lambda q: q["phase"] == "question" and q["round"] == 4)
            qid, kind = q["question"]["id"], q["question"]["kind"]
            assert kind == "text" and "answer" not in q["question"]
            cmd(w3, "quiz_answer", qid=qid, text="  мой   ответ ")
            cmd(w1, "quiz_answer", qid=qid, text="первый")
            cmd(w2, "quiz_answer", qid=qid, text="второй")
            q = wait_quiz(host, lambda q: q["phase"] == "judging" and q["q_index"] == 0)  # все ответили → автозакрытие → вердикты
            assert [a["text"] for a in q["answers"]] == ["мой ответ", "первый", "второй"]
            assert q["next"]["disabled"] is True
            assert cmd(host, "quiz_reveal")["code"] == "verdicts_missing"
            cmd(host, "quiz_verdict", player_id=p1["me"]["id"], ok=True)
            cmd(host, "quiz_verdict", player_id=p3["me"]["id"], ok=True)
            cmd(host, "quiz_verdict_rest", ok=False)
            assert cmd(host, "quiz_reveal")["ok"]
            q = wait_quiz(w2, lambda q: q["phase"] == "reveal" and q["round"] == 4)
            assert q["my"]["verdict"] == 0
            assert [(a["name"], a["verdict"]) for a in q["reveal"]["answers"]] == [
                ("Игрок 3", 1), ("Игрок 1", 1), ("Игрок 2", 0)]
            # бонус по времени отправки среди принятых: игрок 3 первый
            assert ev.total(p3["me"]["id"]) == 250 and ev.total(p1["me"]["id"]) == 225
            assert ev.total(p2["me"]["id"]) == 0
            # игрок не видит общий счёт, пока он скрыт
            assert ev.me(p3["me"]["id"])["score"] is None
            for _ in range(4):
                cmd(host, "quiz_next")
                wait_quiz(host, phase("question"))
                cmd(host, "quiz_close")
                wait_quiz(host, phase("judging"))
                cmd(host, "quiz_verdict_rest", ok=False)
                cmd(host, "quiz_reveal")
                wait_quiz(host, phase("reveal"))
            cmd(host, "quiz_next")
            q = wait_quiz(host, phase("rating"))
            assert q["done"] and not q["facts_locked"] and q["next"] is None
            assert any(f["text"] for f in ev.facts_public())
            assert cmd(host, "quiz_start_round")["code"] == "quiz_done"


def test_restart_mid_question_keeps_answers(data_dir):
    with quiz_client(data_dir) as c:
        p1, p2 = setup(c, 2, host_player=False)
        with c.websocket_connect("/ws?role=host") as host, \
                c.websocket_connect(f"/ws?role=player&token={p1['token']}") as w1:
            recv_until(host, "snapshot")
            recv_until(w1, "snapshot")
            cmd(host, "set_scene", scene="quiz")
            cmd(host, "quiz_start_round")
            cmd(host, "quiz_show")
            q = wait_quiz(w1, phase("question"))
            cmd(w1, "quiz_answer", qid=q["question"]["id"], choice=correct_of(1, 1))
            deadline = q["deadline_ms"]
    with quiz_client(data_dir) as c:
        with c.websocket_connect(f"/ws?role=player&token={p2['token']}") as w2:
            q = recv_until(w2, "snapshot")["quiz"]
            assert q["phase"] == "question" and q["deadline_ms"] == deadline and q["answered_count"] == 1
            assert cmd(w2, "quiz_answer", qid=q["question"]["id"], choice=0)["ok"]
