from pathlib import Path
from flask import Flask, jsonify, request, render_template
from datetime import datetime
import os
import sys
import time
import json
import io
from db import (get_jobs, set_status, bulk_set_status, delete_job, log_run,
                get_last_run_logs, get_counts, job_exists,
                mark_job_seen, cleanup_seen_jobs,
                delete_jobs_without_description)
from db.database import (
    set_ats_result, add_resume, get_resumes, delete_resume, get_combined_resume_text,
)
from scraper import SCRAPERS
from filters import passes_title_filter, passes_description_filter
from analysis import analyze
from notify import send_ntfy, send_ntfy_text
import toml
import threading

app = Flask(__name__)

CONFIG_PATH = Path(__file__).parent.parent / "config.toml"
_scrape_lock = threading.Lock()
_last_run_time = None
_last_run_duration_sec = None
_progress_lock = threading.Lock()
_progress = {
    "running": False,
    "started_at": None,
    "source": None,
    "keyword": None,
    "job_index": 0,
    "job_title": None,
    "paused": False,
}

# Cooperative stop/pause control for an in-progress scan. Checked from inside
# the per-job callback (on_job), so it can only react between jobs — not mid
# HTTP-request — but that's fine in practice (requests are short).
_control_lock = threading.Lock()
_control = {"stop": False, "paused": False}


# Inherits BaseException (not Exception) so it isn't accidentally swallowed
# by the scrapers' broad `except Exception` guards around progress_cb calls.
class ScanStopped(BaseException):
    pass


def _reset_control():
    with _control_lock:
        _control["stop"] = False
        _control["paused"] = False


def _check_control():
    """Called between jobs: blocks while paused, raises ScanStopped if stopped."""
    while True:
        with _control_lock:
            stop = _control["stop"]
            paused = _control["paused"]
        if stop:
            raise ScanStopped()
        if not paused:
            return
        _set_progress(paused=True)
        time.sleep(0.5)


def _set_progress(**kwargs):
    with _progress_lock:
        _progress.update(kwargs)


def _progress_snapshot():
    with _progress_lock:
        return dict(_progress)


def load_config():
    with open(CONFIG_PATH, encoding="utf-8") as f:
        return toml.load(f)


def _score_job_async(job_id, description):
    """Fire-and-forget resume-fit scoring for a freshly-inserted job. Skipped
    entirely when there's no resume on file or the job has no description text
    (e.g. Indeed jobs, hard-walled StepStone jobs) — nothing to compare.

    Scores against the *combined* text of every uploaded resume — e.g. a
    German CV + an English CV — since job postings here are a mix of both
    languages and the matcher works on literal text overlap."""
    if not description:
        return

    def _run():
        try:
            resume_text = get_combined_resume_text()
            if not resume_text:
                return
            result = analyze(resume_text, description)
            if result is None:
                return
            set_ats_result(job_id, result["score"], json.dumps(result))
        except Exception:
            pass

    threading.Thread(target=_run, daemon=True).start()


def _extract_resume_text(filename, raw_bytes):
    """Pull plain text out of an uploaded PDF or DOCX resume."""
    name = (filename or "").lower()
    if name.endswith(".pdf"):
        from pypdf import PdfReader
        reader = PdfReader(io.BytesIO(raw_bytes))
        return "\n".join((page.extract_text() or "") for page in reader.pages)
    if name.endswith(".docx"):
        from docx import Document
        doc = Document(io.BytesIO(raw_bytes))
        return "\n".join(p.text for p in doc.paragraphs)
    raise ValueError("Unsupported file type — please upload a PDF or DOCX resume.")


_last_schedule_run_date = None


def _scheduler_loop():
    """Background loop — checks once a minute whether it's time to kick off
    the configured daily auto-scan or repeat-interval scan, and triggers it
    (respecting the scan lock so it never overlaps a running scan)."""
    global _last_schedule_run_date
    while True:
        try:
            config = load_config()
            sched = config.get("schedule", {})
            if sched.get("enabled") and not _progress_snapshot()["running"]:
                now = datetime.now()

                # Fixed daily time trigger
                if sched.get("time"):
                    today = now.strftime("%Y-%m-%d")
                    if (now.strftime("%H:%M") == sched["time"]
                            and _last_schedule_run_date != today):
                        _last_schedule_run_date = today
                        threading.Thread(target=run_scrape, daemon=True).start()

                # Repeat-every-N-hours trigger
                repeat_h = int(sched.get("repeat_every_hours") or 0)
                if repeat_h > 0 and _last_run_time:
                    try:
                        last_dt = datetime.strptime(_last_run_time, "%Y-%m-%d %H:%M:%S")
                        if (now - last_dt).total_seconds() >= repeat_h * 3600:
                            threading.Thread(target=run_scrape, daemon=True).start()
                    except Exception:
                        pass
        except Exception:
            pass
        time.sleep(30)


