"""
Indeed (DE) scraper — Playwright/headless-Chromium edition.

Indeed fronts its search results AND job-detail pages with Cloudflare bot
management. Plain `requests` sessions get a "Security Check" challenge page
(or an outright 403) on literally the first request, no matter what cookies
are attached — Cloudflare re-evaluates the TLS/JA3 fingerprint and JS
execution on every request, and `requests` simply can't fake a real browser
there.

A real, headless Chromium driven via Playwright DOES get past the challenge
on the *search-results* page (`/jobs?q=...`) — it renders the real results
after ~5-8s, no manual interaction needed. Job *detail* pages are also
fetched using the saved cookies from `scraper/cookies/.indeed.com.json`,
which lets the authenticated browser load the description. If no cookie file
is present the description falls back to None and title-only filtering
applies.

This is, overall, much slower than the old requests-based scrapers — a
headless browser has to actually load and render each results page (several
seconds per page) — but it's the only way to get real Indeed results at all
right now.
"""

import json
import math
import re
import time
import random
from datetime import datetime, timedelta
from pathlib import Path
from playwright.sync_api import sync_playwright
from .base import polite_delay, COOKIE_DIR
from .proxies import get_proxy_url, to_playwright_proxy

SEARCH_URL = "https://de.indeed.com/jobs"
JOB_URL = "https://de.indeed.com/viewjob?jk={job_id}"

SOURCE = "indeed"
PAGE_SIZE = 10
# Cloudflare lets the *first* search-results request through pretty reliably
# (resolves in ~5-8s) but a second request — for page 2 — within the same
# session reliably hits a challenge that never resolves (tested 45s+ wait).
# Rather than raising/erroring on every run, we just take the one page of
# results we can reliably get. ~15-16 fresh listings per keyword is still a
# meaningful chunk, and it's far better than a hard failure every time.
MAX_PAGES = 1

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36 Edg/124.0.0.0"
)

CARD_SELECTOR = "div.job_seen_beacon"
CHALLENGE_TITLES = ("Security Check", "Nur einen Moment", "Just a moment", "Blocked")
DESCRIPTION_SELECTOR = "#jobDescriptionText"

_AGE_RE = re.compile(r"vor\s+(\d+)\s*(Tag|Tagen|Stunde|Stunden)", re.IGNORECASE)


def _parse_age(text, now):
    """Indeed shows relative ages like 'vor 2 Tagen', 'vor 5 Stunden',
    'Heute', 'Gerade veröffentlicht'. Minute-precision isn't offered, so
    this is approximate — good enough for an hours-based lookback cutoff."""
    if not text:
        return None
    low = text.strip().lower()
    if "gerade" in low or low == "heute":
        return now
    m = _AGE_RE.search(text)
    if not m:
        return None
    amount = int(m.group(1))
    unit = m.group(2).lower()
    if unit.startswith("stunde"):
        return now - timedelta(hours=amount)
    if unit.startswith("tag"):
        return now - timedelta(days=amount)
    return None


def _wait_past_challenge(page, max_wait_ms=45000, step_ms=3000):
    """Indeed's search-results page sits behind a Cloudflare challenge for a
    few seconds before resolving to the real page. Poll the title until it's
    no longer a challenge page (or we give up)."""
    waited = 0
    while waited < max_wait_ms:
        title = page.title()
        if not any(c in title for c in CHALLENGE_TITLES):
            return True
        page.wait_for_timeout(step_ms)
        waited += step_ms
    return False


def _load_cookies_into_context(context, profile="edge"):
    """Pull Indeed cookies directly from the browser (Edge/Chrome) via
    browser_cookie3 — no manual export needed. Falls back to a cookie file in
    scraper/cookies/ if the live read fails (e.g. App-Bound Encryption on
    newer Chrome/Edge builds). Returns True if any cookies were loaded."""
    import browser_cookie3

    raw_cookies = None

    # 1. Try live browser cookies first.
    try:
        if profile == "edge":
            raw_cookies = list(browser_cookie3.edge(domain_name=".indeed.com"))
        else:
            raw_cookies = list(browser_cookie3.chrome(domain_name=".indeed.com"))
    except Exception:
        pass

    # 2. Fall back to manually-exported JSON file.
    if not raw_cookies:
        for name in (".indeed.com.json", "indeed.com.json"):
            cookie_path = COOKIE_DIR / name
            if cookie_path.exists():
                try:
                    raw_json = json.loads(cookie_path.read_text(encoding="utf-8"))
                    pw_cookies = []
                    for c in raw_json:
                        entry = {
                            "name": c.get("name", ""),
                            "value": c.get("value", ""),
                            "domain": c.get("domain", ".indeed.com"),
                            "path": c.get("path", "/"),
                        }
                        if c.get("expirationDate"):
                            entry["expires"] = int(c["expirationDate"])
                        if c.get("secure") is not None:
                            entry["secure"] = bool(c["secure"])
                        pw_cookies.append(entry)
                    context.add_cookies(pw_cookies)
                    return True
                except Exception:
                    pass
        return False

    # Convert http.cookiejar cookies to Playwright format.
    pw_cookies = []
    for c in raw_cookies:
        try:
            entry = {
                "name": c.name,
                "value": c.value,
                "domain": c.domain if c.domain.startswith(".") else f".{c.domain}",
                "path": c.path or "/",
            }
            if c.expires:
                entry["expires"] = int(c.expires)
            if c.secure:
                entry["secure"] = True
            pw_cookies.append(entry)
        except Exception:
            continue

    if pw_cookies:
        context.add_cookies(pw_cookies)
        return True
    return False


