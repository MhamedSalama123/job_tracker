"""Static word lists used by the resume-fit analyzer — ported verbatim from
ATS-Friendly-Resume-Analyzer's data/stopwords.php and data/section_headers.php."""

STOPWORDS = {
    'the', 'a', 'an', 'and', 'or', 'but', 'in', 'on', 'at', 'to', 'for',
    'of', 'with', 'by', 'from', 'is', 'are', 'was', 'were', 'be', 'been',
    'being', 'have', 'has', 'had', 'do', 'does', 'did', 'will', 'would',
    'could', 'should', 'may', 'might', 'shall', 'can', 'it', 'its',
    'this', 'that', 'these', 'those', 'i', 'me', 'my', 'we', 'our',
    'you', 'your', 'he', 'she', 'him', 'her', 'his', 'they', 'them',
    'their', 'what', 'which', 'who', 'whom', 'when', 'where', 'why',
    'how', 'all', 'each', 'every', 'both', 'few', 'more', 'most',
    'other', 'some', 'such', 'no', 'not', 'only', 'own', 'same',
    'so', 'than', 'too', 'very', 'just', 'about', 'above', 'after',
    'again', 'also', 'am', 'any', 'as', 'because', 'before', 'below',
    'between', 'during', 'if', 'into', 'here', 'there', 'then',
    'out', 'up', 'down', 'off', 'over', 'under', 'further',
    'once', 'nor', 'yet', 'while', 'until', 'through', 'against',
    'along', 'around', 'among', 'upon', 'without', 'within',
    'however', 'therefore', 'thus', 'hence', 'since', 'although',
    'though', 'whether', 'either', 'neither', 'much', 'many',
    'several', 'various', 'enough', 'rather', 'quite', 'somewhat',
    'still', 'already', 'always', 'never', 'often', 'sometimes',
    'usually', 'perhaps', 'maybe', 'likely', 'anyway', 'besides',
    'instead', 'meanwhile', 'otherwise', 'regardless', 'nevertheless',
    'nonetheless', 'furthermore', 'moreover', 'actually', 'basically',
    'essentially', 'generally', 'particularly', 'specifically',
    'itself', 'himself', 'herself', 'themselves', 'ourselves',
    'yourself', 'myself', 'anything', 'everything', 'something',
    'nothing', 'anyone', 'everyone', 'someone', 'nobody',
    'get', 'got', 'getting', 'make', 'made', 'making',
    'come', 'came', 'go', 'went', 'gone', 'going',
    'take', 'took', 'taken', 'give', 'gave', 'given',
    'see', 'saw', 'seen', 'know', 'knew', 'known',
    'think', 'thought', 'say', 'said', 'tell', 'told',
    'use', 'used', 'using', 'find', 'found',
    'want', 'need', 'try', 'keep', 'let', 'put',
    'seem', 'help', 'show', 'hear', 'play', 'run',
    'move', 'like', 'live', 'believe', 'hold', 'bring',
    'happen', 'write', 'provide', 'sit', 'stand', 'lose',
    'pay', 'meet', 'include', 'continue', 'set', 'learn',
    'change', 'lead', 'understand', 'watch', 'follow', 'stop',
    'create', 'speak', 'read', 'allow', 'add', 'spend',
    'grow', 'open', 'walk', 'win', 'offer', 'remember',
    'love', 'consider', 'appear', 'buy', 'wait', 'serve',
    'die', 'send', 'expect', 'build', 'stay', 'fall',
    'cut', 'reach', 'kill', 'remain',
}

# Extra stopwords specific to job-description boilerplate, applied on top of
# the general STOPWORDS when extracting "interesting" JD keywords — strips out
# generic ATS/recruiting filler so what's left is the actual role-specific
# vocabulary worth comparing against a resume.
JD_STOPWORDS = {
    'required', 'preferred', 'responsibilities', 'qualifications',
    'ability', 'team', 'work', 'looking', 'role', 'position',
    'company', 'including', 'must', 'strong', 'excellent',
    'good', 'years', 'experience', 'working', 'knowledge',
    'understanding', 'skills', 'etc', 'well', 'related',
    'requirements', 'description', 'candidate', 'ideal',
    'opportunity', 'join', 'apply', 'please', 'submit',
    'resume', 'cover', 'letter', 'salary', 'benefits',
    'equal', 'employer', 'diversity',
}

