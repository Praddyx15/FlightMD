"""
Webhook SSRF guards. DNS and the HTTP connection are faked, so nothing here
touches the network.
"""

import os
import socket
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import api.webhook_notifier as wn
from api.airframe_store import AlertRule
from api.config import get_settings
from api.webhook_notifier import UnsafeWebhookURLError, send_alert_webhook, validate_webhook_url

DNS = {
    "hooks.example.com": ["93.184.216.34"],
    "internal.example.com": ["10.0.0.5"],
    "metadata.example.com": ["169.254.169.254"],
    "mapped.example.com": ["::ffff:127.0.0.1"],
    "cgnat.example.com": ["100.64.0.1"],
    "mixed.example.com": ["93.184.216.34", "192.168.1.10"],
}


def fake_getaddrinfo(host, port, *args, **kwargs):
    try:
        addrs = DNS[host]
    except KeyError:
        # IP literals resolve to themselves, like the real thing
        addrs = [host]
    out = []
    for a in addrs:
        family = socket.AF_INET6 if ":" in a else socket.AF_INET
        out.append((family, socket.SOCK_STREAM, 6, "", (a, port)))
    return out


@pytest.fixture(autouse=True)
def fake_dns(monkeypatch):
    monkeypatch.setattr(wn.socket, "getaddrinfo", fake_getaddrinfo)
    monkeypatch.setattr(get_settings(), "allow_http_webhooks", False)


class FakeResponse:
    def __init__(self, status, headers=None):
        self.status = status
        self.headers = headers or {}


class FakeConnection:
    def __init__(self, status, headers=None):
        self.requests = []
        self._resp = FakeResponse(status, headers)

    def request(self, method, target, body=None, headers=None):
        self.requests.append((method, target))

    def getresponse(self):
        return self._resp

    def close(self):
        pass


def triggered():
    return [{"rule": AlertRule(metric="overall_score", comparison="lt", threshold=70.0), "value": 55.0}]


class TestValidateWebhookURL:
    def test_rejects_http_scheme(self):
        with pytest.raises(UnsafeWebhookURLError, match="https"):
            validate_webhook_url("http://hooks.example.com/webhook")

    def test_http_allowed_only_with_the_flag(self, monkeypatch):
        monkeypatch.setattr(get_settings(), "allow_http_webhooks", True)
        assert validate_webhook_url("http://hooks.example.com/webhook") == ["93.184.216.34"]

    @pytest.mark.parametrize("url", [
        "https://127.0.0.1/webhook",
        "https://10.0.0.5/webhook",
        "https://169.254.169.254/latest/meta-data",
        "https://[::1]/webhook",
    ])
    def test_rejects_non_public_ip_literals(self, url):
        with pytest.raises(UnsafeWebhookURLError):
            validate_webhook_url(url)

    @pytest.mark.parametrize("host", [
        "internal.example.com", "metadata.example.com", "mapped.example.com",
        "cgnat.example.com", "mixed.example.com",
    ])
    def test_rejects_hostnames_resolving_to_non_public_addresses(self, host):
        with pytest.raises(UnsafeWebhookURLError, match="non-public"):
            validate_webhook_url(f"https://{host}/webhook")

    def test_rejects_missing_hostname(self):
        with pytest.raises(UnsafeWebhookURLError):
            validate_webhook_url("https:///webhook")

    def test_rejects_header_injection(self):
        with pytest.raises(UnsafeWebhookURLError):
            validate_webhook_url("https://hooks.example.com/a\r\nHost: evil")

    def test_accepts_public_hostname(self):
        assert validate_webhook_url("https://hooks.example.com/api/webhooks/123/abc") == ["93.184.216.34"]


class TestSendAlertWebhook:
    def test_unsafe_url_returns_false_without_connecting(self, monkeypatch):
        def no_connect(*a, **kw):
            raise AssertionError("should not connect")
        monkeypatch.setattr(wn, "_open_connection", no_connect)
        assert send_alert_webhook("https://internal.example.com/webhook", "Quad-1", "r1", triggered()) is False

    def test_success_pins_the_validated_address(self, monkeypatch):
        seen = {}
        conn = FakeConnection(204)

        def open_connection(scheme, host, port, ip, timeout):
            seen.update(scheme=scheme, host=host, ip=ip)
            return conn
        monkeypatch.setattr(wn, "_open_connection", open_connection)

        assert send_alert_webhook("https://hooks.example.com/hook?x=1", "Quad-1", "r1", triggered()) is True
        assert seen == {"scheme": "https", "host": "hooks.example.com", "ip": "93.184.216.34"}
        assert conn.requests == [("POST", "/hook?x=1")]

    def test_redirect_is_not_followed(self, monkeypatch):
        conn = FakeConnection(302, {"Location": "http://169.254.169.254/latest/meta-data"})
        opened = []
        monkeypatch.setattr(wn, "_open_connection", lambda *a: opened.append(a) or conn)

        assert send_alert_webhook("https://hooks.example.com/hook", "Quad-1", "r1", triggered()) is False
        assert len(opened) == 1
        assert len(conn.requests) == 1

    def test_connection_error_returns_false(self, monkeypatch):
        class Broken(FakeConnection):
            def request(self, *a, **kw):
                raise ConnectionRefusedError("nope")
        monkeypatch.setattr(wn, "_open_connection", lambda *a: Broken(200))
        assert send_alert_webhook("https://hooks.example.com/hook", "Quad-1", "r1", triggered()) is False

    def test_pinned_connection_dials_the_ip_not_the_name(self, monkeypatch):
        dialled = []

        def fake_create_connection(addr, *a, **kw):
            dialled.append(addr)
            raise OSError("stop here")
        monkeypatch.setattr(wn.socket, "create_connection", fake_create_connection)
        conn = wn._open_connection("https", "hooks.example.com", None, "93.184.216.34", 1.0)
        with pytest.raises(OSError):
            conn.connect()
        assert dialled == [("93.184.216.34", 443)]
