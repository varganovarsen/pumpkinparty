import io
import json
import zipfile

import pytest
from PIL import Image

from conftest import ROOT, cmd, make_client, recv, recv_until
from server.game import MIN_GOOD_GAP, PLANS, generate, score_of
from server.state import CmdError

CONTENT = ROOT / "tests" / "fixtures" / "content"
POINTS = {"regular": 10, "golden": 50, "rotten": -30}


def client(data_dir, **over):
    return make_client(data_dir, content_dir=str(CONTENT), **over)


def join(c, name, avatar):
    return c.post("/api/join", json={"name": name, "avatar_kind": "pumpkin", "avatar_ref": avatar}).json()


def wait(ws, t, cond=lambda m: True, limit=300):
    for _ in range(limit):
        m = recv(ws)
        if m.get("t") == t and cond(m):
            return m
    raise AssertionError(f"не дождались {t}")


def jpeg(w=800, h=600, color=(200, 120, 40)):
    buf = io.BytesIO()
    Image.new("RGB", (w, h), color).save(buf, "JPEG")
    return buf.getvalue()


# ---------------------------------------------------------------------- игра
def test_schedule_perfect_game_is_500_and_reachable():
    for seed in range(1, 40):
        items = generate(seed, "scored")
        assert items == generate(seed, "scored")  # детерминизм
        good = [it for it in items if it["kind"] != "rotten"]
        assert sum(POINTS[it["kind"]] for it in good) == 500
        assert len([it for it in good if it["kind"] == "golden"]) == 4
        lands = [it["land"] for it in good]
        assert all(b - a >= MIN_GOOD_GAP - 1e-6 for a, b in zip(lands, lands[1:]))
        for r in (it for it in items if it["kind"] == "rotten"):
            assert all(abs(r["land"] - g) >= 0.3 - 1e-6 for g in lands)
        assert all(it["t"] >= 0 and it["land"] <= PLANS["scored"][0] for it in items)
        assert score_of(items, {it["i"] for it in good}, POINTS) == 500
    p = generate(5, "practice")
    assert sum(1 for it in p if it["kind"] == "rotten") == 3 and len(p) == 12


def test_score_never_below_zero():
    items = generate(3, "scored")
    rotten = {it["i"] for it in items if it["kind"] == "rotten"}
    assert score_of(items, rotten, POINTS) == 0


def test_game_flow_practice_and_scored(data_dir):
    with client(data_dir, speed=30) as c:
        a, b = join(c, "Аня", "pumpkin-1"), join(c, "Паша", "pumpkin-2")
        ev = c.app.state.ev
        with c.websocket_connect("/ws?role=host") as host, \
                c.websocket_connect(f"/ws?role=player&token={a['token']}") as wa, \
                c.websocket_connect(f"/ws?role=player&token={b['token']}") as wb:
            for w in (host, wa, wb):
                recv_until(w, "snapshot")
            assert cmd(host, "game_start", mode="practice")["code"] == "wrong_scene"
            cmd(host, "set_scene", scene="game")
            assert cmd(host, "game_start", mode="practice")["ok"]
            g = wait(wa, "game", lambda m: m["game"]["phase"] == "countdown")["game"]
            assert g["items"] and g["my"]["eligible"]
            good = [it["i"] for it in g["items"] if it["kind"] != "rotten"]
            wait(wa, "game", lambda m: m["game"]["phase"] == "running")
            assert cmd(wa, "game_result", caught=good)["ok"]
            assert cmd(wb, "game_result", caught=[])["ok"]
            wait(host, "game", lambda m: m["game"]["phase"] == "finished")
            assert ev.total(a["me"]["id"]) == 0  # тренировка не в зачёт
            assert cmd(host, "game_start", mode="scored")["ok"]
            g = wait(wa, "game", lambda m: m["game"]["phase"] == "countdown" and m["game"]["mode"] == "scored")["game"]
            items = g["items"]
            wait(wa, "game", lambda m: m["game"]["phase"] == "running")
            assert cmd(host, "set_scene", scene="ambient")["code"] == "confirm_required"
            cmd(wa, "game_progress", score=120)
            golden = [it["i"] for it in items if it["kind"] == "golden"]
            r = cmd(wa, "game_result", caught=[it["i"] for it in items])  # поймал всё, включая гнилые
            assert 0 <= r["score"] <= 500
            assert cmd(wb, "game_result", caught=golden)["score"] == 200
            wait(host, "game", lambda m: m["game"]["phase"] == "finished" and m["game"]["scored_done"])
            assert cmd(host, "game_start", mode="scored")["code"] == "done"
        assert ev.total(b["me"]["id"]) == 200
        assert ev.breakdown(a["me"]["id"]).get("game", 0) == r["score"]