def run_scrape():
    global _last_run_time, _last_run_duration_sec
    if not _scrape_lock.acquire(blocking=False):
        return {"error": "Scrape already running"}

    _reset_control()
    scan_started_at = datetime.now()
    _set_progress(running=True, started_at=scan_started_at.isoformat(),
                  source=None, keyword=None, job_index=0, job_title=None, paused=False)

    try:
        config = load_config()
        keywords = config["search"]["keywords"]
        lookback = config["search"]["lookback_hours"]
        sources = config["sources"]["enabled"]
        profile = config["browser"]["profile"]
        filter_cfg = config.get("filters", {})

        # Passed down to scrapers so they can skip the slow per-job
        # description fetch for jobs that would be filtered or are already
        # in the DB — no point paying for their description.
        def title_ok(title):
            return passes_title_filter(title, filter_cfg)

        def already_known(title, company, location):
            # Only skip the description fetch if the job is actually in the
            # DB already — `is_job_recently_seen` alone isn't enough: a job
            # can be marked "seen" (by on_seen) and then never inserted if
            # the scan is stopped mid-fetch, which would otherwise leave it
            # permanently description-less when it reappears next run.
            return job_exists(title, company, location)

        # Clear seen-jobs entries older than lookback_hours so jobs that
        # have aged out can be reconsidered (e.g. if filters changed).
        cleanup_seen_jobs(max_age_hours=lookback)

        # One-time back-fill: drop Indeed jobs without descriptions so they
        # get re-scraped now that the scraper can fetch them.
        delete_jobs_without_description("indeed")

        ntfy_topic = config.get("notifications", {}).get("ntfy_topic", "")
        if ntfy_topic:
            threading.Thread(
                target=send_ntfy_text,
                args=(ntfy_topic, "Job scan started", f"Scanning {', '.join(sources)}…", "mag"),
                daemon=True,
            ).start()

        run_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        results = {}
        stopped = False

        for source in sources:
            if stopped:
                break

            scrape_fn = SCRAPERS.get(source)
            if not scrape_fn:
                continue

            found = 0
            dupes = 0
            try:
                for keyword in keywords:
                    _set_progress(source=source, keyword=keyword, job_index=0, job_title=None)

                    def on_job(job, idx, _source=source, _keyword=keyword):
                        nonlocal found, dupes
                        _set_progress(source=_source, keyword=_keyword, job_index=idx, job_title=job.get("title"))
                        _check_control()  # raises ScanStopped, or blocks while paused

                        if not passes_title_filter(job["title"], filter_cfg):
                            return
                        if not passes_description_filter(job.get("description"), filter_cfg):
                            return

                        from db.database import insert_job
                        new_id = insert_job(
                            title=job["title"],
                            company=job["company"],
                            location=job.get("location", ""),
                            source=job["source"],
                            url=job["url"],
                            description=job.get("description"),
                        )
                        if new_id:
                            found += 1
                            _score_job_async(new_id, job.get("description"))
                            topic = config.get("notifications", {}).get("ntfy_topic", "")
                            if topic:
                                threading.Thread(
                                    target=send_ntfy,
                                    args=(topic, job["title"], job["company"],
                                          job.get("location", ""), job["url"], job["source"]),
                                    daemon=True,
                                ).start()
                        else:
                            dupes += 1

                    # scrapers insert each job into the DB immediately via
                    # on_job (called as soon as it's scraped + described), so
                    # the UI can show new matches live instead of waiting for
                    # the whole run to finish
                    scrape_fn(keyword, lookback, profile, progress_cb=on_job,
                              title_filter=title_ok, job_known=already_known,
                              on_seen=mark_job_seen)

                log_run(run_time, source, "ok", f"{found} new, {dupes} duplicates")
                results[source] = {"status": "ok", "found": found, "dupes": dupes}

            except ScanStopped:
                stopped = True
                log_run(run_time, source, "stopped", f"stopped by user — {found} new, {dupes} duplicates so far")
                results[source] = {"status": "stopped", "found": found, "dupes": dupes}

            except Exception as e:
                log_run(run_time, source, "error", str(e))
                results[source] = {"status": "error", "message": str(e)}

        _last_run_time = run_time
        return results

    finally:
        _last_run_duration_sec = (datetime.now() - scan_started_at).total_seconds()
        _reset_control()
        _set_progress(running=False, source=None, keyword=None, job_index=0, job_title=None, paused=False)
        _scrape_lock.release()


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/jobs")
def api_jobs():
    status = request.args.get("status", "new")
    jobs = get_jobs(status)
    counts = get_counts()
    return jsonify({"jobs": jobs, "counts": counts})


