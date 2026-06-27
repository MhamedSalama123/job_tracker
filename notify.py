"""
Notification senders for the Job Finder app.
Currently supports ntfy.sh push notifications.
"""

import requests as _requests

NTFY_BASE = "https://ntfy.sh"


def send_ntfy(topic: str, title: str, company: str, location: str,
              url: str, source: str) -> bool:
    """POST a new-job notification to an ntfy.sh topic.
    Returns True on success, False on any error (non-fatal — never raises)."""
    if not topic:
        return False
    try:
        loc_str = f" · {location}" if location else ""
        body = f"{company}{loc_str}"
        resp = _requests.post(
            f"{NTFY_BASE}/{topic}",
            data=body.encode("utf-8"),
            headers={
                "Title": title,
                "Click": url,
                "Tags": f"briefcase,{source}",
                "Priority": "default",
            },
            timeout=8,
        )
        return resp.status_code in (200, 204)
    except Exception:
        return False


def send_ntfy_text(topic: str, title: str, message: str, tags: str = "mag") -> bool:
    """POST a plain text notification to an ntfy.sh topic.
    Returns True on success, False on any error (non-fatal — never raises)."""
    if not topic:
        return False
    try:
        resp = _requests.post(
            f"{NTFY_BASE}/{topic}",
            data=message.encode("utf-8"),
            headers={
                "Title": title,
                "Tags": tags,
                "Priority": "low",
            },
            timeout=8,
        )
        return resp.status_code in (200, 204)
    except Exception:
        return False