# ---------------------------------------------------------------------- голосование
def _pumpkin(ev, pid):
    ev.db.execute("INSERT INTO pumpkins(player_id, version, data, updated_at) VALUES(?, 1, '{}', 0)", (pid,))


def test_vote_ties_and_bonuses(data_dir):
    with client(data_dir) as c:
        ps = [join(c, f"Игрок {i}", f"pumpkin-{i}") for i in range(1, 6)]
        ev = c.app.state.ev
        ids = [p["me"]["id"] for p in ps]
        for pid in ids[:4]:
            _pumpkin(ev, pid)
        socks = []
        with c.websocket_connect("/ws?role=host") as host:
            recv_until(host, "snapshot")
            cmd(host, "set_scene", scene="carve_vote")
            assert cmd(host, "vote_start")["ok"]
            assert ev.settings["carve_locked"] is True
            entries = {e["player_id"]: e["n"] for e in ev.vote.st["entries"]}
            for p in ps:
                ws = c.websocket_connect(f"/ws?role=player&token={p['token']}")
                socks.append(ws.__enter__())
            snap = recv_until(socks[0], "snapshot")["vote"]
            assert snap["my"]["own"] == entries[ids[0]]
            assert "masks" not in snap["entries"][0]  # игрокам маски не нужны
            assert cmd(socks[0], "vote", n=entries[ids[0]])["code"] == "own"
            # голоса: A=2, B=2, C=1, D=0 → места 1, 1, 3; D без места
            A, B, C = entries[ids[0]], entries[ids[1]], entries[ids[2]]
            cmd(socks[1], "vote", n=C)            # потом передумает
            cmd(socks[1], "vote", n=A)
            cmd(socks[2], "vote", n=A)
            cmd(socks[0], "vote", n=B)
            cmd(socks[4], "vote", n=B)
            cmd(socks[3], "vote", n=C)
            cmd(socks[3], "vote", n=None)          # воздержался
            cmd(socks[3], "vote", n=C)
            assert cmd(host, "vote_close")["ok"]
            res = {r["player_id"]: r for r in ev.vote.st["results"]}
            assert (res[ids[0]]["place"], res[ids[1]]["place"], res[ids[2]]["place"]) == (1, 1, 3)
            assert res[ids[3]]["place"] is None and res[ids[3]]["bonus"] == 0
            assert [ev.total(i) for i in ids[:4]] == [500, 500, 100, 0]
            # раскрытие по одному, от последнего места к первому
            cmd(host, "set_scene", scene="carve_reveal")
            assert c.get("/api/pumpkins").json()["revealed"] is False
            for _ in range(4):
                assert cmd(host, "vote_reveal")["ok"]
            tv_view = ev.vote.public("tv")
            assert [r["player_id"] for r in tv_view["results"]][0] == ids[3]
            assert cmd(host, "vote_reveal")["ok"] and ev.vote.st["revealed"]
            assert cmd(host, "vote_reveal")["code"] == "done"
            for ws in socks:
                ws.__exit__(None, None, None)
        assert c.get("/api/pumpkins").json()["revealed"] is True
        # после голосования тыквы не меняются
        assert ev.settings["carve_locked"] is True


# ---------------------------------------------------------------------- таймер и финал
def test_timer_pause_add_and_finish(data_dir):
    with client(data_dir, speed=60) as c:
        ev = c.app.state.ev
        with c.websocket_connect("/ws?role=host") as host:
            recv_until(host, "snapshot")
            cmd(host, "set_scene", scene="timer")
            assert cmd(host, "timer_set", minutes=0.5, label="Чай и пироги")["ok"]
            assert cmd(host, "timer_pause", paused=True)["ok"]
            left = ev.timer.st["left"]
            assert 0 < left <= 30
            assert cmd(host, "timer_add", seconds=60)["ok"]
            assert ev.timer.st["left"] == left + 60
            assert cmd(host, "timer_pause", paused=False)["ok"]
            t = wait(host, "timer", lambda m: m["timer"]["finished"])["timer"]
            assert t["label"] == "Чай и пироги"
        assert ev.settings["scene"] == "timer"  # по нулю сцена не переключается


