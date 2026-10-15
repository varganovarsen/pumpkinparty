import io

from PIL import Image

from conftest import ROOT, cmd, join, make_client, recv_until


def test_join_and_duplicates(client):
    r = join(client, "Аня")
    assert r.status_code == 200 and r.json()["token"]
    r = join(client, "  аня ", avatar="pumpkin-2")
    assert r.status_code == 409 and r.json()["code"] == "name_taken"
    assert r.json()["can_claim"] is True  # Аня не в сети
    r = join(client, "Паша", avatar="pumpkin-1")
    assert r.json()["code"] == "avatar_taken"
    assert join(client, "", avatar="pumpkin-3").json()["code"] == "bad_name"
    assert join(client, "x" * 21, avatar="pumpkin-3").json()["code"] == "bad_name"
    info = client.get("/api/info").json()
    assert [a["id"] for a in info["avatars"] if a["taken"]] == ["pumpkin-1"]


def test_token_restores_player_and_claim(client):
    token = join(client, "Аня").json()["token"]
    with client.websocket_connect(f"/ws?role=player&token={token}") as ws:
        snap = recv_until(ws, "snapshot")
        assert snap["me"]["name"] == "Аня" and snap["scene"]["scene"] == "ambient"
        # пока Аня в сети, «Это я?» не работает
        assert client.post("/api/claim", json={"name": "аня"}).json()["code"] == "name_taken"
    r = client.post("/api/claim", json={"name": "аня"}).json()
    assert r["ok"] and r["token"] == token


def test_bad_token_rejected(client):
    with client.websocket_connect("/ws?role=player&token=nope") as ws:
        assert ws.receive_json()["t"] == "auth_failed"


def test_scene_switch_reaches_players(client):
    token = join(client, "Аня").json()["token"]
    with client.websocket_connect("/ws?role=host") as host, \
            client.websocket_connect(f"/ws?role=player&token={token}") as pl:
        recv_until(host, "snapshot")
        recv_until(pl, "snapshot")
        assert cmd(host, "set_scene", scene="timer")["ok"]
        m = recv_until(pl, "scene")
        assert m["scene"] == "timer" and m["participating"] is False
        assert cmd(host, "set_scene", scene="game")["ok"]
        assert recv_until(pl, "scene")["participating"] is True
        # выход из живой сцены требует подтверждения
        r = cmd(host, "set_scene", scene="ambient")
        assert not r["ok"] and r["code"] == "confirm_required"
        assert cmd(host, "set_scene", scene="ambient", force=True)["ok"]


def test_player_cannot_switch_scene(client):
    token = join(client, "Аня").json()["token"]
    with client.websocket_connect(f"/ws?role=player&token={token}") as pl:
        recv_until(pl, "snapshot")
        assert cmd(pl, "set_scene", scene="quiz")["code"] == "forbidden"


def test_manual_score_and_log(client):
    pid = join(client, "Аня").json()["me"]["id"]
    with client.websocket_connect("/ws?role=host") as host:
        recv_until(host, "snapshot")
        assert cmd(host, "adjust_score", player_id=pid, amount=150, note="за костюм")["ok"]
        assert cmd(host, "adjust_score", player_id=pid, amount=-50)["ok"]
        assert not cmd(host, "adjust_score", player_id=pid, amount=0)["ok"]
        log = cmd(host, "get_log", player_id=pid)["log"]
    assert any("+150 (за костюм)" in e["text"] for e in log)
    ev = client.app.state.ev
    assert ev.total(pid) == 100
    assert ev.breakdown(pid) == {"manual": 100}


def test_restart_keeps_state(data_dir):
    with make_client(data_dir) as c:
        me = join(c, "Аня").json()
        with c.websocket_connect("/ws?role=host") as host:
            recv_until(host, "snapshot")
            cmd(host, "set_scene", scene="quiz")
            cmd(host, "adjust_score", player_id=me["me"]["id"], amount=200)
            cmd(host, "set_setting", key="hide_total", value=True)
    with make_client(data_dir) as c:
        with c.websocket_connect(f"/ws?role=player&token={me['token']}") as pl:
            snap = recv_until(pl, "snapshot")
        assert snap["scene"]["scene"] == "quiz"
        assert snap["me"]["score"] is None  # общий рейтинг скрыт
        assert c.app.state.ev.total(me["me"]["id"]) == 200


