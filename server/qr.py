"""QR-коды и адрес сервера в локальной сети."""
from __future__ import annotations

import io
import socket
from functools import lru_cache

import qrcode
import qrcode.image.svg


def detect_ip() -> str:
    """IP ноутбука в локальной сети (без отправки пакетов наружу)."""
    for probe in ("10.255.255.255", "192.168.255.255", "8.8.8.8"):
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            s.connect((probe, 1))
            ip = s.getsockname()[0]
            if ip and not ip.startswith("127."):
                return ip
        except OSError:
            pass
        finally:
            s.close()
    try:
        return socket.gethostbyname(socket.gethostname())
    except OSError:
        return "127.0.0.1"


def base_url(public_host: str, port: int) -> str:
    host = (public_host or "").strip() or detect_ip()
    if host.startswith("http://") or host.startswith("https://"):
        return host.rstrip("/")
    if ":" in host:
        return f"http://{host}"
    return f"http://{host}:{port}"


@lru_cache(maxsize=32)
def svg(data: str) -> bytes:
    qr = qrcode.QRCode(border=2, error_correction=qrcode.constants.ERROR_CORRECT_M)
    qr.add_data(data)
    qr.make(fit=True)
    img = qr.make_image(image_factory=qrcode.image.svg.SvgPathFillImage)
    buf = io.BytesIO()
    img.save(buf)
    return buf.getvalue()