def test_rating_reveal_ties_and_unhides_total(data_dir):
    with client(data_dir) as c:
        ps = [join(c, n, f"pumpkin-{i}") for i, n in enumerate(["А", "Б", "В", "Г"], 1)]
        host_p = c.post("/api/join", json={"name": "Вед", "avatar_kind": "pumpkin", "avatar_ref": "pumpkin-8",
                                           "as_host": True}).json()
        ev = c.app.state.ev
        for p, pts in zip(ps, [300, 500, 300, 100]):
            ev.add_points(p["me"]["id"], "quiz", pts, ref="r1q01")
        ev.add_points(host_p["me"]["id"], "quiz", 900, ref="r1q01")
        ev._set("hide_total", True)
        with c.websocket_connect("/ws?role=host") as host:
            recv_until(host, "snapshot")
            cmd(host, "set_scene", scene="rating_reveal")
            groups = ev.finale.st["groups"]
            assert [[r["total"] for r in g] for g in groups] == [[100], [300, 300], [500]]
            assert all(r["player_id"] != host_p["me"]["id"] for g in groups for r in g)
            assert groups[1][0]["place"] == 2 and groups[0][0]["place"] == 4
            assert ev.finale.public("tv")["groups"] == []
            for _ in range(3):
                assert cmd(host, "rating_next")["ok"]
            assert cmd(host, "rating_next")["code"] == "done"
        assert ev.settings["hide_total"] is False
        assert groups[2][0]["breakdown"]["quiz"] == 500


# ---------------------------------------------------------------------- фото
def test_selfie_album_hide_delete_and_zip(data_dir):
    with client(data_dir) as c:
        a = join(c, "Аня", "pumpkin-1")
        assert c.post("/api/photo", data={"token": "bad"}, files={"file": ("a.jpg", jpeg(), "image/jpeg")}).status_code == 403
        r = c.post("/api/photo", data={"token": a["token"]}, files={"file": ("a.jpg", jpeg(4000, 3000), "image/jpeg")}).json()
        assert r["ok"] and r["photo"]["author_name"] == "Аня"
        big = Image.open(io.BytesIO(c.get(r["photo"]["url"]).content))
        thumb = Image.open(io.BytesIO(c.get(r["photo"]["thumb_url"]).content))
        assert max(big.size) == 2048 and max(thumb.size) == 400
        r2 = c.post("/api/photo", data={"token": a["token"]}, files={"file": ("b.jpg", jpeg(), "image/jpeg")}).json()
        with c.websocket_connect("/ws?role=host") as host:
            recv_until(host, "snapshot")
            assert cmd(host, "photo_hide", id=r["photo"]["id"], hidden=True)["ok"]
            assert [p["id"] for p in c.get("/api/photos").json()["photos"]] == [r2["photo"]["id"]]
            assert c.get(r["photo"]["url"]).status_code == 404
            assert c.get(r["photo"]["url"] + "?all=1").status_code == 200
            assert len(c.get("/api/photos?all=1").json()["photos"]) == 2
            assert cmd(host, "photo_delete", id=r2["photo"]["id"])["ok"]
        assert (data_dir / "_deleted" / r2["photo"]["url"].split("/")[-1]).exists()
        assert c.get("/api/photos").json()["photos"] == []
        cmd_ok = c.post("/api/photo", data={"token": a["token"]}, files={"file": ("c.jpg", jpeg(), "image/jpeg")}).json()
        z = c.post("/api/download_zip", data={"ids": f"{cmd_ok['photo']['id']},{r['photo']['id']}"})
        names = zipfile.ZipFile(io.BytesIO(z.content)).namelist()
        assert len(names) == 1  # скрытое в архив не попадает
        assert not list((data_dir / "tmp").glob("*.zip"))  # временный архив удалён


