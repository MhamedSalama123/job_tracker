import re


def _word_match(keyword, text):
    """Return True if `keyword` appears as a whole word in `text` (case-insensitive).
    For single-word keywords this uses a word-boundary regex so 'ROS' won't
    match 'across' or 'gross'. Multi-word phrases fall back to plain substring
    since word boundaries don't apply across spaces the same way."""
    kw = keyword.lower()
    t  = text.lower()
    if ' ' in kw:
        return kw in t
    return bool(re.search(r'\b' + re.escape(kw) + r'\b', t))


def passes_title_filter(title, config):
    title_lower = title.lower()

    must_contain = config.get("title_must_contain", [])
    if must_contain and not any(_word_match(kw, title_lower) for kw in must_contain):
        return False

    blocklist = config.get("title_blocklist", [])
    if any(_word_match(kw, title_lower) for kw in blocklist):
        return False

    return True


def passes_description_filter(description, config):
    if not description:
        return True  # don't discard jobs with unavailable descriptions

    desc_lower = description.lower()

    must_contain = config.get("description_must_contain", [])
    if must_contain and not any(_word_match(kw, desc_lower) for kw in must_contain):
        return False

    blocklist = config.get("description_blocklist", [])
    if any(_word_match(kw, desc_lower) for kw in blocklist):
        return False

    return True
