import sqlite3
import hashlib
import re
from pathlib import Path

DB_PATH = Path(__file__).parent.parent / "jobs.db"


def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    with get_conn() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS jobs (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                hash        TEXT UNIQUE NOT NULL,
                title       TEXT NOT NULL,
                company     TEXT NOT NULL,
                location    TEXT,
                source      TEXT NOT NULL,
                url         TEXT NOT NULL,
                description TEXT,
                status      TEXT NOT NULL DEFAULT 'new',
                date_found  TEXT NOT NULL DEFAULT (datetime('now')),
                ats_score   INTEGER,
                ats_report  TEXT
            )
        """)
        # Older DBs won't have these columns yet — SQLite has no
        # `ADD COLUMN IF NOT EXISTS`, so just try and ignore the duplicate-
        # column error if they're already there.
        for col_def in ("ats_score INTEGER", "ats_report TEXT"):
            try:
                conn.execute(f"ALTER TABLE jobs ADD COLUMN {col_def}")
            except sqlite3.OperationalError:
                pass
        # Multiple resumes are supported (e.g. a German CV + an English CV) —
        # job postings in this market are a mix of both languages, and the
        # ATS-fit engine matches on literal text, so storing both and
        # combining their text for scoring gives much better keyword/skill
        # coverage than picking just one.
        conn.execute("""
            CREATE TABLE IF NOT EXISTS resumes (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                filename    TEXT,
                text        TEXT,
                uploaded_at TEXT NOT NULL DEFAULT (datetime('now'))
            )
        """)
        # One-time migration from the old single-resume singleton table, if
        # it exists and `resumes` is still empty.
        try:
            old = conn.execute("SELECT filename, text, uploaded_at FROM resume WHERE id = 1").fetchone()
            if old and old["text"]:
                count = conn.execute("SELECT COUNT(*) AS c FROM resumes").fetchone()["c"]
                if count == 0:
                    conn.execute(
                        "INSERT INTO resumes (filename, text, uploaded_at) VALUES (?, ?, ?)",
                        (old["filename"], old["text"], old["uploaded_at"])
                    )
        except sqlite3.OperationalError:
            pass  # no old `resume` table — fresh DB
        conn.execute("""
            CREATE TABLE IF NOT EXISTS run_logs (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                run_time    TEXT NOT NULL DEFAULT (datetime('now')),
                source      TEXT NOT NULL,
                status      TEXT NOT NULL,
                message     TEXT
            )
        """)
        # Seen-jobs cache — every job encountered in search results is stamped
        # here regardless of whether it passes filters or is inserted. Entries
        # older than 24 h are pruned at the start of each scrape run so jobs
        # can be reconsidered if filters change or descriptions update.
        conn.execute("""
            CREATE TABLE IF NOT EXISTS seen_jobs (
                hash     TEXT PRIMARY KEY,
                title    TEXT NOT NULL,
                company  TEXT NOT NULL,
                location TEXT,
                seen_at  TEXT NOT NULL DEFAULT (datetime('now'))
            )
        """)
        conn.commit()


def make_hash(title, company, location):
    def normalize(s):
        s = (s or "").lower()
        s = re.sub(r'[^\w\s]', '', s)
        return re.sub(r'\s+', ' ', s).strip()
    raw = f"{normalize(title)}|{normalize(company)}|{normalize(location)}"
    return hashlib.sha256(raw.encode()).hexdigest()


def job_exists(title, company, location):
    """Return True if a job with this title/company/location is already in the DB."""
    h = make_hash(title, company, location)
    with get_conn() as conn:
        row = conn.execute("SELECT 1 FROM jobs WHERE hash = ?", (h,)).fetchone()
        return row is not None


def insert_job(title, company, location, source, url, description=None):
    """Returns the new row's id on insert, or None if it was a duplicate."""
    h = make_hash(title, company, location)
    with get_conn() as conn:
        try:
            cur = conn.execute("""
                INSERT INTO jobs (hash, title, company, location, source, url, description)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (h, title, company, location, source, url, description))
            conn.commit()
            return cur.lastrowid  # new job
        except sqlite3.IntegrityError:
            return None  # duplicate


def get_jobs(status=None):
    with get_conn() as conn:
        if status and status != 'all':
            rows = conn.execute(
                "SELECT * FROM jobs WHERE status = ? ORDER BY date_found DESC", (status,)
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM jobs ORDER BY date_found DESC"
            ).fetchall()
        return [dict(r) for r in rows]


def set_status(job_id, status):
    with get_conn() as conn:
        conn.execute("UPDATE jobs SET status = ? WHERE id = ?", (status, job_id))
        conn.commit()


def bulk_set_status(from_status, to_status):
    """Move every job currently in `from_status` to `to_status`. Returns the
    number of rows affected — used for "ignore everything I haven't acted on"."""
    with get_conn() as conn:
        cur = conn.execute(
            "UPDATE jobs SET status = ? WHERE status = ?", (to_status, from_status)
        )
        conn.commit()
        return cur.rowcount


def delete_job(job_id):
    with get_conn() as conn:
        conn.execute("DELETE FROM jobs WHERE id = ?", (job_id,))
        conn.commit()


def log_run(run_time, source, status, message=None):
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO run_logs (run_time, source, status, message) VALUES (?, ?, ?, ?)",
            (run_time, source, status, message)
        )
        conn.commit()


def get_last_run_logs():
    with get_conn() as conn:
        # get logs from the most recent run time
        last_time = conn.execute(
            "SELECT run_time FROM run_logs ORDER BY id DESC LIMIT 1"
        ).fetchone()
        if not last_time:
            return []
        rows = conn.execute(
            "SELECT * FROM run_logs WHERE run_time = ?", (last_time["run_time"],)
        ).fetchall()
        return [dict(r) for r in rows]


def get_counts():
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT status, COUNT(*) as count FROM jobs GROUP BY status"
        ).fetchall()
        counts = {"new": 0, "applying": 0, "applied": 0, "ignored": 0, "all": 0}
        for r in rows:
            counts[r["status"]] = r["count"]
            counts["all"] += r["count"]
        return counts


# --------------------------------------------------------------- ATS / resume

def set_ats_result(job_id, score, report_json):
    """Store the resume-fit score (0-100 int) and full JSON report for a job."""
    with get_conn() as conn:
        conn.execute(
            "UPDATE jobs SET ats_score = ?, ats_report = ? WHERE id = ?",
            (score, report_json, job_id)
        )
        conn.commit()


def add_resume(filename, text):
    """Add a resume (doesn't replace existing ones — e.g. you can keep both
    a German and an English CV on file for mixed-language job postings)."""
    with get_conn() as conn:
        cur = conn.execute(
            "INSERT INTO resumes (filename, text, uploaded_at) VALUES (?, ?, datetime('now'))",
            (filename, text)
        )
        conn.commit()
        return cur.lastrowid


def get_resumes():
    with get_conn() as conn:
        rows = conn.execute("SELECT * FROM resumes ORDER BY id").fetchall()
        return [dict(r) for r in rows]


def delete_resume(resume_id):
    with get_conn() as conn:
        conn.execute("DELETE FROM resumes WHERE id = ?", (resume_id,))
        conn.commit()


def get_combined_resume_text():
    """Concatenate the text of every uploaded resume into one block for
    scoring — this is what actually gets compared against job descriptions,
    so having e.g. both a German and an English CV on file means German *and*
    English keyword/skill vocabulary is available for matching, regardless of
    which language a given job posting is written in."""
    resumes = get_resumes()
    if not resumes:
        return None
    return "\n\n".join(r["text"] for r in resumes if r.get("text"))


# ---------------------------------------------------------------- seen-jobs cache

def mark_job_seen(title, company, location):
    """Stamp a job as seen right now. Called for every job found in search
    results, before any filter or dedup check, so even filtered-out jobs are
    remembered and won't be re-fetched on the next run."""
    h = make_hash(title, company, location)
    with get_conn() as conn:
        conn.execute("""
            INSERT INTO seen_jobs (hash, title, company, location, seen_at)
            VALUES (?, ?, ?, ?, datetime('now'))
            ON CONFLICT(hash) DO UPDATE SET seen_at = datetime('now')
        """, (h, title, company, location))
        conn.commit()


def is_job_recently_seen(title, company, location, max_age_hours=24):
    """Return True if this job was seen within the last `max_age_hours`."""
    h = make_hash(title, company, location)
    with get_conn() as conn:
        row = conn.execute("""
            SELECT 1 FROM seen_jobs
            WHERE hash = ?
              AND seen_at >= datetime('now', ? || ' hours')
        """, (h, f"-{max_age_hours}")).fetchone()
        return row is not None


def cleanup_seen_jobs(max_age_hours=24):
    """Delete seen-jobs entries older than `max_age_hours`. Called once at the
    start of each scrape run so stale entries don't block re-evaluation."""
    with get_conn() as conn:
        cur = conn.execute("""
            DELETE FROM seen_jobs
            WHERE seen_at < datetime('now', ? || ' hours')
        """, (f"-{max_age_hours}",))
        conn.commit()
        return cur.rowcount


# ---------------------------------------------------------------- maintenance

def delete_jobs_without_description(source):
    """Delete all jobs from `source` that have no description — used to force
    a clean re-scrape after the scraper gains description support."""
    with get_conn() as conn:
        cur = conn.execute(
            "DELETE FROM jobs WHERE source = ? AND (description IS NULL OR description = '')",
            (source,)
        )
        conn.commit()
        return cur.rowcount