def test_final_photo_portrait_cropped_to_4x3(data_dir):
    with client(data_dir) as c:
        r = c.post("/api/final_photo", files={"file": ("f.jpg", jpeg(1500, 2000), "image/jpeg")}).json()
        assert r["ok"] and r["photo"]["kind"] == "final"
        img = Image.open(io.BytesIO(c.get(r["photo"]["url"]).content))
        assert abs(img.width / img.height - 4 / 3) < 0.01
        assert list((data_dir / "photos" / "original").glob("*.jpg"))
        sel = c.post("/api/photo", data={"token": join(c, "А", "pumpkin-1")["token"]},
                     files={"file": ("a.jpg", jpeg(), "image/jpeg")}).json()
        ids = [p["id"] for p in c.get("/api/photos?final_first=1").json()["photos"]]
        assert ids == [r["photo"]["id"], sel["photo"]["id"]]
        assert c.app.state.ev.finale.st["final_photo_id"] == r["photo"]["id"]


def test_webcam_failure_is_logged_not_fatal(data_dir, monkeypatch):
    from server import webcam

    def broken(device):
        raise webcam.WebcamError("нет устройства")

    monkeypatch.setattr(webcam, "snapshot", broken)
    with client(data_dir, speed=60) as c:
        with c.websocket_connect("/ws?role=host") as host:
            recv_until(host, "snapshot")
            assert cmd(host, "shot_now")["ok"]
            wait(host, "log", lambda m: "Вебка" in m["entry"]["text"])
        assert c.app.state.ev.photos.shot_running is False


def test_shots_interval_setting_reschedules(data_dir):
    with client(data_dir) as c:
        ev = c.app.state.ev
        with c.websocket_connect("/ws?role=host") as host:
            recv_until(host, "snapshot")
            assert cmd(host, "set_setting", key="shots_max_minutes", value=2)["ok"]
            assert ev.settings["shots_min_minutes"] == 2  # «от» подтянулось к «до»
            assert ev.settings["shot_next_at"] <= ev.clock.now() + 2 * 60 + 1
            assert cmd(host, "set_setting", key="shots_min_minutes", value=30)["ok"]
            assert ev.settings["shots_max_minutes"] == 30
            assert ev.settings["shot_next_at"] >= ev.clock.now() + 30 * 60 - 1
            assert not cmd(host, "set_setting", key="shots_min_minutes", value=0)["ok"]
            s = wait(host, "settings", lambda m: True)["settings"]
            assert "shot_next_at" in s


# ---------------------------------------------------------------------- голова
def test_head_scheduler_respects_scene_gap(data_dir):
    with client(data_dir, tv_localhost_only=False) as c:
        ev = c.app.state.ev
        now = ev.clock.now()
        ev._set("head_next_at", now - 1)
        ev._set("last_scene_end_at", now)  # только что закончилась другая сцена
        ev.head_tick()
        assert ev.head_current is None
        ev._set("last_scene_end_at", now - 3 * 60 - 1)
        ev.head_tick()
        assert ev.head_current is not None
        assert ev.settings["head_next_at"] > now + 4 * 60
        ev.head_skip()
        ev._set("scene", "quiz")
        ev._set("head_next_at", now - 1)
        ev.head_tick()
        assert ev.head_current is None  # вне ambient голова не появляется


def test_lipsync_script(tmp_path):
    import numpy as np
    import soundfile as sf

    from tools.make_lipsync import analyse

    sr = 22050
    t = np.arange(sr * 2) / sr
    sig = np.where(t < 1, 0.0, 0.5 * np.sin(2 * np.pi * 220 * t))
    sf.write(tmp_path / "f001.wav", sig, sr)
    data = analyse(tmp_path / "f001.wav")
    assert data["fps"] == 30 and len(data["frames"]) == 60
    early = [f["mouth"] for f in data["frames"][:25]]
    late = [f["mouth"] for f in data["frames"][35:]]
    assert max(early) < 10 < min(late)
    assert all(0 <= f["viseme"] <= 4 for f in data["frames"])
    json.dumps(data)


