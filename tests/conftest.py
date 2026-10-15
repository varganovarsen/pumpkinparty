import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from server.app import create_app  # noqa: E402
from server.config import load_config  # noqa: E402


def make_client(data_dir: Path, **over) -> TestClient:
    cfg = load_config(ROOT / "config.yaml", data_dir=str(data_dir), **over)
    return TestClient(create_app(cfg))


@pytest.fixture
def data_dir(tmp_path):
    return tmp_path / "data"


@pytest.fixture
def client(data_dir):
    with make_client(data_dir) as c:
        yield c


def join(client, name, avatar="pumpkin-1", **kw):
    return client.post("/api/join", json={"name": name, "avatar_kind": "pumpkin", "avatar_ref": avatar, **kw})


def recv_until(ws, t, limit=50):
    for _ in range(limit):
        m = ws.receive_json()
        if m.get("t") == t:
            return m
    raise AssertionError(f"не дождались {t}")


def cmd(ws, name, **args):
    ws.send_json({"t": "cmd", "cmd": name, "id": 1, **args})
    return recv_until(ws, "reply")
