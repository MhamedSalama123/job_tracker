"""Proxy support for Playwright-based scrapers (StepStone, Indeed).

Reads `[proxies]` from config.toml — a single rotating-proxy endpoint
(e.g. Webshare's "Rotating Proxy Endpoint") that hands out a different
exit IP per request automatically, so no client-side rotation is needed.
"""

from pathlib import Path
from urllib.parse import urlparse
import toml

CONFIG_PATH = Path(__file__).parent.parent / "config.toml"


def get_proxy_url():
    """Return the configured proxy URL, or None if proxies are disabled
    or not configured."""
    try:
        config = toml.load(CONFIG_PATH)
    except Exception:
        return None
    proxies_cfg = config.get("proxies", {})
    if not proxies_cfg.get("enabled"):
        return None
    return proxies_cfg.get("url") or None


def to_playwright_proxy(proxy_url):
    """Convert "http://user:pass@host:port" into Playwright's proxy dict
    (Playwright wants the server URL and credentials as separate fields)."""
    if not proxy_url:
        return None
    p = urlparse(proxy_url)
    proxy = {"server": f"{p.scheme}://{p.hostname}:{p.port}"}
    if p.username:
        proxy["username"] = p.username
    if p.password:
        proxy["password"] = p.password
    return proxy