def test_vote_host_out_of_scoring_gets_no_place(data_dir):
    with client(data_dir) as c:
        a, b = join(c, "Аня", "pumpkin-1"), join(c, "Паша", "pumpkin-2")
        h = c.post("/api/join", json={"name": "Вед", "avatar_kind": "pumpkin", "avatar_ref": "pumpkin-8",
                                      "as_host": True}).json()
        ev = c.app.state.ev
        for p in (a, b, h):
            _pumpkin(ev, p["me"]["id"])
        with c.websocket_connect("/ws?role=host") as host, \
                c.websocket_connect(f"/ws?role=player&token={a['token']}") as wa, \
                c.websocket_connect(f"/ws?role=player&token={b['token']}") as wb:
            for w in (host, wa, wb):
                recv_until(w, "snapshot")
            cmd(host, "set_scene", scene="carve_vote")
            cmd(host, "vote_start")
            n = {e["player_id"]: e["n"] for e in ev.vote.st["entries"]}
            cmd(wa, "vote", n=n[h["me"]["id"]])   # оба голосуют за тыкву ведущего
            cmd(wb, "vote", n=n[h["me"]["id"]])
            cmd(host, "vote_close")
            res = {r["player_id"]: r for r in ev.vote.st["results"]}
            assert res[h["me"]["id"]]["votes"] == 2 and res[h["me"]["id"]]["place"] is None
            assert ev.total(h["me"]["id"]) == 0
            # сброс голосования: бонусы удалены, тыквы снова можно менять
            assert cmd(host, "vote_reset")["ok"]
            assert ev.settings["carve_locked"] is False and ev.vote.phase == "idle"
            assert cmd(host, "vote_start")["ok"]


def test_timer_add_after_finish_restarts(data_dir):
    with client(data_dir, speed=60) as c:
        ev = c.app.state.ev
        with c.websocket_connect("/ws?role=host") as host:
            recv_until(host, "snapshot")
            cmd(host, "set_scene", scene="timer")
            cmd(host, "timer_set", minutes=0.05)
            wait(host, "timer", lambda m: m["timer"]["finished"])
            assert cmd(host, "timer_add", seconds=60)["ok"]
            assert ev.timer.st["running"] and not ev.timer.st["finished"]


def test_content_checker_case_sensitive_names(tmp_path):
    from server.content_check import check
    (tmp_path / "images" / "sorts").mkdir(parents=True)
    Image.new("RGB", (8, 8)).save(tmp_path / "images" / "sorts" / "Butternut.jpg")
    qs = "\n".join(
        f"    - id: r2q{i:02d}\n      text: t\n      options: [a, b, c, d]\n      correct: 0\n"
        f"      image: sorts/{'butternut' if i == 1 else 'Butternut'}.jpg" for i in range(1, 3))
    (tmp_path / "quiz.yaml").write_text(
        "rounds:\n  - id: r1\n    title: a\n    questions: []\n  - id: r2\n    title: b\n    questions:\n" + qs +
        "\n  - id: r3\n    title: c\n    questions: []\n", encoding="utf-8")
    (tmp_path / "facts.yaml").write_text("[]", encoding="utf-8")
    errors, _ = check(tmp_path)
    text = "\n".join(errors)
    assert "регистр" in text          # sorts/butternut.jpg при файле Butternut.jpg
    assert "нижнем регистре" in text  # имя с заглавной буквой


def test_js_syntax():
    import shutil
    import subprocess

    import pytest
    node = shutil.which("node")
    if not node:
        pytest.skip("node не установлен")
    r = subprocess.run([node, "--experimental-vm-modules", str(ROOT / "tools" / "check_js.mjs")],
                       capture_output=True, text=True, encoding="utf-8")
    assert r.returncode == 0, r.stdout + r.stderr


def test_numeric_fact_ids_are_strings(tmp_path):
    from server.content import Content
    (tmp_path / "facts.yaml").write_text("- id: 001\n  text: Факт\n", encoding="utf-8")
    assert Content(tmp_path).fact("1")["id"] == "1"


def test_timer_rejects_nan(data_dir):
    with client(data_dir) as c:
        with c.websocket_connect("/ws?role=host") as host:
            recv_until(host, "snapshot")
            cmd(host, "timer_set", minutes=5)
            assert cmd(host, "timer_add", seconds="nan")["ok"] is False
            assert cmd(host, "timer_set", minutes="inf")["ok"] is False
        with c.websocket_connect("/ws?role=host") as host:
            assert recv_until(host, "snapshot")["timer"]["running"] is True


def test_carve_save_refused_if_vote_opened_meanwhile(data_dir):
    from server import carve
    with client(data_dir) as c:
        a = join(c, "Аня", "pumpkin-1")
        ev = c.app.state.ev
        files = {f"{n}.png": png_bytes(256) for n in carve.MASK_NAMES}
        files.update({f"{n}.jpg": jpeg(64, 64) for n in carve.SHOT_NAMES})
        meta = carve.prepare(ev, a["me"]["id"], files, {"theta": 0, "phi": 1, "radius": 4})
        ev._set("carve_locked", True)  # голосование открыли, пока писались файлы
        import pytest
        from server.state import CmdError
        with pytest.raises(CmdError):
            carve.commit(ev, a["me"]["id"], meta)
        assert not carve.pumpkin_dir(ev, a["me"]["id"]).exists()
        assert not list((data_dir / "pumpkins").glob("*.new-*"))