SECTION_HEADERS = {
    'education': [
        'education', 'academic background', 'academic qualifications',
        'educational qualifications', 'academic history', 'degrees',
        'educational background',
        # German — German-language CVs are extremely common for the DE job
        # market this app targets, and the original (English-only) header
        # list caused every section to be reported "missing" for them,
        # tanking scores by ~20pts regardless of actual CV quality.
        'ausbildung', 'akademischer werdegang', 'bildung',
        'schulische ausbildung', 'studium', 'hochschulbildung',
    ],
    'experience': [
        'experience', 'work experience', 'professional experience',
        'employment history', 'work history', 'career history',
        'professional background', 'employment',
        'berufserfahrung', 'praktische erfahrung', 'werdegang',
        'beruflicher werdegang', 'arbeitserfahrung', 'tätigkeiten',
        'praxiserfahrung',
    ],
    'skills': [
        'skills', 'technical skills', 'core competencies', 'competencies',
        'key skills', 'areas of expertise', 'proficiencies',
        'technologies', 'tools and technologies',
        'kenntnisse', 'fähigkeiten', 'fertigkeiten', 'kompetenzen',
        'technische kenntnisse', 'fachkenntnisse', 'qualifikationen',
        'edv-kenntnisse', 'sprachen und kenntnisse',
    ],
    'projects': [
        'projects', 'personal projects', 'academic projects',
        'key projects', 'notable projects', 'project experience',
        'side projects',
        'projekte', 'persönliche projekte', 'studienprojekte',
        'abschlussprojekt', 'projektarbeiten',
    ],
    'summary': [
        'summary', 'professional summary', 'objective', 'career objective',
        'profile', 'about me', 'career summary', 'professional profile',
        'about', 'overview',
        'zusammenfassung', 'profil', 'über mich', 'kurzprofil',
        'persönliches profil', 'werdegang im überblick', 'ziel',
        'berufsziel',
    ],
    'certifications': [
        'certifications', 'certificates', 'professional certifications',
        'licenses', 'accreditations', 'training',
        'zertifikate', 'zertifizierungen', 'qualifikationen',
        'weiterbildungen', 'lizenzen', 'fortbildungen', 'kurse',
    ],
    'contact': [
        'contact', 'contact information', 'contact details',
        'personal information', 'personal details',
        'kontakt', 'kontaktdaten', 'kontaktinformationen',
        'persönliche daten', 'persönliche angaben',
    ],
    # German CVs commonly carry a dedicated languages section ("Sprachen")
    # that has no real English-CV equivalent in the original rubric — added
    # as its own bucket so it doesn't get mis-bucketed or ignored outright.
    'languages': [
        'languages', 'language skills', 'sprachen', 'sprachkenntnisse',
    ],
}

ACTION_VERBS = [
    'led', 'developed', 'managed', 'implemented', 'designed',
    'built', 'created', 'improved', 'increased', 'reduced',
    'optimized', 'launched', 'delivered', 'architected', 'mentored',
    'coordinated', 'established', 'streamlined', 'automated',
    'collaborated', 'maintained', 'resolved', 'analyzed',
    'engineered', 'deployed', 'integrated', 'migrated',
    'refactored', 'spearheaded', 'initiated', 'executed',
    # German equivalents (infinitive/participle forms commonly seen in
    # German CV bullet points)
    'geleitet', 'entwickelt', 'gemanagt', 'implementiert', 'entworfen',
    'gebaut', 'erstellt', 'verbessert', 'erhöht', 'reduziert',
    'optimiert', 'eingeführt', 'geliefert', 'konzipiert', 'betreut',
    'koordiniert', 'aufgebaut', 'automatisiert', 'realisiert',
    'umgesetzt', 'konstruiert', 'validiert', 'analysiert', 'integriert',
    'durchgeführt', 'gestaltet', 'erweitert', 'evaluiert',
]

DEGREE_TERMS = [
    'bachelor', 'master', 'phd', 'doctorate', 'associate',
    r'b\.s\.', r'b\.a\.', r'm\.s\.', r'm\.a\.', 'mba', r'b\.tech',
    r'm\.tech', r'b\.e\.', r'm\.e\.', 'bsc', 'msc', 'bca', 'mca',
    'diploma', 'degree', 'engineering', 'computer science',
    # German
    'b\.eng', 'm\.eng', 'diplom', 'fachabitur', 'abitur',
    'maschinenbau', 'mechatronik', 'informatik', 'elektrotechnik',
    'ingenieurwissenschaften', 'wirtschaftsingenieurwesen',
]

INSTITUTION_TERMS = [
    'university', 'college', 'institute', 'school', 'academy',
    'universität', 'universitaet', 'hochschule', 'fachhochschule',
    'technische universität', 'fakultät', 'akademie',
]

PROJECT_TECH_TERMS = [
    'built with', 'using', 'technologies', 'tech stack',
    'developed using', 'implemented in',
    # German
    'umgesetzt mit', 'implementiert in', 'technologien', 'mit hilfe von',
    'entwickelt mit', 'realisiert mit', 'auf basis von',
]
