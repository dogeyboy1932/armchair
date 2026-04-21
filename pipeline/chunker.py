import re
from collections import Counter

import nltk
nltk.download('stopwords', quiet=True)
_STOP = set(nltk.corpus.stopwords.words('english'))


def tokenize(text: str) -> list[str]:
    """Lowercase, keep alpha tokens > 2 chars, strip stopwords."""
    tokens = re.findall(r'\b[a-zA-Z][a-zA-Z0-9\-]{2,}\b', text.lower())
    return [t for t in tokens if t not in _STOP]


def chunk_course(course: dict, topic_defs: dict) -> tuple[list[dict], dict]:
    """
    Build chunk dicts and term counts for one course.

    course    — entry from mechse_syllabi.json
    topic_defs — {topic_key: definition_text}  (topic_definitions.json)

    Returns (chunks, term_counts)
      chunks      : list of {chunk_id, course_id, chunk_type, raw_text}
      term_counts : {term: count}  over the full course corpus
    """
    course_id   = course['id']
    course_name = course['name']
    chunks: list[dict] = []
    all_tokens: list[str] = []

    def _add(chunk_type: str, idx: int, text: str):
        safe_id = course_id.replace(' ', '_').replace('/', '_')
        chunks.append({
            'chunk_id':   f"{safe_id}__{chunk_type}__{idx}",
            'course_id':  course_id,
            'chunk_type': chunk_type,
            'raw_text':   text.strip(),
        })
        all_tokens.extend(tokenize(text))

    # ── 1. Topic chunks (enriched with definition where available) ──────────────
    for i, topic in enumerate(course.get('topics', [])):
        key        = f"{course_id}: {topic}"
        definition = topic_defs.get(key, '')
        text = (f"{course_name} [SEP] {topic}: {definition}"
                if definition else f"{course_name} [SEP] {topic}")
        _add('topic', i, text)

    # ── 2. Inline definition chunks (CHEM courses only) ─────────────────────────
    defs = course.get('definitions', [])
    if defs and defs[0].get('d_entry'):
        for i, (term, entry) in enumerate(
            zip(defs[0]['d_term'], defs[0]['d_entry'])
        ):
            _add('definition', i, f"{term}: {entry}")

    # ── 3. Course description ────────────────────────────────────────────────────
    desc = course.get('description', '')
    if len(desc) > 50:
        _add('description', 0, f"{course_name}: {desc}")

    # ── 4. Learning objectives ───────────────────────────────────────────────────
    objectives = course.get('objectives', [])
    if objectives:
        _add('objective', 0,
             f"{course_name} objectives: " + '. '.join(objectives))

    return chunks, dict(Counter(all_tokens))