def png_bytes(size):
    buf = io.BytesIO()
    Image.new("L", (size, size), 0).save(buf, "PNG")
    return buf.getvalue()


# ---------------------------------------------------------------------- охота за семечками
def test_seeds_first_finder_wins_and_scores(data_dir):
    with client(data_dir, tv_localhost_only=False) as c:
        ev = c.app.state.ev
        a, b = join(c, "Аня", "pumpkin-1"), join(c, "Боря", "pumpkin-2")
        host = ev.join("Ведущий", "pumpkin", "pumpkin-3", as_host=True)
        with c.websocket_connect("/ws?role=host") as h, \
                c.websocket_connect(f"/ws?role=player&token={a['token']}") as wa, \
                c.websocket_connect(f"/ws?role=player&token={b['token']}") as wb:
            recv_until(h, "snapshot")
            recv_until(wa, "snapshot")
            recv_until(wb, "snapshot")
            assert cmd(h, "seeds_start")["code"] == "wrong_scene"
            assert cmd(h, "set_scene", scene="seeds")["ok"]
            assert cmd(h, "seeds_start")["ok"]
            assert cmd(wa, "seeds_enter", code="2201")["code"] == "not_started"
            ev.seeds.st["start_at"] = ev.clock.now() - 1
            ev.seeds.tick()
            assert ev.seeds.phase == "running"
            r = cmd(wa, "seeds_enter", code="22 01")
            assert r["ok"] and r["kind"] == "regular" and r["points"] == 30
            r = cmd(wb, "seeds_enter", code="2201")
            assert r["code"] == "taken" and "Аня" in r["error"]
            assert cmd(wa, "seeds_enter", code="2201")["code"] == "mine"
            assert cmd(wb, "seeds_enter", code="7364")["points"] == 300  # радужная
            with pytest.raises(CmdError) as e:
                ev.seeds.enter(host.id, "9325")
            assert e.value.code == "host"
        assert ev.breakdown(a["me"]["id"])["seeds"] == 30
        assert ev.breakdown(b["me"]["id"])["seeds"] == 300
        board = ev.seeds.board()
        assert [r["name"] for r in board] == ["Боря", "Аня"]
        assert ev.seeds.counts()["rainbow"] == {"total": 1, "found": 1}
        grp = [r for g in ev.finale.build_groups() for r in g]
        assert next(r for r in grp if r["name"] == "Боря")["breakdown"]["seeds"] == 300


def test_seeds_wrong_codes_cooldown_and_finish(data_dir):
    with client(data_dir, tv_localhost_only=False) as c:
        ev = c.app.state.ev
        a = join(c, "Аня", "pumpkin-1")
        ev.set_scene("seeds")
        ev.seeds.start()
        ev.seeds.st["start_at"] = ev.clock.now() - 1
        ev.seeds.tick()
        for _ in range(2):
            with pytest.raises(CmdError) as e:
                ev.seeds.enter(a["me"]["id"], "0000")
            assert e.value.code == "wrong" and "until_ms" not in e.value.extra
        with pytest.raises(CmdError) as e:
            ev.seeds.enter(a["me"]["id"], "0000")
        assert e.value.extra["until_ms"] > ev.clock.now() * 1000
        with pytest.raises(CmdError) as e:
            ev.seeds.enter(a["me"]["id"], "2201")  # даже верный код ждёт конца паузы
        assert e.value.code == "cooldown"
        assert ev.seeds.public("player", a["me"]["id"])["my"]["cooldown_until_ms"]
        ev.seeds.st["fails"][str(a["me"]["id"])]["until"] = 0
        assert ev.seeds.enter(a["me"]["id"], "2201")["points"] == 30
        assert ev.scene_is_live("seeds")
        ev.seeds.st["end_at"] = ev.clock.now() - 1
        ev.seeds.tick()
        assert ev.seeds.phase == "finished" and not ev.scene_is_live("seeds")
        with pytest.raises(CmdError):
            ev.seeds.enter(a["me"]["id"], "9325")
        with pytest.raises(CmdError):
            ev.seeds.start()  # второй раз нельзя, только через сброс
        ev.seeds.reset()
        assert ev.seeds.phase == "idle" and "seeds" not in ev.breakdown(a["me"]["id"])
        page = c.get("/seeds/print").text
        assert "7364" in page and "Шпаргалка" in page


