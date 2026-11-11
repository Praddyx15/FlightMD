"""
Alert webhooks (Slack/Discord-shaped JSON) for airframe alert rules.

The target URL is user-supplied, so before every send we resolve the host,
refuse anything that isn't a public address, connect to exactly the address
we checked (no second DNS lookup to rebind), and never follow redirects.
"""

import http.client
import ipaddress
import json
import logging
import socket
from urllib.parse import urlparse

from api.config import get_settings

logger = logging.getLogger(__name__)

REQUEST_TIMEOUT_S = 5.0
MAX_URL_LEN = 2048


class UnsafeWebhookURLError(ValueError):
    pass


def validate_webhook_url(url: str) -> list[str]:
    """Return the host's resolved addresses, or raise UnsafeWebhookURLError."""
    if len(url) > MAX_URL_LEN or any(c.isspace() or ord(c) < 32 for c in url):
        raise UnsafeWebhookURLError("Webhook URL is too long or contains whitespace")

    parsed = urlparse(url)
    schemes = ("https", "http") if get_settings().allow_http_webhooks else ("https",)
    if parsed.scheme not in schemes:
        raise UnsafeWebhookURLError("Webhook URL must use https://")
    if not parsed.hostname:
        raise UnsafeWebhookURLError("Webhook URL must include a hostname")
    try:
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
    except ValueError:
        raise UnsafeWebhookURLError("Webhook URL has an invalid port")

    try:
        infos = socket.getaddrinfo(parsed.hostname, port, proto=socket.IPPROTO_TCP)
    except socket.gaierror as e:
        raise UnsafeWebhookURLError(f"Could not resolve webhook hostname: {e}") from e

    addrs = []
    for *_, sockaddr in infos:
        ip = ipaddress.ip_address(sockaddr[0].split("%")[0])
        if ip.version == 6 and ip.ipv4_mapped:
            ip = ip.ipv4_mapped
        # is_global rules out private, loopback, link-local (cloud metadata),
        # CGNAT and reserved ranges in one go
        if not ip.is_global or ip.is_multicast:
            raise UnsafeWebhookURLError(
                f"Webhook hostname resolves to a non-public address ({ip}), refusing to send."
            )
        addrs.append(str(ip))
    if not addrs:
        raise UnsafeWebhookURLError("Webhook hostname did not resolve")
    return addrs


def _open_connection(scheme: str, host: str, port, ip: str, timeout: float):
    cls = http.client.HTTPSConnection if scheme == "https" else http.client.HTTPConnection
    conn = cls(host, port, timeout=timeout)
    # TLS still checks the cert against `host`; only the socket target is pinned
    conn._create_connection = lambda addr, *a, **kw: socket.create_connection((ip, addr[1]), *a, **kw)
    return conn


def send_alert_webhook(webhook_url: str, airframe_label: str, report_id: str, triggered: list[dict]) -> bool:
    """POST the alert. Never raises; True only on a 2xx."""
    try:
        addrs = validate_webhook_url(webhook_url)
    except UnsafeWebhookURLError as e:
        logger.warning(f"refusing alert webhook for report {report_id}: {e}")
        return False

    lines = [f"⚠️ FlightMD alert — *{airframe_label}* (report `{report_id}`)"]
    for item in triggered:
        rule = item["rule"]
        label = rule.label or rule.metric
        lines.append(f"• {label}: {item['value']:.3g} ({'<' if rule.comparison == 'lt' else '>'} {rule.threshold:g})")
    text = "\n".join(lines)
    payload = json.dumps({"content": text, "text": text}).encode("utf-8")

    parsed = urlparse(webhook_url)
    target = parsed.path or "/"
    if parsed.query:
        target += "?" + parsed.query

    conn = _open_connection(parsed.scheme, parsed.hostname, parsed.port, addrs[0], REQUEST_TIMEOUT_S)
    try:
        conn.request("POST", target, body=payload, headers={
            "Content-Type": "application/json",
            "User-Agent": "FlightMD-webhook",
        })
        resp = conn.getresponse()
        # a 3xx is not followed, it just counts as a failed delivery
        return 200 <= resp.status < 300
    except (OSError, ValueError, http.client.HTTPException) as e:
        logger.warning(f"alert webhook for report {report_id} failed: {e}")
        return False
    finally:
        conn.close()
