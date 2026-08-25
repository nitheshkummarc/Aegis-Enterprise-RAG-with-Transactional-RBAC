"""SlowAPI rate limiter instance.

Uses X-Forwarded-For when behind a reverse proxy (nginx, cloud load balancer),
falling back to the direct connection IP otherwise. X-Forwarded-For is only
honored when the direct connection is in TRUSTED_PROXY_IPS — a client can set
that header to any value on a request it sends directly, so trusting it
unconditionally lets rate limits be bypassed by rotating the header.
"""

from starlette.requests import Request
from slowapi import Limiter

from app.config import get_settings


def _get_direct_ip(request: Request) -> str:
    """IP of whoever opened the TCP connection — not spoofable via headers."""
    return request.client.host if request.client else "127.0.0.1"


def _get_trusted_proxy_ips() -> set[str]:
    raw = get_settings().TRUSTED_PROXY_IPS
    return {ip.strip() for ip in raw.split(",") if ip.strip()}


def _get_real_client_ip(request: Request) -> str:
    """Resolve the client IP for rate-limit keying.

    Only honors X-Forwarded-For when the direct connection IP is a
    configured trusted proxy; otherwise uses the direct connection IP.
    """
    direct_ip = _get_direct_ip(request)

    if direct_ip in _get_trusted_proxy_ips():
        forwarded_for = request.headers.get("X-Forwarded-For")
        if forwarded_for:
            # client, proxy1, proxy2 — first entry is the original client
            return forwarded_for.split(",")[0].strip()

    return direct_ip


limiter = Limiter(key_func=_get_real_client_ip)