# ---------------------------------------------------------------------- бомба
def _bomb_go(ev):
    """Отсчёт или пауза после взрыва прошли: следующий ход."""
    st = ev.bomb.st
    if st["phase"] == "countdown":
        st["start_at"] = ev.clock.now() - 1
    elif st["phase"] == "boom":
        st["resume_at"] = ev.clock.now() - 1
    ev.bomb.tick()
    assert ev.bomb.phase == "running"


def _bomb_timeout(ev):
    ev.bomb.st["deadline"] = ev.clock.now() - 0.01
    ev.bomb.tick()


def test_bomb_round_passes_explosions_and_points(data_dir):
    with client(data_dir, tv_localhost_only=False) as c:
        ev = c.app.state.ev
        a, b, v = join(c, "Аня", "pumpkin-1"), join(c, "Боря", "pumpkin-2"), join(c, "Вика", "pumpkin-3")
        ids = {r["me"]["name"]: r["me"]["id"] for r in (a, b, v)}
        with c.websocket_connect("/ws?role=host") as h, \
                c.websocket_connect(f"/ws?role=player&token={a['token']}") as wa, \
                c.websocket_connect(f"/ws?role=player&token={b['token']}") as wb, \
                c.websocket_connect(f"/ws?role=player&token={v['token']}") as wv:
            for ws in (h, wa, wb, wv):
                recv_until(ws, "snapshot")
            assert cmd(h, "bomb_topic")["code"] == "wrong_scene"
            assert cmd(h, "set_scene", scene="bomb")["ok"]
            assert ev.next_step()["cmd"] == "bomb_topic"
            assert cmd(h, "bomb_start")["code"] == "no_topic"
            assert cmd(h, "bomb_topic")["ok"]
            st = ev.bomb.public("player", ids["Аня"])
            assert st["phase"] == "topic" and st["round"] == 1 and st["topic"]
            assert [p["name"] for p in st["players"]] == ["Аня", "Боря", "Вика"] and st["my"]["in_round"]
            assert cmd(h, "bomb_start")["ok"]
            assert ev.scene_is_live("bomb")
            _bomb_go(ev)
            assert ev.bomb.st["holder"] == ids["Аня"] and ev.bomb.st["turn_seconds"] == 5
            assert cmd(wb, "bomb_pass")["code"] == "not_holder"
            r = cmd(wa, "bomb_pass")
            assert r["ok"] and r["to"] == ids["Боря"]
            assert cmd(wa, "bomb_pass")["code"] == "not_holder"  # двойное нажатие не уводит бомбу дальше
            assert cmd(wb, "bomb_pass")["to"] == ids["Вика"]
            assert cmd(wv, "bomb_pass")["to"] == ids["Аня"]
            assert ev.bomb.st["turn_seconds"] == 4  # второй круг на секунду короче
            ev.bomb.st["deadline"] = ev.clock.now() - 0.01
            assert cmd(wa, "bomb_pass")["code"] == "late"
            ev.bomb.tick()
            assert ev.bomb.phase == "boom" and ev.bomb.st["boom"]["place"] == 3
            assert ev.bomb.public("player", ids["Аня"])["my"] == {
                "player_id": ids["Аня"], "can_play": True, "in_round": True, "alive": False, "holder": False, "place": 3, "points": 0}
            _bomb_go(ev)
            assert ev.bomb.st["holder"] == ids["Боря"]  # бомба у следующего за взорвавшимся
            assert cmd(h, "bomb_boom")["ok"]  # ведущий взрывает вручную (повтор слова)
            assert ev.bomb.phase == "round_over" and not ev.scene_is_live("bomb")
            res = ev.bomb.public("tv")["results"]
            assert [(r["name"], r["place"], r["points"]) for r in res] == [
                ("Вика", 1, 500), ("Боря", 2, 400), ("Аня", 3, 300)]
            assert ev.next_step()["cmd"] == "bomb_topic"
        assert ev.breakdown(ids["Вика"])["bomb"] == 500
        grp = [r for g in ev.finale.build_groups() for r in g]
        assert next(r for r in grp if r["name"] == "Боря")["breakdown"]["bomb"] == 400


