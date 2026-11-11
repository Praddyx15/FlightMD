"""Client IP for rate limiting, the shared limiter, and airframe token checks."""

import ipaddress
from functools import lru_cache
from typing import Optional

from fastapi import HTTPException, Request
from slowapi import Limiter

from api import airframe_store as afs
from api.config import get_settings

AIRFRAME_TOKEN_HEADER = "X-Airframe-Token"


@lru_cache(maxsize=8)
def trusted_networks(spec: str) -> tuple:
    nets = []
    for part in spec.split(","):
        part = part.strip()
        if part:
            nets.append(ipaddress.ip_network(part, strict=False))
    return tuple(nets)


def _trusted(addr: str, nets: tuple) -> bool:
    try:
        ip = ipaddress.ip_address(addr)
    except ValueError:
        return False
    return any(ip in n for n in nets)


def client_ip(request: Request) -> str:
    """The address to rate-limit on.

    X-Forwarded-For is only read when the direct peer is a trusted proxy, and
    then from the right: the first hop that isn't one of our proxies is the
    client. Anything left of it was written by the client and can be faked.
    """
    peer = request.client.host if request.client else "unknown"
    nets = trusted_networks(get_settings().trusted_proxies)
    if not nets or not _trusted(peer, nets):
        return peer

    hops = []
    for value in request.headers.getlist("x-forwarded-for"):
        hops.extend(h.strip() for h in value.split(",") if h.strip())
    for hop in reversed(hops):
        if not _trusted(hop, nets):
            return hop
    return hops[0] if hops else peer


limiter = Limiter(key_func=client_ip)


def token_error(e: "afs.TokenError") -> HTTPException:
    if e.reason == "invalid":
        return HTTPException(status_code=403, detail="Wrong airframe token.")
    if e.reason == "missing":
        return HTTPException(status_code=401, detail=f"This airframe needs its {AIRFRAME_TOKEN_HEADER} header.")
    return HTTPException(
        status_code=401,
        detail="Airframe not claimed yet. Saving its config, logging maintenance or "
               "tagging an upload with it claims it.",
    )


def check_airframe_token(label: str, token: Optional[str], claim: bool = False) -> Optional[str]:
    """Raise 401/403 unless `token` opens this airframe.

    claim=True lets an unclaimed airframe be claimed by this request; the new
    token is returned and must go back to the caller in the response.
    """
    try:
        return afs.airframe_store.authorise(label, token, claim=claim)
    except afs.TokenError as e:
        raise token_error(e)


def precheck_airframe_token(label: str, token: Optional[str]) -> bool:
    """For writes: True if the airframe is unclaimed and this request may claim it.

    A claimed airframe with a missing or wrong token raises 401/403 here,
    before the caller does anything expensive. The claim itself happens later
    via check_airframe_token(claim=True), once the request is known to be good,
    so a rejected request never burns the one-time token.
    """
    try:
        afs.airframe_store.authorise(label, token)
    except afs.TokenError as e:
        if e.reason != "unclaimed":
            raise token_error(e)
        return True
    return False