def test_reset_backs_up_and_clears(client, data_dir):
    token = join(client, "Аня").json()["token"]
    with client.websocket_connect("/ws?role=host") as host, \
            client.websocket_connect(f"/ws?role=player&token={token}") as pl:
        recv_until(host, "snapshot")
        recv_until(pl, "snapshot")
        assert not cmd(host, "reset_evening")["ok"]  # без подтверждения нельзя
        r = cmd(host, "reset_evening", confirm="СБРОС")
        assert r["ok"] and r["backup"].startswith("before_reset_")
        recv_until(pl, "reset")
    assert (data_dir / "backups" / r["backup"] / "pumpkin.db").exists()
    assert client.app.state.ev.players == {}
    assert join(client, "Аня").status_code == 200


def test_host_scoring_toggle(client):
    me = join(client, "Ведущий", as_host=True).json()["me"]
    assert me["is_host"] and not me["in_scoring"]
    assert join(client, "Второй", avatar="pumpkin-2", as_host=True).json()["code"] == "host_exists"
    with client.websocket_connect("/ws?role=host") as host:
        recv_until(host, "snapshot")
        assert cmd(host, "set_setting", key="host_in_scoring", value=True)["ok"]
    assert client.app.state.ev.players[me["id"]].in_scoring


def test_tv_localhost_only(client):
    # TestClient приходит с адреса «testclient», не localhost
    assert client.get("/tv").status_code == 403
    with client.websocket_connect("/ws?role=tv") as ws:
        assert ws.receive_json()["code"] == "tv_localhost_only"


def test_tv_allowed_when_disabled(data_dir):
    with make_client(data_dir, tv_localhost_only=False) as c:
        assert c.get("/tv").status_code == 200
        with c.websocket_connect("/ws?role=tv") as ws:
            snap = recv_until(ws, "snapshot")
            assert "rive/head.riv" in snap["stubs"]


def test_head_marks_fact_shown(data_dir):
    with make_client(data_dir, tv_localhost_only=False) as c:
        token = join(c, "Аня").json()["token"]
        with c.websocket_connect("/ws?role=host") as host, c.websocket_connect("/ws?role=tv") as tv, \
                c.websocket_connect(f"/ws?role=player&token={token}") as pl:
            recv_until(host, "snapshot")
            recv_until(tv, "snapshot")
            facts0 = recv_until(pl, "snapshot")["facts"]
            assert all(f["text"] is None for f in facts0)
            assert cmd(host, "head_call")["ok"]
            head = recv_until(tv, "head")["head"]
            cmd(tv, "head_shown", fact_id=head["fact_id"])
            facts = recv_until(pl, "facts")["facts"]
            assert sum(1 for f in facts if f["text"]) == 1
            cmd(host, "set_scene", scene="timer")
            assert cmd(host, "head_call")["code"] == "wrong_scene"


def test_avatar_upload_and_crop(client, data_dir):
    img = Image.new("RGB", (400, 300), (200, 100, 50))
    exif = Image.Exif()
    exif[0x0112] = 6  # повернуть на 90°
    buf = io.BytesIO()
    img.save(buf, "JPEG", exif=exif)
    r = client.post("/api/upload_avatar", files={"file": ("a.jpg", buf.getvalue(), "image/jpeg")}).json()
    assert r["ok"]
    prev = Image.open(io.BytesIO(client.get(r["preview_url"]).content))
    assert prev.size == (300, 400)  # EXIF-поворот применён
    c = client.post("/api/avatar_crop", json={"upload_id": r["upload_id"], "cx": .5, "cy": .5, "size": 1}).json()
    av = Image.open(io.BytesIO(client.get(c["avatar_url"]).content))
    assert av.size == (256, 256) and av.mode == "RGBA"
    j = client.post("/api/join", json={"name": "Фото", "avatar_kind": "photo", "avatar_ref": c["avatar_ref"]}).json()
    assert j["ok"] and j["me"]["avatar_url"] == c["avatar_url"]
    # фото-профиль не занимает аватар-тыкву
    assert not any(a["taken"] for a in client.get("/api/info").json()["avatars"])


def test_heic_upload(client):
    from pillow_heif import from_pillow
    buf = io.BytesIO()
    from_pillow(Image.new("RGB", (64, 48), (10, 200, 10))).save(buf, quality=80)
    r = client.post("/api/upload_avatar", files={"file": ("a.heic", buf.getvalue(), "image/heic")}).json()
    assert r["ok"]


def test_check_endpoint(client):
    r = client.get("/api/check").json()
    ids = {i["id"] for i in r["items"]}
    assert {"address", "tv", "phones", "assets", "content", "python", "disk", "session"} <= ids
    assets = next(i for i in r["items"] if i["id"] == "assets")
    assert assets["status"] == "warn" and any("head.riv" in x for x in assets["items"])