def test_bomb_rounds_timing_order_host_and_reset(data_dir):
    with client(data_dir, tv_localhost_only=False) as c:
        ev = c.app.state.ev
        a, b = join(c, "Аня", "pumpkin-1"), join(c, "Боря", "pumpkin-2")
        host = ev.join("Ведущий", "pumpkin", "pumpkin-3", as_host=True)  # вне зачёта, но играет
        for p in ev.players.values():
            p.connections = 1
        aid, bid = a["me"]["id"], b["me"]["id"]
        ev.set_scene("bomb")
        for bad in ((1, 1, 1), (5, -1, 2), (5, 1, 6), ("x", 1, 1)):
            with pytest.raises(CmdError):
                ev.bomb.set_timing(*bad)
        ev.bomb.set_timing(3, 2, 1)
        with pytest.raises(CmdError):
            ev.bomb.set_order([aid, aid])
        ev.bomb.set_order([host.id, bid, aid])
        ev.bomb.pick_topic()
        first = ev.bomb.st["topic"]
        ev.bomb.pick_topic()  # «другая тема» того же раунда
        assert ev.bomb.st["round"] == 1 and ev.bomb.st["topic"] != first
        ev.bomb.start()
        _bomb_go(ev)
        assert ev.bomb.st["holder"] == host.id and ev.bomb.st["turn_seconds"] == 3
        with pytest.raises(CmdError):
            ev.bomb.set_order([aid, bid, host.id])  # во время раунда порядок не меняется
        for pid in (host.id, bid, aid):
            ev.bomb.pass_bomb(pid)
        assert ev.bomb.st["turn_seconds"] == 1  # 3 − 2, не меньше минимума
        ev.bomb.pass_bomb(host.id)
        ev.bomb.pass_bomb(bid)
        _bomb_timeout(ev)  # Аня
        _bomb_go(ev)
        assert ev.bomb.st["holder"] == host.id
        _bomb_timeout(ev)  # ведущий, Боря выиграл
        assert ev.bomb.phase == "round_over"
        rows = ev.bomb.st["results"]["1"]
        # ведущий вне зачёта занял 2 место, но очки за 2 место ушли следующему в зачёте
        assert [(r["player_id"], r["place"], r["points"]) for r in rows] == [
            (bid, 1, 500), (host.id, 2, 0), (aid, 3, 400)]
        # раунды 2 и 3; начинает следующий по кругу
        for rnd in (2, 3):
            ev.bomb.pick_topic()
            ev.bomb.start()
            _bomb_go(ev)
            assert ev.bomb.st["holder"] == [host.id, bid, aid][rnd - 1]
            while ev.bomb.phase != "round_over":
                if ev.bomb.phase == "boom":
                    _bomb_go(ev)
                _bomb_timeout(ev)
        assert ev.bomb.done() and ev.next_step()["cmd"] == "set_scene"
        assert len(set(ev.bomb.st["topics_used"])) == 3
        with pytest.raises(CmdError) as e:
            ev.bomb.pick_topic()
        assert e.value.code == "done"
        total = ev.breakdown(aid)["bomb"] + ev.breakdown(bid)["bomb"]
        assert total == 3 * (500 + 400) and "bomb" not in ev.breakdown(host.id)
        ev.bomb.reset()
        assert ev.bomb.phase == "idle" and "bomb" not in ev.breakdown(aid)
        assert ev.bomb.timing()["start_seconds"] == 3  # настройки ведущего переживают сброс


def test_bomb_needs_two_players_and_aborts_when_scene_left(data_dir):
    with client(data_dir, tv_localhost_only=False) as c:
        ev = c.app.state.ev
        a, b = join(c, "Аня", "pumpkin-1"), join(c, "Боря", "pumpkin-2")
        ev.set_scene("bomb")
        ev.bomb.pick_topic()
        with pytest.raises(CmdError) as e:
            ev.bomb.start()  # никого нет в сети
        assert e.value.code == "few_players"
        for p in ev.players.values():
            p.connections = 1
        ev.bomb.start()
        _bomb_go(ev)
        ev.set_scene("ambient", force=True)
        ev.bomb.tick()
        assert ev.bomb.phase == "topic" and ev.bomb.st["round"] == 1 and not ev.bomb.st["topics_used"]
        assert "bomb" not in ev.breakdown(a["me"]["id"]) and "bomb" not in ev.breakdown(b["me"]["id"])
