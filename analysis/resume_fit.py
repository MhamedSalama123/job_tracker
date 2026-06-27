"""
Resume <-> job-description fit analysis.

Ported from the PHP "ATS-Friendly-Resume-Analyzer" project
(github.com/hibareprasad0302-spec/ATS-Friendly-Resume-Analyzer) — its scoring
logic is pure text-processing/regex/arithmetic with no framework dependencies,
so it translates directly to Python. The 7-category, 100-point rubric and the
weighting are kept as in the original; only the implementation language and
the surrounding plumbing (DB-backed skills table, file uploads, multi-user
auth, etc.) have been dropped in favor of a single-user, in-process module
that fits this app's existing Flask/SQLite stack.

Entry point: `analyze(resume_text, job_description) -> dict`
"""

import re
from collections import Counter

from .text_data import (
    STOPWORDS, JD_STOPWORDS, SECTION_HEADERS, ACTION_VERBS,
    DEGREE_TERMS, INSTITUTION_TERMS, PROJECT_TECH_TERMS,
)
from .skills_data import SKILLS

SCORE_WEIGHTS = {
    'keyword': 30,
    'skills': 20,
    'sections': 15,
    'projects': 10,
    'experience': 10,
    'education': 5,
    'formatting': 10,
}

_WORD_RE = re.compile(r'[^a-zA-Z0-9\s.+#\-/]')
_WS_RE = re.compile(r'\s+')


# ---------------------------------------------------------------- text utils

def _clean(text):
    text = _WS_RE.sub(' ', text.strip())
    text = _WORD_RE.sub('', text)
    return text.lower()


def _tokenize(text):
    return [w for w in _WS_RE.split(text.strip()) if len(w) > 1]


def _ngrams(tokens, n=2):
    return [' '.join(tokens[i:i + n]) for i in range(len(tokens) - n + 1)]


def _word_in_text(word, text):
    """Whole-word (boundary-respecting) substring match — mirrors the PHP
    `preg_match('/\\b<word>\\b/i', ...)` used throughout the original."""
    return re.search(r'\b' + re.escape(word) + r'\b', text, re.IGNORECASE) is not None


# ---------------------------------------------------------- keyword pipeline

def _extract_jd_keywords(jd_text, limit=50):
    """TF-style top keywords + repeated bigrams from a job description, with
    generic ATS/recruiting filler words stripped out — same heuristic as the
    original KeywordExtractor (single + double counted-bigram frequency,
    sorted, top N)."""
    cleaned = _clean(jd_text)
    tokens = _tokenize(cleaned)
    filtered = [t for t in tokens if t not in STOPWORDS]
    freq = Counter(filtered)

    bigrams = _ngrams(tokens, 2)
    bigram_freq = Counter(bigrams)

    keywords = {}
    for word, count in freq.items():
        word = word.strip('.,;:!?')
        if word and word not in JD_STOPWORDS and word not in STOPWORDS and len(word) > 2:
            keywords[word] = keywords.get(word, 0) + count
    for bigram, count in bigram_freq.items():
        if count < 2:
            continue
        w1, _, w2 = bigram.partition(' ')
        w1, w2 = w1.strip('.,;:!?'), w2.strip('.,;:!?')
        # skip phrases anchored on filler words — "you will", "be part of" —
        # they're noise; a useful bigram should be carrying real content on
        # both ends (e.g. "real-time", "machine learning")
        if (not w1 or not w2 or len(w1) <= 2 or len(w2) <= 2
                or w1 in STOPWORDS or w2 in STOPWORDS
                or w1 in JD_STOPWORDS or w2 in JD_STOPWORDS):
            continue
        keywords[f"{w1} {w2}"] = count * 2

    ranked = sorted(keywords.items(), key=lambda kv: kv[1], reverse=True)
    return [k for k, _ in ranked[:limit]]


def _match_keywords(jd_keywords, resume_text):
    cleaned_resume = _clean(resume_text)
    matched, missing = [], []
    for kw in jd_keywords:
        (matched if _word_in_text(kw, cleaned_resume) else missing).append(kw)

    total = len(jd_keywords)
    pct = (len(matched) / total * 100) if total else 0
    return {'matched': matched, 'missing': missing, 'percentage': round(pct, 2)}


