"""Редактор конфига в браузере: роли, сырьё, блюда, числа баланса и прогон ботов.

    python -m fair edit [--config путь] [--port 8765]

Сохраняет config.yaml через ruamel.yaml, чтобы не терять комментарии; без него пишет через
pyyaml (комментарии пропадут — предупреждает). Только stdlib-сервер на 127.0.0.1.
"""
from __future__ import annotations

import copy
import io
import json
import re
import shutil
import traceback
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import yaml

from . import config
from .runner import make_game, run_many
from .stats import Summary

HTML = Path(__file__).with_name("editor.html")

try:
    from ruamel.yaml import YAML
    from ruamel.yaml.comments import CommentedMap, CommentedSeq
except ImportError:  # pragma: no cover
    YAML = None


# --- конфиг из браузера: JSON теряет числовые ключи, возвращаем

def from_json(cfg: dict) -> dict:
    cfg = copy.deepcopy(cfg)
    qw = cfg.get("buyer", {}).get("qty_weights")
    if isinstance(qw, dict):
        cfg["buyer"]["qty_weights"] = {int(k) if str(k).isdigit() else k: v for k, v in qw.items()}
    return cfg


def validate(cfg: dict) -> list[str]:
    """Пусто — конфиг годится: контент сходится и одна партия ботов доигрывается."""
    try:
        config.Content(cfg)
    except Exception as e:
        return [str(e)]
    try:
        make_game(copy.deepcopy(cfg), 1).run()
    except Exception as e:
        return [f"партия не доигрывается: {type(e).__name__}: {e}"]
    return []


# --- сохранение с комментариями

def _flow(node) -> bool:
    return bool(getattr(node, "fa", None) and node.fa.flow_style())


def _convert(value, flow: bool = False):
    if isinstance(value, dict):
        m = CommentedMap((k, _convert(v)) for k, v in value.items())
        if flow:
            m.fa.set_flow_style()
        return m
    if isinstance(value, list):
        s = CommentedSeq(_convert(v, flow=True) for v in value)
        s.fa.set_flow_style()
        return s
    return value


def merge(node, new):
    """Вписать новые значения в дерево ruamel, сохранив комментарии, порядок и стиль там, где ключи уцелели."""
    if isinstance(node, CommentedMap) and isinstance(new, dict):
        sibling_flow = any(_flow(v) for v in node.values() if isinstance(v, CommentedMap))
        for k in [k for k in node if k not in new]:
            del node[k]
        for i, (k, v) in enumerate(new.items()):
            keys = list(node)
            if i < len(keys) and keys[i] == k:
                node[k] = merge(node[k], v)
            elif k in node:
                old = node.pop(k)
                node.insert(i, k, merge(old, v))
            else:
                node.insert(i, k, _convert(v, flow=sibling_flow))
        return node
    if isinstance(node, CommentedSeq) and isinstance(new, list):
        if list(node) == new:
            return node
        return _convert(new, flow=_flow(node)) if _flow(node) else CommentedSeq(_convert(v, True) for v in new)
    if isinstance(new, (dict, list)):
        return _convert(new, flow=isinstance(new, dict) and _flow(node))
    if isinstance(node, float) and isinstance(new, int) and not isinstance(new, bool):
        return float(new)  # 1.0 из браузера приходит как 1
    return new


def save(path: Path, cfg: dict) -> str:
    shutil.copyfile(path, path.with_suffix(path.suffix + ".bak"))
    if YAML is None:
        with open(path, "w", encoding="utf-8") as f:
            yaml.safe_dump(cfg, f, allow_unicode=True, sort_keys=False)
        return "сохранено без комментариев (нет ruamel.yaml)"
    ry = YAML()
    ry.preserve_quotes = True
    ry.width = 200
    ry.indent(mapping=2, sequence=4, offset=2)
    with open(path, encoding="utf-8") as f:
        tree = ry.load(f)
    merge(tree, cfg)
    buf = io.StringIO()
    ry.dump(tree, buf)
    path.write_text(align_flow(buf.getvalue()), encoding="utf-8")
    return "сохранено"


FLOW_LINE = re.compile(r"^( +)([^ #:][^:]*):\s+(\{.*)$")


