# KarriereScout 

A self-hosted job-hunting dashboard that automatically scrapes **StepStone**, **Indeed**, and **LinkedIn** for matching roles, scores them against your résumé, and tracks your application pipeline — all from a local web UI.

Built for finding working-student / entry-level software roles in Germany, but the filters are fully configurable.

## Features

- **Multi-source scraping** — StepStone, Indeed, and LinkedIn in one place.
- **Smart filtering** — include/exclude by title and description keywords (e.g. keep `Werkstudent`, drop `Senior`).
- **Résumé-fit (ATS) scoring** — upload your résumé (PDF/DOCX) and each job gets a fit score with a category breakdown and improvement suggestions.
- **Application pipeline** — move jobs through `New → Applying → Applied → Ignored`.
- **Scheduled scans** — run automatically on an interval (e.g. every day at 09:00).
- **Push notifications** — get a phone alert per scan via [ntfy.sh](https://ntfy.sh).
- **Light & dark mode** — toggle in the header, remembered across sessions.

## Tech stack

- **Backend:** Python + Flask
- **Scraping:** Playwright, requests, BeautifulSoup, browser-cookie3
- **Parsing:** pypdf, python-docx
- **Storage:** SQLite (`jobs.db`)
- **Frontend:** vanilla HTML/CSS/JS (no build step)

## Setup

```bash
# 1. Create and activate a virtual environment
python -m venv venv
venv\Scripts\activate        # Windows
# source venv/bin/activate   # macOS/Linux

# 2. Install dependencies
pip install -r requirements.txt

# 3. Install the Playwright browser
playwright install chromium

# 4. Run
python main.py
```

The app starts at **http://localhost:5000** and opens your browser automatically.

> On Windows you can also just double-click **`run.bat`**.

## Configuration

Settings live in `config.toml` (or edit them from the in-app settings sidebar):

| Section | What it controls |
|---|---|
| `[search]` | Lookback window and keywords |
| `[sources]` | Which job boards are enabled |
| `[filters]` | Title / description must-contain and blocklists |
| `[schedule]` | Automatic scan time and interval |
| `[browser]` | Browser profile used for cookies (`edge`/`chrome`) |
| `[output]` | Web server port and auto-open |
| `[notifications]` | Your ntfy.sh topic |

### Push notifications (optional)

1. Pick a unique topic name and set it under `[notifications] ntfy_topic` (or in the settings sidebar).
2. Install the [ntfy app](https://ntfy.sh/) and subscribe to that same topic.
3. You'll get a notification each time a scan runs.

### Cookies for blocked sites (optional)

Some sites (Indeed/LinkedIn) may block automated cookie extraction. See
`scraper/cookies/README.txt` for how to export cookies manually.

## Notes

- `jobs.db` (your saved jobs and uploaded résumé) and `venv/` are **git-ignored** — your personal data stays local.
- This tool scrapes public job listings for personal use; respect each site's terms of service.