# ------------------------------------------------------------ skill matching

def _match_skills(jd_text, resume_text):
    jd_clean = _clean(jd_text)
    resume_clean = _clean(resume_text)

    # which of our known skills actually appear in the JD at all?
    jd_skills = []
    for skill in SKILLS:
        names = [skill['name']] + list(skill.get('aliases') or [])
        if any(_word_in_text(n, jd_clean) for n in names):
            jd_skills.append(skill)

    matched, missing = [], []
    for skill in jd_skills:
        names = [skill['name']] + list(skill.get('aliases') or [])
        if any(_word_in_text(n, resume_clean) for n in names):
            matched.append(skill['name'])
        else:
            missing.append(skill['name'])

    total = len(jd_skills)
    pct = (len(matched) / total * 100) if total else 0
    return {'matched': matched, 'missing': missing, 'percentage': round(pct, 2)}


# --------------------------------------------------------- structural checks

def _detect_sections(resume_text):
    low = resume_text.lower()
    detected, missing = [], []
    for key, headers in SECTION_HEADERS.items():
        found = False
        for h in headers:
            pattern = r'(?:^|\n)\s*' + re.escape(h) + r'\s*[:\-–]?\s*(?:\n|$)'
            if re.search(pattern, low, re.IGNORECASE):
                found = True
                break
        if not found:
            found = any(h in low for h in headers)
        (detected if found else missing).append(key)
    return {'detected': detected, 'missing': missing}


def _analyze_experience(resume_text):
    text = resume_text.lower()
    has_section = any(h in text for h in SECTION_HEADERS['experience'])

    action_verbs_count = sum(
        1 for v in ACTION_VERBS
        if re.search(r'\b' + re.escape(v) + r'\b', text, re.IGNORECASE)
    )
    quantifiable_count = len(re.findall(
        r'\d+\s*%|\$\s*[\d,]+|\d+\s*(?:users|clients|projects|teams|members|employees)',
        text, re.IGNORECASE
    ))
    positions_count = len(re.findall(
        r'(?:20\d{2}|19\d{2})\s*[-–]\s*(?:20\d{2}|19\d{2}|present|current)',
        text, re.IGNORECASE
    ))
    if positions_count == 0:
        positions_count = len(re.findall(
            r'(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\s+\d{4}\s*[-–]',
            text, re.IGNORECASE
        ))

    return {
        'has_section': has_section,
        'action_verbs_count': action_verbs_count,
        'quantifiable_count': quantifiable_count,
        'positions_count': positions_count,
    }


def _analyze_education(resume_text):
    text = resume_text.lower()
    return {
        'has_section': any(h in text for h in SECTION_HEADERS['education']),
        'has_degree': any(re.search(r'\b' + d + r'\b', text, re.IGNORECASE) for d in DEGREE_TERMS),
        'has_institution': any(i in text for i in INSTITUTION_TERMS),
        'has_graduation_date': bool(re.search(r'(?:20\d{2}|19\d{2})', text, re.IGNORECASE)),
    }


def _analyze_projects(resume_text):
    text = resume_text.lower()
    has_section = any(h in text for h in SECTION_HEADERS['projects'])

    project_count = max(
        len(re.findall(r'(?:^|\n)\s*(?:[-•*]|\d+[.)])\s*[A-Z]', resume_text, re.MULTILINE)),
        len(re.findall(r'project\s*(?:name|title)?:\s*', text, re.IGNORECASE)),
        1 if has_section else 0,
    )
    project_count = min(project_count, 10)

    return {
        'has_section': has_section,
        'project_count': project_count,
        'has_tech_mentions': any(t in text for t in PROJECT_TECH_TERMS),
    }


