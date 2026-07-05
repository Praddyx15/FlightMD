"""
Best-effort webhook notifier for airframe alert rules — fires a POST to an
operator-configured URL (Slack/Discord-compatible payload shape) when a
tagged flight breaches one of that airframe's alert rules.

Since any operator of a shared instance can set an airframe's webhook_url
to an arbitrary URL with no authentication, this validates the target to
reduce SSRF risk before ever making a request: https-only, and the
resolved IP must not be a private/loopback/link-local/reserved address.
This isn't perfect (DNS can still change between check and request on a
sufficiently adversarial setup), but it closes the easy cases — pointing
the webhook at localhost, a RFC1918 address, or a link-local metadata
endpoint.
"""

import ipaddress
import json
import logging
import socket
import urllib.request
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

REQUEST_TIMEOUT_S = 5.0


class UnsafeWebhookURLError(ValueError):
    pass


def validate_webhook_url(url: str) -> None:
    """Raises UnsafeWebhookURLError if the URL isn't safe to POST to."""
    parsed = urlparse(url)
    if parsed.scheme != "https":
        raise UnsafeWebhookURLError("Webhook URL must use https://")
    if not parsed.hostname:
        raise UnsafeWebhookURLError("Webhook URL must include a hostname")

    try:
        addr_infos = socket.getaddrinfo(parsed.hostname, None)
    except socket.gaierror as e:
        raise UnsafeWebhookURLError(f"Could not resolve webhook hostname: {e}") from e

    for family, _, _, _, sockaddr in addr_infos:
        ip = ipaddress.ip_address(sockaddr[0])
        if (
            ip.is_private
            or ip.is_loopback
            or ip.is_link_local
            or ip.is_reserved
            or ip.is_multicast
            or ip.is_unspecified
        ):
            raise UnsafeWebhookURLError(
                f"Webhook hostname resolves to a non-public address ({ip}) — refusing to send."
            )


def send_alert_webhook(webhook_url: str, airframe_label: str, report_id: str, triggered: list[dict]) -> bool:
    """
    Best-effort: validates the URL, posts a Slack/Discord-compatible
    payload, and swallows any error (never raises) — a broken webhook
    must never break analysis. Returns True if the request was sent
    successfully.
    """
    try:
        validate_webhook_url(webhook_url)
    except UnsafeWebhookURLError as e:
        logger.warning(f"Refusing to send alert webhook for airframe {airframe_label!r}: {e}")
        return False

    lines = [f"⚠️ FlightMD alert — *{airframe_label}* (report `{report_id}`)"]
    for item in triggered:
        rule = item["rule"]
        label = rule.label or rule.metric
        lines.append(f"• {label}: {item['value']:.3g} ({'<' if rule.comparison == 'lt' else '>'} {rule.threshold:g})")
    text = "\n".join(lines)

    payload = json.dumps({"content": text, "text": text}).encode("utf-8")
    req = urllib.request.Request(
        webhook_url,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT_S) as response:
            return 200 <= response.status < 300
    except Exception as e:
        logger.warning(f"Alert webhook delivery failed for airframe {airframe_label!r}: {e}")
        return False
