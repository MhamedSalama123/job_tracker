"""
StepStone (DE) scraper.

Uses StepStone's server-rendered job search results page
(stepstone.de/jobs/{keyword}), no API/auth needed for the search itself.
Each result card carries an exact ISO-8601 "posted at" timestamp
(<time datetime="...">), so — unlike Indeed/LinkedIn's day-bucket filters —
we can filter precisely by `lookback_hours` client-side. The `ag=age_N`
query param is used only as a coarse server-side pre-filter (StepStone
offers day-granularity buckets: 1/3/7/14/30 days); we pick the smallest
bucket that comfortably covers the requested lookback window.
"""

import random
import re
from datetime import datetime, timedelta
import requests
from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright
from .base import polite_delay, get_session, load_cookies
from .proxies import get_proxy_url, to_playwright_proxy

BASE_URL = "https://www.stepstone.de"
SEARCH_URL = "https://www.stepstone.de/jobs/{keyword}"
DESCRIPTION_SELECTOR = "[data-at='job-ad-content']"
# StepStone tar-pits requests.* fetches of job *detail* pages — they hang
# until they time out (confirmed: 45s+ with no response). A headless browser
# (Playwright) gets through fine, so detail pages are fetched that way. The
# search-results page also embeds a sizeable teaser/snippet of the ad text
# right on each card (the bit shown before the "..." / "mehr anzeigen" expand
# button) — used as a fallback if the full-page fetch fails for some reason.
SNIPPET_SELECTOR = "span[data-genesis-element='TEXT']:has([data-at='text-snippet-expand-button'])"

SOURCE = "stepstone"
PAGE_SIZE = 25  # StepStone's results-per-page; used only as a "last page" heuristic
MAX_PAGES = 5

AGE_BUCKETS = [1, 3, 7, 14, 30]

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36 Edg/124.0.0.0"
    ),
    "Accept-Language": "de-DE,de;q=0.9,en;q=0.8",
}


_RELATIVE_RE = re.compile(
    r"vor\s+(\d+)\s*(Minute|Minuten|Stunde|Stunden|Tag|Tagen)", re.IGNORECASE
)


def _parse_relative_age(text, now):
    """
    Parse StepStone's relative timestamps (server-rendered, no ISO datetime
    attr available): "vor X Minuten/Stunden/Tagen", "Heute", "Gestern".
    Returns an absolute datetime (approximate — minute/hour precision) or
    None if unparseable (in which case the job is kept, not filtered out).
    """
    if not text:
        return None
    text = text.strip()
    low = text.lower()
    if low == "heute":
        return now
    if low == "gestern":
        return now - timedelta(days=1)

    m = _RELATIVE_RE.search(text)
    if not m:
        return None
    amount = int(m.group(1))
    unit = m.group(2).lower()
    if unit.startswith("minute"):
        return now - timedelta(minutes=amount)
    if unit.startswith("stunde"):
        return now - timedelta(hours=amount)
    if unit.startswith("tag"):
        return now - timedelta(days=amount)
    return None


def _age_bucket(lookback_hours):
    days_needed = lookback_hours / 24
    for bucket in AGE_BUCKETS:
        if bucket >= days_needed:
            return bucket
    return AGE_BUCKETS[-1]


def _fetch_full_description(context, url):
    """Fetch the full job description from the detail page using a headless
    browser (plain `requests` tar-pits StepStone detail pages — see above).
    Returns None on failure so the caller can fall back to the card snippet."""
    page = None
    try:
        page = context.new_page()
        page.goto(url, timeout=30000)
        page.wait_for_timeout(random.randint(1500, 3000))
        el = page.query_selector(DESCRIPTION_SELECTOR)
        if el:
            return el.inner_text().strip() or None
        return None
    except Exception:
        return None
    finally:
        if page:
            try:
                page.close()
            except Exception:
                pass