@app.route("/api/status", methods=["POST"])
def api_set_status():
    data = request.json
    job_id = data.get("id")
    status = data.get("status")
    if not job_id or status not in ("new", "applying", "applied", "ignored"):
        return jsonify({"error": "invalid"}), 400
    set_status(job_id, status)
    return jsonify({"ok": True})


@app.route("/api/status/bulk-ignore-new", methods=["POST"])
def api_bulk_ignore_new():
    """Ignore every job still sitting in 'new' — i.e. everything you didn't
    move to Applying/Applied/Ignore yourself. A quick way to clear the deck."""
    moved = bulk_set_status("new", "ignored")
    return jsonify({"ok": True, "moved": moved, "counts": get_counts()})


@app.route("/api/refresh", methods=["POST"])
def api_refresh():
    if _progress_snapshot()["running"]:
        return jsonify({"error": "Scrape already running"}), 409

    thread = threading.Thread(target=run_scrape, daemon=True)
    thread.start()
    return jsonify({"started": True})


@app.route("/api/restart", methods=["POST"])
def api_restart():
    """Spawn a fresh copy of the process (so code changes — e.g. to the
    scrapers — take effect) and exit this one. Uses subprocess.Popen rather
    than os.execv, which mishandles paths containing spaces on Windows."""
    def _do_restart():
        import subprocess
        time.sleep(0.5)  # let the response flush before we exit
        args = sys.argv + (["--no-open"] if "--no-open" not in sys.argv else [])
        subprocess.Popen([sys.executable] + args, cwd=os.getcwd())
        os._exit(0)

    threading.Thread(target=_do_restart, daemon=True).start()
    return jsonify({"restarting": True})


@app.route("/api/scan/stop", methods=["POST"])
def api_scan_stop():
    if not _progress_snapshot()["running"]:
        return jsonify({"error": "No scan running"}), 409
    with _control_lock:
        _control["stop"] = True
        _control["paused"] = False  # don't leave it stuck waiting on pause
    return jsonify({"ok": True})


@app.route("/api/scan/pause", methods=["POST"])
def api_scan_pause():
    if not _progress_snapshot()["running"]:
        return jsonify({"error": "No scan running"}), 409
    data = request.json or {}
    paused = bool(data.get("paused", True))
    with _control_lock:
        _control["paused"] = paused
    if not paused:
        _set_progress(paused=False)
    return jsonify({"ok": True, "paused": paused})


@app.route("/api/progress")
def api_progress():
    snap = _progress_snapshot()
    if snap.get("running") and not snap.get("started_at"):
        snap["started_at"] = None

    response = dict(snap)
    if not response.get("running"):
        response.update({
            "logs": get_last_run_logs(),
            "counts": get_counts(),
            "last_run": _last_run_time,
            "last_run_duration_sec": _last_run_duration_sec,
        })
    return jsonify(response)


@app.route("/api/logs")
def api_logs():
    return jsonify({
        "logs": get_last_run_logs(),
        "last_run": _last_run_time,
        "last_run_duration_sec": _last_run_duration_sec,
    })


@app.route("/api/counts")
def api_counts():
    return jsonify(get_counts())


@app.route("/api/config", methods=["GET"])
def api_get_config():
    config = load_config()
    return jsonify({
        "search": config.get("search", {}),
        "filters": config.get("filters", {}),
        "sources": config.get("sources", {}).get("enabled", []),
        "all_sources": list(SCRAPERS.keys()),
        "schedule": config.get("schedule", {"enabled": False, "time": "09:00"}),
        "notifications": config.get("notifications", {"ntfy_topic": ""}),
    })


