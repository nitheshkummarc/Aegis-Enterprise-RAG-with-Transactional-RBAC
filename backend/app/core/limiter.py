"""SlowAPI rate limiter instance.

Uses X-Forwarded-For when behind a reverse proxy (nginx, cloud load balancer),
falling back to the direct connection IP when no proxy header is present.
Without this, all clients behind a proxy share a single rate-limit bucket.
"""

from starlette.requests import Request
from slowapi import Limiter


def _get_real_client_ip(request: Request) -> str:
    """Extract the real client IP, respecting X-Forwarded-For if present.

    When behind a reverse proxy, the direct connection IP is the proxy's IP.
    X-Forwarded-For contains the original client IP as the first entry.
    """
    forwarded_for = request.headers.get("X-Forwarded-For")
    if forwarded_for:
        # X-Forwarded-For: client, proxy1, proxy2 — take the first (client)
        return forwarded_for.split(",")[0].strip()
    # Fallback: direct connection IP (no proxy)
    if request.client:
        return request.client.host
    return "127.0.0.1"


limiter = Limiter(key_func=_get_real_client_ip)