def test_qr_and_pages(client):
    assert client.get("/api/qr.svg").headers["content-type"].startswith("image/svg")
    for path in ("/", "/host", "/check", "/carve", "/download"):
        assert client.get(path).status_code == 200
    # вопросы квиза наружу не отдаются
    assert client.get("/content/quiz.yaml").status_code == 404
    assert client.get("/media/avatars/..%2Fpumpkin.db").status_code == 404


def test_backup_rotation(client, data_dir):
    from server.backup import make_backup
    for _ in range(14):
        make_backup(client.app.state.db, data_dir)
    auto = [p for p in (data_dir / "backups").iterdir() if p.name[0].isdigit()]
    assert len(auto) == 12
    assert all((p / "files.txt").exists() for p in auto)


def test_content_checker_flags_problems(tmp_path):
    from server.content_check import check
    (tmp_path / "facts.yaml").write_text(
        "- id: F 1\n  text: x\n- id: a\n  text: '" + "я" * 230 + "'\n- id: a\n  text: y\n", encoding="utf-8")
    (tmp_path / "quiz.yaml").write_text(
        "rounds:\n - id: r1\n   title: t\n   questions:\n    - id: q1\n      text: t\n      options: [a, b]\n      correct: 5\n",
        encoding="utf-8")
    errors, warnings = check(tmp_path)
    text = "\n".join(errors)
    assert "нижний регистр" in text and "лимит пузыря" in text and "повтор id" in text
    assert "ровно 4 варианта" in text and "correct" in text
    assert any("quiz" in w for w in warnings)
    errors, _ = check(ROOT / "content")  # пример контента читается без падений


def _png(size=256, value=0):
    buf = io.BytesIO()
    Image.new("L", (size, size), value).save(buf, "PNG")
    return buf.getvalue()


def _jpg():
    buf = io.BytesIO()
    Image.new("RGB", (64, 64), (200, 100, 0)).save(buf, "JPEG")
    return buf.getvalue()


def _pumpkin_files(through=_png, size=256):
    return {
        "through.png": ("t.png", through(size, 255), "image/png"),
        "depth.png": ("d.png", _png(size, 10), "image/png"),
        "lit.jpg": ("a.jpg", _jpg(), "image/jpeg"),
        "dark.jpg": ("b.jpg", _jpg(), "image/jpeg"),
        "side.jpg": ("c.jpg", _jpg(), "image/jpeg"),
    }


def test_pumpkin_save_and_load(client, data_dir):
    import json
    pid = join(client, "Аня").json()["me"]["id"]
    assert client.get(f"/api/pumpkin/{pid}").json()["exists"] is False
    cam = json.dumps({"theta": 0.3, "phi": 1.2, "radius": 4})
    r = client.post(f"/api/pumpkin/{pid}", files=_pumpkin_files(), data={"camera": cam}).json()
    assert r["ok"] and r["version"] == 1 and r["camera"]["theta"] == 0.3
    r = client.post(f"/api/pumpkin/{pid}", files=_pumpkin_files(), data={"camera": cam}).json()
    assert r["version"] == 2
    got = client.get(f"/api/pumpkin/{pid}").json()
    t = Image.open(io.BytesIO(client.get(got["masks"]["through"]).content))
    assert t.mode == "L" and t.size == (256, 256) and t.getpixel((0, 0)) == 255
    assert client.get(got["shots"]["side"]).status_code == 200
    assert sorted(p.name for p in (data_dir / "pumpkins").iterdir()) == [str(pid)]  # только последняя версия
    with client.websocket_connect("/ws?role=carve") as ws:
        snap = recv_until(ws, "snapshot")
        assert snap["players"][0]["pumpkin_version"] == 2


def test_pumpkin_rejects_bad_input(client):
    import json
    pid = join(client, "Аня").json()["me"]["id"]
    cam = json.dumps({"theta": 0, "phi": 1, "radius": 4})
    files = _pumpkin_files()
    files["depth.png"] = ("d.png", _png(128), "image/png")
    assert client.post(f"/api/pumpkin/{pid}", files=files, data={"camera": cam}).json()["code"] == "bad_mask"
    files = _pumpkin_files()
    del files["side.jpg"]
    assert client.post(f"/api/pumpkin/{pid}", files=files, data={"camera": cam}).status_code == 400
    assert client.post(f"/api/pumpkin/{pid}", files=_pumpkin_files(), data={"camera": "{}"}).status_code == 400
    assert client.post("/api/pumpkin/999", files=_pumpkin_files(), data={"camera": cam}).status_code == 404
    client.app.state.ev.settings["carve_locked"] = True
    assert client.post(f"/api/pumpkin/{pid}", files=_pumpkin_files(), data={"camera": cam}).json()["code"] == "locked"
