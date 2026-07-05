"""
Tests for webhook URL SSRF validation. send_alert_webhook itself makes a
real network call, so it isn't exercised here beyond confirming it refuses
unsafe URLs before ever opening a connection.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from api.webhook_notifier import UnsafeWebhookURLError, validate_webhook_url, send_alert_webhook


class TestValidateWebhookURL:
    def test_rejects_http_scheme(self):
        with pytest.raises(UnsafeWebhookURLError, match="https"):
            validate_webhook_url("http://example.com/webhook")

    def test_rejects_localhost(self):
        with pytest.raises(UnsafeWebhookURLError):
            validate_webhook_url("https://localhost/webhook")

    def test_rejects_loopback_ip(self):
        with pytest.raises(UnsafeWebhookURLError):
            validate_webhook_url("https://127.0.0.1/webhook")

    def test_rejects_private_ip_range(self):
        with pytest.raises(UnsafeWebhookURLError):
            validate_webhook_url("https://10.0.0.5/webhook")

    def test_rejects_link_local_metadata_address(self):
        with pytest.raises(UnsafeWebhookURLError):
            validate_webhook_url("https://169.254.169.254/latest/meta-data")

    def test_rejects_missing_hostname(self):
        with pytest.raises(UnsafeWebhookURLError):
            validate_webhook_url("https:///webhook")

    def test_accepts_public_hostname(self):
        # discord.com resolves to a public IP — should pass validation
        # (doesn't send a request, just checks it doesn't raise).
        validate_webhook_url("https://discord.com/api/webhooks/123/abc")


class TestSendAlertWebhookRefusesUnsafeURLWithoutNetworkCall:
    def test_unsafe_url_returns_false_without_raising(self):
        result = send_alert_webhook("http://127.0.0.1/webhook", "Quad-1", "r1", [])
        assert result is False