def scrape(keyword, lookback_hours, profile="edge", progress_cb=None, title_filter=None, job_known=None, on_seen=None):
    """
    Returns list of job dicts: {title, company, location, url, description, source}

    `title_filter` and `job_known`, when given, are used to skip the slow
    per-job description fetch (a headless-browser page load) for jobs that
    would be filtered or are already known — falling back to the card snippet
    instead.
    """
    session = get_session(profile)
    try:
        load_cookies(session, ".stepstone.de", profile)
    except Exception:
        pass  # cookies optional — search results work without them

    bucket = _age_bucket(lookback_hours)
    now = datetime.now()
    cutoff = now - timedelta(hours=lookback_hours)

    jobs = []
    page_num = 1

    pw = sync_playwright().start()
    browser = pw.chromium.launch(headless=True)
    try:
        proxy = to_playwright_proxy(get_proxy_url())
        context = browser.new_context(user_agent=HEADERS["User-Agent"], locale="de-DE", proxy=proxy)

        while page_num <= MAX_PAGES:
            params = {
                "action": f"facet_selected;age;age_{bucket}",
                "ag": f"age_{bucket}",
                "page": page_num,
            }

            resp = session.get(SEARCH_URL.format(keyword=keyword), params=params, timeout=10)

            if resp.status_code in (401, 403):
                raise RuntimeError("StepStone blocked the request — try again later")

            resp.raise_for_status()
            soup = BeautifulSoup(resp.text, "html.parser")
            cards = soup.select("article[data-testid='job-item']")
            if not cards:
                break

            reached_cutoff = False
            new_on_page = 0

            for card in cards:
                try:
                    time_el = card.select_one("time")
                    posted_dt = None
                    if time_el:
                        posted_dt = _parse_relative_age(time_el.get_text(), now)

                    if posted_dt and posted_dt < cutoff:
                        reached_cutoff = True
                        continue

                    title_link = card.select_one("a[data-testid='job-item-title']")
                    if not title_link:
                        continue
                    href = title_link.get("href", "")
                    if not href:
                        continue
                    job_url = href if href.startswith("http") else f"{BASE_URL}{href}"

                    title_el = title_link.select_one(".res-ewgtgq")
                    title = title_el.get_text(strip=True) if title_el else title_link.get_text(strip=True)

                    company_el = card.select_one("[data-at='job-item-company-name'] .res-ewgtgq, [data-at='job-item-company-name'] .res-du9bhi")
                    location_el = card.select_one("[data-at='job-item-location'] .res-du9bhi")

                    company = company_el.get_text(strip=True) if company_el else None
                    location = location_el.get_text(strip=True) if location_el else ""
                    if not title or not company:
                        continue

                    # check job_known BEFORE on_seen — on_seen stamps seen_jobs
                    # with seen_at = now, which would make is_job_recently_seen
                    # immediately return True for this very job if checked after
                    is_new = (title_filter is None or title_filter(title)) and \
                             (job_known is None or not job_known(title, company, location))

                    if on_seen:
                        on_seen(title, company, location)

                    # Try the full detail page first (headless browser); fall
                    # back to the card snippet. Skip the fetch entirely for
                    # title-filtered or already-known jobs.
                    description = None
                    if is_new:
                        description = _fetch_full_description(context, job_url)
                        polite_delay()  # only delay when we actually hit the network
                    if not description:
                        snippet_el = card.select_one(SNIPPET_SELECTOR)
                        description = snippet_el.get_text(separator=" ", strip=True) if snippet_el else None
                        if description:
                            description = description.rstrip(" .") + " …" if not description.endswith("…") else description

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
                            pass
                    new_on_page += 1
                except (AttributeError, KeyError):
                    continue

            if reached_cutoff or new_on_page == 0 or len(cards) < PAGE_SIZE:
                break

            page_num += 1
            polite_delay()

        return jobs
    finally:
        browser.close()
        pw.stop()