def _analyze_formatting(resume_text):
    words = [w for w in _WS_RE.split(resume_text.strip()) if w]
    word_count = len(words)

    has_email = bool(re.search(r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}', resume_text))
    has_phone = bool(re.search(r'(?:\+?\d{1,3}[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}', resume_text))

    section_count = 0
    for headers in SECTION_HEADERS.values():
        if any(h in resume_text.lower() for h in headers):
            section_count += 1
    has_consistent_structure = section_count >= 3

    lines = resume_text.split('\n')
    non_empty = [l for l in lines if l.strip()]
    avg_line_len = (sum(len(l) for l in non_empty) / len(non_empty)) if non_empty else 0
    has_clean_linebreaks = avg_line_len < 200 and len(non_empty) > 10

    total_chars = len(resume_text)
    special_ratio = 0.0
    if total_chars:
        special_chars = len(re.findall(r'[^a-zA-Z0-9\s.,;:\-()/@+#]', resume_text))
        special_ratio = round(special_chars / total_chars, 4)

    return {
        'word_count': word_count,
        'has_email': has_email,
        'has_phone': has_phone,
        'has_consistent_structure': has_consistent_structure,
        'has_clean_linebreaks': has_clean_linebreaks,
        'special_char_ratio': special_ratio,
    }


# --------------------------------------------------------------- scoring


def _score_keywords(result):
    max_pts = SCORE_WEIGHTS['keyword']
    pct = (result.get('percentage') or 0) / 100
    base = pct * (max_pts - 5)
    bonus = 5 if pct >= 0.8 else (3 if pct >= 0.6 else 0)
    score = base + bonus
    if result.get('matched') and score < 2:
        score = 2
    return round(min(score, max_pts), 2)


def _score_skills(result):
    max_pts = SCORE_WEIGHTS['skills']
    total = len(result.get('matched') or []) + len(result.get('missing') or [])
    if total == 0:
        return round(max_pts * 0.75, 2)
    pct = len(result['matched']) / total
    return round(pct * max_pts, 2)


def _score_sections(result):
    max_pts = SCORE_WEIGHTS['sections']
    detected = result.get('detected') or []
    score = 0
    for s in ('experience', 'education', 'skills', 'contact'):
        if s in detected:
            score += 3
    for s in ('projects', 'certifications', 'summary'):
        if s in detected:
            score += 1
    return round(min(score, max_pts), 2)


def _score_projects(result):
    max_pts = SCORE_WEIGHTS['projects']
    score = 0
    if result.get('has_section'):
        score += 3
    score += min(result.get('project_count', 0), 3) * 1.5
    if result.get('has_tech_mentions'):
        score += 2.5
    return round(min(score, max_pts), 2)


def _score_experience(result):
    max_pts = SCORE_WEIGHTS['experience']
    score = 0
    if result.get('has_section'):
        score += 2
    score += (min(result.get('action_verbs_count', 0), 6) / 6) * 3
    score += (min(result.get('quantifiable_count', 0), 4) / 4) * 3
    score += (min(result.get('positions_count', 0), 3) / 3) * 2
    return round(min(score, max_pts), 2)


def _score_education(result):
    max_pts = SCORE_WEIGHTS['education']
    score = 0
    if result.get('has_section'):
        score += 1
    if result.get('has_degree'):
        score += 2
    if result.get('has_institution'):
        score += 1
    if result.get('has_graduation_date'):
        score += 1
    return round(min(score, max_pts), 2)


def _score_formatting(result):
    max_pts = SCORE_WEIGHTS['formatting']
    score = 0
    wc = result.get('word_count', 0)
    if 300 <= wc <= 1500:
        score += 3
    elif 150 <= wc <= 2000:
        score += 1.5
    if result.get('has_consistent_structure'):
        score += 2
    ratio = result.get('special_char_ratio', 0)
    if ratio < 0.02:
        score += 2
    elif ratio < 0.05:
        score += 1
    if result.get('has_email'):
        score += 1
    if result.get('has_phone'):
        score += 1
    if result.get('has_clean_linebreaks'):
        score += 1
    return round(min(score, max_pts), 2)


def _calculate_scores(keyword_r, skill_r, section_r, project_r, exp_r, edu_r, fmt_r):
    scores = {
        'keyword': _score_keywords(keyword_r),
        'skills': _score_skills(skill_r),
        'sections': _score_sections(section_r),
        'projects': _score_projects(project_r),
        'experience': _score_experience(exp_r),
        'education': _score_education(edu_r),
        'formatting': _score_formatting(fmt_r),
    }
    scores['total'] = round(sum(scores.values()), 2)
    scores['maximums'] = dict(SCORE_WEIGHTS)
    scores['maximums']['total'] = 100
    return scores


# ------------------------------------------------------------- suggestions

def _generate_suggestions(scores, keyword_r, skill_r, section_r):
    suggestions = []

    kw_pct = keyword_r.get('percentage', 0)
    if kw_pct < 50:
        top_missing = (keyword_r.get('missing') or [])[:10]
        suggestions.append({
            'category': 'keywords', 'priority': 'high',
            'message': ('Your resume matches less than 50% of the job description '
                        'keywords. Consider incorporating these missing terms: '
                        + ', '.join(top_missing) + '.'),
        })
    elif kw_pct < 75:
        top_missing = (keyword_r.get('missing') or [])[:5]
        suggestions.append({
            'category': 'keywords', 'priority': 'medium',
            'message': ('Good keyword coverage, but you could strengthen it by '
                        'adding: ' + ', '.join(top_missing) + '.'),
        })

    missing_skills = skill_r.get('missing') or []
    if missing_skills:
        suggestions.append({
            'category': 'skills',
            'priority': 'high' if len(missing_skills) > 3 else 'medium',
            'message': ('The job requires these skills not found in your resume: '
                        + ', '.join(missing_skills)
                        + '. Add them to your skills section if you possess them.'),
        })

    core_sections = ('experience', 'education', 'skills')
    # "languages" is tracked for completeness (common on German CVs) but it's
    # not a section ATS systems specifically expect — don't nag about it
    optional_no_nag = ('languages',)
    for section in section_r.get('missing') or []:
        if section in optional_no_nag:
            continue
        suggestions.append({
            'category': 'sections',
            'priority': 'high' if section in core_sections else 'medium',
            'message': (f"Your resume is missing a '{section.capitalize()}' section. "
                        "ATS systems expect this section to be clearly labeled."),
        })

    exp_max = scores['maximums'].get('experience', 10)
    if scores.get('experience', 0) < exp_max * 0.5:
        suggestions.append({
            'category': 'experience', 'priority': 'medium',
            'message': ('Strengthen your experience section with action verbs '
                        '(led, developed, implemented, optimized) and quantifiable '
                        'achievements (increased revenue by 20%, reduced load time by 40%).'),
        })

    fmt_max = scores['maximums'].get('formatting', 10)
    if scores.get('formatting', 0) < fmt_max * 0.5:
        suggestions.append({
            'category': 'formatting', 'priority': 'medium',
            'message': ('Improve your resume formatting: use clear section headers, '
                        'maintain consistent bullet points, and keep length between '
                        '1-2 pages (300-1500 words).'),
        })

    edu_max = scores['maximums'].get('education', 5)
    if scores.get('education', 0) < edu_max * 0.5:
        suggestions.append({
            'category': 'education', 'priority': 'low',
            'message': ('Ensure your education section includes your degree name, '
                        'institution, and graduation date.'),
        })

    return suggestions


# --------------------------------------------------------------- public API

def analyze(resume_text, job_description):
    """
    Compare a resume against a job description and return:
      {
        "score": <0-100 int>,
        "breakdown": {category: points, ..., "maximums": {...}},
        "suggestions": [{"category", "priority", "message"}, ...],
        "matched_keywords": [...], "missing_keywords": [...],
        "matched_skills": [...], "missing_skills": [...],
      }

    Returns None if either input is too short to analyze meaningfully (e.g.
    a job with no description — nothing to compare against).
    """
    if not resume_text or not job_description:
        return None
    if len(job_description.split()) < 15:
        return None

    jd_keywords = _extract_jd_keywords(job_description)
    keyword_r = _match_keywords(jd_keywords, resume_text)
    skill_r = _match_skills(job_description, resume_text)
    section_r = _detect_sections(resume_text)
    project_r = _analyze_projects(resume_text)
    exp_r = _analyze_experience(resume_text)
    edu_r = _analyze_education(resume_text)
    fmt_r = _analyze_formatting(resume_text)

    scores = _calculate_scores(keyword_r, skill_r, section_r, project_r, exp_r, edu_r, fmt_r)
    suggestions = _generate_suggestions(scores, keyword_r, skill_r, section_r)

    return {
        'score': int(round(scores['total'])),
        'breakdown': scores,
        'suggestions': suggestions,
        'matched_keywords': keyword_r['matched'],
        'missing_keywords': keyword_r['missing'],
        'matched_skills': skill_r['matched'],
        'missing_skills': skill_r['missing'],
    }
