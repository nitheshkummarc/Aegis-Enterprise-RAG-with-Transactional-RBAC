"""Unit tests for the rate limiter's client-IP resolution."""

from app.config import Settings
from app.core import limiter as limiter_module


class FakeClient:
    def __init__(self, host):
        self.host = host


class FakeRequest:
    def __init__(self, client_host, headers=None):
        self.client = FakeClient(client_host) if client_host else None
        self.headers = headers or {}


class TestGetRealClientIP:
    """Tests for _get_real_client_ip."""

    def test_xff_ignored_when_no_trusted_proxies_configured(self, monkeypatch):
        """Default config (TRUSTED_PROXY_IPS unset) must ignore
        X-Forwarded-For — otherwise any direct client can spoof it."""
        monkeypatch.setattr(
            limiter_module, "get_settings", lambda: Settings(TRUSTED_PROXY_IPS="")
        )
        request = FakeRequest(
            client_host="203.0.113.9",
            headers={"X-Forwarded-For": "1.2.3.4"},
        )
        assert limiter_module._get_real_client_ip(request) == "203.0.113.9"

    def test_xff_ignored_when_direct_ip_not_in_trusted_list(self, monkeypatch):
        monkeypatch.setattr(
            limiter_module,
            "get_settings",
            lambda: Settings(TRUSTED_PROXY_IPS="10.0.0.1"),
        )
        request = FakeRequest(
            client_host="203.0.113.9",  # not the trusted proxy
            headers={"X-Forwarded-For": "1.2.3.4"},
        )
        assert limiter_module._get_real_client_ip(request) == "203.0.113.9"

    def test_xff_honored_when_direct_ip_is_trusted_proxy(self, monkeypatch):
        monkeypatch.setattr(
            limiter_module,
            "get_settings",
            lambda: Settings(TRUSTED_PROXY_IPS="10.0.0.1,10.0.0.2"),
        )
        request = FakeRequest(
            client_host="10.0.0.1",
            headers={"X-Forwarded-For": "1.2.3.4, 10.0.0.1"},
        )
        assert limiter_module._get_real_client_ip(request) == "1.2.3.4"

    def test_no_client_falls_back_to_localhost(self, monkeypatch):
        monkeypatch.setattr(
            limiter_module, "get_settings", lambda: Settings(TRUSTED_PROXY_IPS="")
        )
        request = FakeRequest(client_host=None)
        assert limiter_module._get_real_client_ip(request) == "127.0.0.1"

    def test_spoofed_xff_cannot_bypass_rate_limit_bucket(self, monkeypatch):
        """An attacker rotating X-Forwarded-For must not change their
        rate-limit key when no proxy is trusted."""
        monkeypatch.setattr(
            limiter_module, "get_settings", lambda: Settings(TRUSTED_PROXY_IPS="")
        )
        attacker_ip = "198.51.100.1"
        first = limiter_module._get_real_client_ip(
            FakeRequest(attacker_ip, {"X-Forwarded-For": "1.1.1.1"})
        )
        second = limiter_module._get_real_client_ip(
            FakeRequest(attacker_ip, {"X-Forwarded-For": "2.2.2.2"})
        )
        assert first == second == attacker_ip