@app.route("/api/config", methods=["POST"])
def api_set_config():
    data = request.json or {}
    config = load_config()

    if "search" in data:
        config.setdefault("search", {})
        if "keywords" in data["search"]:
            config["search"]["keywords"] = data["search"]["keywords"]

    if "sources" in data:
        config.setdefault("sources", {})
        if "enabled" in data["sources"]:
            valid = [s for s in data["sources"]["enabled"] if s in SCRAPERS]
            config["sources"]["enabled"] = valid

    if "filters" in data:
        config.setdefault("filters", {})
        for key in ("title_must_contain", "title_blocklist",
                    "description_must_contain", "description_blocklist"):
            if key in data["filters"]:
                config["filters"][key] = data["filters"][key]

    if "schedule" in data:
        config.setdefault("schedule", {})
        if "enabled" in data["schedule"]:
            config["schedule"]["enabled"] = bool(data["schedule"]["enabled"])
        if "time" in data["schedule"]:
            t = str(data["schedule"]["time"]).strip()
            # basic HH:MM validation — fall back to a sane default otherwise
            import re as _re
            if _re.match(r"^([01]\d|2[0-3]):[0-5]\d$", t):
                config["schedule"]["time"] = t
        if "repeat_every_hours" in data["schedule"]:
            h = int(data["schedule"]["repeat_every_hours"] or 0)
            config["schedule"]["repeat_every_hours"] = max(0, min(h, 24))

    if "notifications" in data:
        config.setdefault("notifications", {})
        topic = str(data["notifications"].get("ntfy_topic", "")).strip()
        config["notifications"]["ntfy_topic"] = topic

    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        toml.dump(config, f)

    removed = 0
    if "filters" in data:
        filter_cfg = config.get("filters", {})
        for job in get_jobs("all"):
            if not passes_title_filter(job["title"], filter_cfg):
                delete_job(job["id"])
                removed += 1
                continue
            if not passes_description_filter(job.get("description"), filter_cfg):
                delete_job(job["id"])
                removed += 1

    return jsonify({"ok": True, "removed": removed, "counts": get_counts()})


@app.route("/api/resume", methods=["GET"])
def api_get_resume():
    resumes = get_resumes()
    return jsonify({
        "uploaded": len(resumes) > 0,
        "resumes": [
            {
                "id": r["id"],
                "filename": r.get("filename"),
                "uploaded_at": r.get("uploaded_at"),
                "word_count": len((r.get("text") or "").split()),
            }
            for r in resumes
        ],
    })


def _rescore_all_jobs():
    """Re-score every job that already has a description against the current
    combined resume text — run after any upload/delete so existing cards
    reflect the change immediately rather than waiting for the next scrape."""
    try:
        resume_text = get_combined_resume_text()
        for job in get_jobs("all"):
            desc = job.get("description")
            if not desc:
                continue
            if not resume_text:
                set_ats_result(job["id"], None, None)
                continue
            result = analyze(resume_text, desc)
            if result is not None:
                set_ats_result(job["id"], result["score"], json.dumps(result))
    except Exception:
        pass


@app.route("/api/resume", methods=["POST"])
def api_upload_resume():
    f = request.files.get("resume")
    if not f or not f.filename:
        return jsonify({"ok": False, "error": "No file uploaded"}), 400

    try:
        raw = f.read()
        text = _extract_resume_text(f.filename, raw)
    except ValueError as e:
        return jsonify({"ok": False, "error": str(e)}), 400
    except Exception as e:
        return jsonify({"ok": False, "error": f"Couldn't read that file: {e}"}), 400

    text = (text or "").strip()
    if len(text.split()) < 50:
        return jsonify({
            "ok": False,
            "error": "That doesn't look like a resume — too little extractable text. "
                     "If it's a scanned/image-based PDF, try exporting it as text-based instead.",
        }), 400

    add_resume(f.filename, text)
    threading.Thread(target=_rescore_all_jobs, daemon=True).start()

    return jsonify({
        "ok": True,
        "filename": f.filename,
        "word_count": len(text.split()),
    })


@app.route("/api/resume/<int:resume_id>", methods=["DELETE"])
def api_delete_resume(resume_id):
    delete_resume(resume_id)
    threading.Thread(target=_rescore_all_jobs, daemon=True).start()
    return jsonify({"ok": True})


# Start the daily-schedule checker once when the app module loads.
threading.Thread(target=_scheduler_loop, daemon=True).start()