def align_flow(text: str) -> str:
    """Подряд идущие «  ключ: {…}» на одном отступе — значения в колонку, как в рукописном config.yaml."""
    lines = text.split("\n")
    i = 0
    while i < len(lines):
        m = FLOW_LINE.match(lines[i])
        j = i
        while j < len(lines) and (mj := FLOW_LINE.match(lines[j])) and mj.group(1) == (m and m.group(1)):
            j += 1
        if j - i > 1:
            run = [FLOW_LINE.match(x) for x in lines[i:j]]
            w = max(len(r.group(2)) for r in run) + 2
            for k, r in enumerate(run):
                lines[i + k] = f"{r.group(1)}{(r.group(2) + ':').ljust(w)}{r.group(3)}"
        i = max(j, i + 1)
    return "\n".join(lines)


# --- прогон

def simulate(cfg: dict, n: int, seed: int) -> dict:
    s = Summary(run_many(cfg, n, seed), cfg)
    return {
        "n": s.n_games, "mean_coins": s.mean_coins, "winner_coins": s.winner_coins, "spread": s.spread,
        "by_role": s.by_role, "by_arch": s.by_arch, "income_share": s.income_share,
        "penalty_share": s.penalty_share, "push_share": s.push_share, "push_rate": s.push_rate,
        "dishes_before": s.dishes_before, "dishes_in_range": s.dishes_in_range,
        "sellthrough": s.sellthrough, "price_ratio": s.price_ratio, "counter_rate": s.counter_rate,
        "stock_by_day": s.stock_by_day, "sold_by_day": s.sold_by_day, "dishes_left": s.dishes_left,
        "orders_per_player": s.orders_per_player, "order_fail_rate": s.order_fail_rate,
        "tender_empty_rate": s.tender_empty_rate, "tender_parts": s.tender_parts, "tender_ratio": s.tender_ratio,
        "banquet_size": s.banquet_size, "negative_rate": s.negative_rate, "trades": s.trades,
        "raws_left": s.raws_left, "raw_use": s.raw_use, "cooked_dish": s.cooked_dish,
        "flags": s.flags, "report": s.report(),
    }


# --- сервер

def make_handler(path: Path):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def _send(self, code: int, body: bytes, ctype: str):
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def _json(self, obj, code: int = 200):
            self._send(code, json.dumps(obj, ensure_ascii=False).encode("utf-8"), "application/json; charset=utf-8")

        def do_GET(self):
            if self.path in ("/", "/index.html"):
                self._send(200, HTML.read_bytes(), "text/html; charset=utf-8")
            elif self.path == "/api/config":
                self._json({"path": str(path), "cfg": config.load(path), "comments": YAML is not None})
            else:
                self._send(404, b"not found", "text/plain")

        def do_POST(self):
            try:
                body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")
                cfg = from_json(body["cfg"])
                if self.path == "/api/validate":
                    self._json({"errors": validate(cfg)})
                elif self.path == "/api/save":
                    errors = validate(cfg)
                    if errors:
                        self._json({"errors": errors}, 400)
                    else:
                        self._json({"message": save(path, cfg)})
                elif self.path == "/api/sim":
                    errors = validate(cfg)
                    if errors:
                        self._json({"errors": errors}, 400)
                    else:
                        n = max(1, min(int(body.get("n", 200)), 5000))
                        self._json(simulate(cfg, n, int(body.get("seed", 1))))
                else:
                    self._send(404, b"not found", "text/plain")
            except Exception as e:
                traceback.print_exc()
                self._json({"errors": [f"{type(e).__name__}: {e}"]}, 500)

    return Handler


def serve(path: str | Path | None, port: int = 8765, open_browser: bool = True):
    path = Path(path or config.DEFAULT_PATH).resolve()
    srv = ThreadingHTTPServer(("127.0.0.1", port), make_handler(path))
    url = f"http://127.0.0.1:{port}/"
    print(f"Редактор ярмарки: {url}  (конфиг {path}; Ctrl+C — выход)")
    if YAML is None:
        print("  ⚠ нет ruamel.yaml — при сохранении комментарии в YAML пропадут (pip install ruamel.yaml)")
    if open_browser:
        webbrowser.open(url)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
