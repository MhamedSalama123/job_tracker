import time
import random
import json
from pathlib import Path
import browser_cookie3
import requests
from bs4 import BeautifulSoup

# Manual cookie export directory (fallback for sites whose cookies can no
# longer be read from the browser's local storage — e.g. Edge/Chrome 127+
# wrap them in "App-Bound Encryption", which browser_cookie3 cannot decrypt
# even with admin rights). Export cookies with a browser extension like
# "Cookie-Editor" (JSON export) and save them here as "<domain>.json", e.g.
# scraper/cookies/.indeed.com.json — a JSON array of {name, value, domain, ...}.
COOKIE_DIR = Path(__file__).parent / "cookies"


def _cookie_file_for(domain):
    safe = domain.lstrip(".")
    for candidate in (domain, safe):
        for ext in (".json", ".txt"):
            path = COOKIE_DIR / f"{candidate}{ext}"
            if path.exists():
                return path
    return None


def load_cookies_from_file(session, domain):
    """
    Load cookies from a manually-exported file in COOKIE_DIR, if one exists.
    Supports:
      - JSON array exports (e.g. from the "Cookie-Editor" browser extension):
        [{"name": "...", "value": "...", "domain": "...", "path": "/"}, ...]
      - Netscape "cookies.txt" format (tab-separated, as exported by most
        cookie-export extensions in "Netscape" mode).
    Returns True if a file was found and loaded, False otherwise.
    """
    path = _cookie_file_for(domain)
    if not path:
        return False

    try:
        if path.suffix == ".json":
            data = json.loads(path.read_text(encoding="utf-8"))
            for c in data:
                session.cookies.set(
                    c.get("name"), c.get("value"),
                    domain=c.get("domain", domain),
                    path=c.get("path", "/"),
                )
        else:  # Netscape cookies.txt
            for line in path.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                parts = line.split("\t")
                if len(parts) < 7:
                    continue
                cdomain, _flag, cpath, _secure, _expiry, name, value = parts[:7]
                session.cookies.set(name, value, domain=cdomain, path=cpath)
        return True
    except Exception as e:
        raise RuntimeError(f"Failed to load cookie file {path.name}: {e}")


def get_session(profile="edge"):
    session = requests.Session()
    session.headers.update({
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36 Edg/124.0.0.0"
        ),
        "Accept-Language": "de-DE,de;q=0.9,en;q=0.8",
    })
    return session


def load_cookies(session, domain, profile="edge"):
    # Prefer a manually-exported cookie file — modern Edge/Chrome (127+) wrap
    # cookies in "App-Bound Encryption", which browser_cookie3 cannot decrypt
    # (raises "Unable to get key for cookie decryption" / admin errors) no
    # matter the privilege level. A manual export sidesteps that entirely.
    try:
        if load_cookies_from_file(session, domain):
            return
    except RuntimeError:
        raise
    except Exception:
        pass

    try:
        if profile == "edge":
            cookies = browser_cookie3.edge(domain_name=domain)
        else:
            cookies = browser_cookie3.chrome(domain_name=domain)
        session.cookies.update(cookies)
    except Exception as e:
        raise RuntimeError(
            f"Failed to load cookies for {domain}: {e}. "
            f"Modern Edge/Chrome encrypt cookies in a way this tool can't read automatically — "
            f"export them manually instead: install the 'Cookie-Editor' browser extension, "
            f"open {domain.lstrip('.')}, export cookies as JSON, and save the file as "
            f"scraper/cookies/{domain}.json"
        )


def fetch_description(session, url, description_selector, retries=2):
    """
    Fetch job detail page and extract description text.
    Returns None on failure — job still gets stored.

    Occasionally a single request returns a page where the description
    selector doesn't match (transient blocking/rate-limiting under request
    bursts) even though the same URL succeeds moments later — so retry a
    couple of times with a short backoff before giving up.
    """
    for attempt in range(retries + 1):
        try:
            time.sleep(random.uniform(1.0, 2.5))
            resp = session.get(url, timeout=10)
            resp.raise_for_status()
            resp.encoding = resp.apparent_encoding or "utf-8"
            soup = BeautifulSoup(resp.text, "html.parser")
            el = soup.select_one(description_selector)
            if el:
                return el.get_text(separator="\n", strip=True)
        except Exception:
            pass
        if attempt < retries:
            time.sleep(random.uniform(1.5, 3.0))
    return None


def polite_delay():
    time.sleep(random.uniform(1.0, 3.0))