def _fetch_description(context, job_url):
    """Open the job detail page in a new tab and extract the description text.
    Returns None if the page is blocked or the selector isn't found."""
    detail_page = None
    try:
        detail_page = context.new_page()
        detail_page.goto(job_url, timeout=30000)
        detail_page.wait_for_timeout(random.randint(2000, 4000))
        # Detail pages sit behind the same Cloudflare challenge as search
        # results, but it can take longer to clear here — give it the same
        # poll-and-wait treatment instead of giving up after one fixed delay.
        if any(c in detail_page.title() for c in CHALLENGE_TITLES):
            _wait_past_challenge(detail_page, max_wait_ms=30000, step_ms=5000)
        if any(c in detail_page.title() for c in CHALLENGE_TITLES):
            return None
        el = detail_page.query_selector(DESCRIPTION_SELECTOR)
        if el:
            return el.inner_text().strip() or None
        return None
    except Exception:
        return None
    finally:
        if detail_page:
            try:
                detail_page.close()
            except Exception:
                pass


def scrape(keyword, lookback_hours, profile="edge", progress_cb=None, title_filter=None, job_known=None, on_seen=None):
    """
    Returns list of job dicts: {title, company, location, url, description, source}

    Descriptions are fetched from the job detail page using saved cookies.
    If no cookie file is present or the page is Cloudflare-blocked, description
    falls back to None (title-based filtering still applies).
    """
    fromage = max(1, math.ceil(lookback_hours / 24))
    now = datetime.now()
    cutoff = now - timedelta(hours=lookback_hours)

    jobs = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        try:
            proxy = to_playwright_proxy(get_proxy_url())
            context = browser.new_context(user_agent=USER_AGENT, locale="de-DE", proxy=proxy)
            has_cookies = _load_cookies_into_context(context, profile)
            page = context.new_page()

            for page_num in range(MAX_PAGES):
                start = page_num * PAGE_SIZE
                url = f"{SEARCH_URL}?q={keyword}&l=&fromage={fromage}&start={start}"

                try:
                    page.goto(url, timeout=60000)
                except Exception as e:
                    raise RuntimeError(f"Indeed page load failed: {e}")

                page.wait_for_timeout(5000)
                if not _wait_past_challenge(page):
                    raise RuntimeError("Indeed blocked the request — try again later")

                cards = page.query_selector_all(CARD_SELECTOR)
                if not cards:
                    break

                reached_cutoff = False
                new_on_page = 0

                for card in cards:
                    try:
                        title_link = card.query_selector("h3.jobTitle a[data-jk]")
                        if not title_link:
                            continue
                        job_id = title_link.get_attribute("data-jk")
                        if not job_id:
                            continue

                        title_span = title_link.query_selector("span[title]")
                        title = (
                            title_span.get_attribute("title").strip()
                            if title_span and title_span.get_attribute("title")
                            else title_link.inner_text().strip()
                        )

                        company_el = card.query_selector("[data-testid='company-name']")
                        location_el = card.query_selector("[data-testid='text-location']")
                        date_el = card.query_selector("[data-testid='myJobsStateDate'], .date, [class*='date']")

                        company = company_el.inner_text().strip() if company_el else None
                        location = location_el.inner_text().strip() if location_el else ""
                        if not title or not company:
                            continue

                        posted_dt = _parse_age(date_el.inner_text() if date_el else None, now)
                        if posted_dt and posted_dt < cutoff:
                            reached_cutoff = True
                            continue

                        # check job_known BEFORE on_seen — on_seen stamps seen_jobs
                        # with seen_at = now, which would make is_job_recently_seen
                        # immediately return True for this very job if checked after
                        already_known = job_known and job_known(title, company, location)

                        if on_seen:
                            on_seen(title, company, location)

                        job_url = JOB_URL.format(job_id=job_id)

                        # Skip description fetch for title-filtered or already-known jobs.
                        if title_filter and not title_filter(title):
                            continue
                        if already_known:
                            continue

                        description = None
                        if has_cookies:
                            description = _fetch_description(context, job_url)

                        job = {
                            "title": title,
                            "company": company,
                            "location": location,
                            "url": job_url,
                            "description": description,
                            "source": SOURCE,
                        }
                        jobs.append(job)

                        if progress_cb:
                            try:
                                progress_cb(job, len(jobs))
                            except Exception:
                                # ScanStopped subclasses BaseException (not
                                # Exception), so it passes through untouched —
                                # same pattern as the other scrapers.
                                pass

                        new_on_page += 1
                    except (AttributeError, KeyError):
                        continue

                if reached_cutoff or new_on_page == 0 or len(cards) < PAGE_SIZE:
                    break

                # Cloudflare seems to tighten up on subsequent requests within
                # the same session — give it noticeably more breathing room
                # between result pages than the plain `polite_delay()` other
                # scrapers use between their (cheap, non-challenged) requests.
                page.wait_for_timeout(8000)
                polite_delay()

            return jobs
        finally:
            browser.close()
