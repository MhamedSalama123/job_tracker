"""
LinkedIn scraper.

Uses LinkedIn's public "guest" jobs search API (jobs-guest/jobs/api/...),
which returns server-rendered HTML and requires no login or cookies.
"""

import re
import requests
from bs4 import BeautifulSoup
from .base import fetch_description, polite_delay

SEARCH_URL = "https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search"
JOB_POSTING_URL = "https://www.linkedin.com/jobs-guest/jobs/api/jobPosting/{job_id}"
DESCRIPTION_SELECTOR = ".show-more-less-html__markup"

SOURCE = "linkedin"
PAGE_SIZE = 10
# LinkedIn's guest search will keep paging almost indefinitely for broad
# keywords, returning 500+ results per keyword — most of them low-relevance
# tail results. Cap how many we pull per keyword per run.
MAX_JOBS = 300

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36 Edg/124.0.0.0"
    ),
    "Accept-Language": "de-DE,de;q=0.9,en;q=0.8",
}


def scrape(keyword, lookback_hours, profile="edge", progress_cb=None, title_filter=None, job_known=None, on_seen=None):
    """
    Returns list of job dicts: {title, company, location, url, description, source}
    No cookies needed — the jobs-guest endpoint is public.

    `title_filter`, if given, is called as `title_filter(title) -> bool` right
    after the title is known — when it returns False we skip the description
    fetch (a network request + 1-3s polite delay per job) entirely, since the
    job would be dropped by the title filter downstream anyway. This is purely
    a speed optimization; the real filtering still happens in run_scrape.
    """
    session = requests.Session()
    session.headers.update(HEADERS)

    jobs = []
    page = 0

    while True:
        params = {
            "keywords": keyword,
            "location": "Germany",
            "f_TPR": f"r{lookback_hours * 3600}",
            "start": page * PAGE_SIZE,
        }

        resp = session.get(SEARCH_URL, params=params, timeout=10)

        if resp.status_code in (401, 403):
            raise RuntimeError("LinkedIn blocked the request — try again later")

        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")
        cards = soup.select("li > .base-card")
        if not cards:
            break

        for card in cards:
            if len(jobs) >= MAX_JOBS:
                break
            try:
                urn = card.get("data-entity-urn", "")
                m = re.search(r"jobPosting:(\d+)", urn)
                if not m:
                    continue
                job_id = m.group(1)

                title_el = card.select_one("h3.base-search-card__title")
                company_el = card.select_one("h4.base-search-card__subtitle")
                location_el = card.select_one(".job-search-card__location")

                title = title_el.get_text(strip=True) if title_el else None
                company = company_el.get_text(strip=True) if company_el else None
                location = location_el.get_text(strip=True) if location_el else ""
                if not title or not company:
                    continue

                # check job_known BEFORE on_seen — on_seen stamps seen_jobs
                # with seen_at = now, which would make is_job_recently_seen
                # immediately return True for this very job if checked after
                already_known = job_known and job_known(title, company, location)

                if on_seen:
                    on_seen(title, company, location)

                job_url = f"https://www.linkedin.com/jobs/view/{job_id}"

                # skip description fetch for title-filtered or already-known jobs
                if (title_filter and not title_filter(title)) or already_known:
                    description = None
                else:
                    description = fetch_description(
                        session, JOB_POSTING_URL.format(job_id=job_id), DESCRIPTION_SELECTOR
                    )
                    polite_delay()

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
            except (AttributeError, KeyError):
                continue

        if len(cards) < PAGE_SIZE or len(jobs) >= MAX_JOBS:
            break

        page += 1
        polite_delay()

    return jobs
