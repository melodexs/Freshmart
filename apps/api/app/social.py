"""Store social media links. Only real https links on the named network are accepted, so the footer can
never be made to carry a javascript: or look-alike link."""

from __future__ import annotations

from urllib.parse import urlparse

NETWORKS = {
    "facebook": ("Facebook", ("facebook.com", "fb.com", "fb.me")),
    "instagram": ("Instagram", ("instagram.com",)),
    "x": ("X (Twitter)", ("x.com", "twitter.com")),
    "tiktok": ("TikTok", ("tiktok.com",)),
    "youtube": ("YouTube", ("youtube.com", "youtu.be")),
}
MAX_URL = 200


def clean_social(network: str, value) -> str | None:
    """The tidy https URL if it belongs to the network, "" for blank, None if it is not acceptable."""
    if value is None or (isinstance(value, str) and not value.strip()):
        return ""
    if network not in NETWORKS or not isinstance(value, str):
        return None
    raw = value.strip()
    if len(raw) > MAX_URL or any(c in raw for c in " <>\"'\\\r\n\t"):
        return None
    if "://" not in raw:
        if (
            ":" in raw.split("/", 1)[0]
        ):  # "javascript:..." / "data:..." / host:port: never a bare web address
            return None
        raw = "https://" + raw
    try:
        u = urlparse(raw)
        host = (u.hostname or "").lower()
        port = u.port
    except ValueError:  # a malformed port or bracketed host: refuse it, never crash
        return None
    if u.scheme != "https" or u.username or u.password or port not in (None, 443):
        return None
    domains = NETWORKS[network][1]
    if not any(host == d or host.endswith("." + d) for d in domains):
        return None
    return raw


def public_links(stored) -> list[dict]:
    """Links for the footer: only those that are set and still valid."""
    out = []
    if not isinstance(stored, dict):
        return out
    for key, (label, _) in NETWORKS.items():
        url = clean_social(key, stored.get(key))
        if url:
            out.append({"key": key, "label": label, "url": url})
    return out
