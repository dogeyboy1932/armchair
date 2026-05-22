"""
Single-pass course analysis using one LLM call.

The LLM produces everything the stack needs: a clean course description,
learning objectives, topic names + definitions, and 8-category distributions
per topic. The stack (chunking, embedding, scoring, graph) consumes this
output directly — no further LLM calls during ingest.

extract_topics() and label_topic() are kept for standalone scripts
(label_categories.py, etc.) but are NOT called during ingest.
"""
import json
from google import genai
from google.genai import types
import config
from scoring.category_scorer import CATEGORIES

_client: genai.Client | None = None


def _get_client(api_key: str | None = None) -> genai.Client:
    global _client
    if api_key:
        return genai.Client(api_key=api_key)
    if _client is None:
        _client = genai.Client(api_key=config.GEMINI_API_KEY)
    return _client


# ── System prompts for standalone functions (kept for scripts) ────────────────

_EXTRACT_SYSTEM = (
    "You are a curriculum analyst. Given raw syllabus text for an engineering or CS course, "
    "extract the distinct academic topics covered in the course.\n\n"
    "Return ONLY raw valid JSON with no markdown, no code blocks, no backticks:\n"
    '{"topics": [{"name": "topic name", "description": "one sentence: what this topic covers technically"}, ...]}\n\n'
    "Rules:\n"
    "- Extract 5–20 meaningful academic topics (concepts, methods, theories)\n"
    "- Each name must be a concise noun phrase: 'Laplace Transforms', 'Consensus Mechanisms'\n"
    "- Descriptions: exactly 1 technical sentence — what the topic IS, not how it is taught\n"
    "- Skip all logistics: grading, office hours, schedules, policies, instructor info\n"
    "- If there is a week-by-week or module schedule, extract the academic subjects listed\n"
    "- If there is a bullet-point topic list, use it directly"
)

# ── One giant prompt for ingest ───────────────────────────────────────────────

_CAT_SCHEMA = (
    '{"Mechanics":0.0,"Thermodynamics":0.0,"Electrical":0.0,'
    '"Fluids":0.0,"Materials":0.0,"Mathematics":0.0,"Chemistry":0.0,"Systems":0.0}'
)

_ANALYZE_SYSTEM = f"""You are an expert engineering curriculum analyst. Given raw syllabus text, \
produce a complete structured analysis of the course in a single pass. Your output is the \
authoritative source of truth — the scoring engine, knowledge graph, and semantic matching \
system will be built entirely from what you return.

Produce ALL of the following in one JSON response:

1. DESCRIPTION — A precise 2-3 sentence technical summary of what the course covers and why it matters. \
No fluff. Describe the intellectual content, not the logistics.

2. OBJECTIVES — 3-6 concrete learning outcomes. Each must be a full sentence starting with a verb \
("Analyze...", "Derive...", "Apply..."). These define what a student can DO after the course.

3. TOPICS — Every meaningful academic topic covered. For each topic:
   - name: a concise noun phrase ("Laplace Transforms", "Euler-Lagrange Equations")
   - description: exactly 1 technical sentence — what the topic IS, the mathematical/scientific content
   - categories: probability distribution over 8 engineering domains (must sum to 1.0):
       Mechanics      — dynamics, statics, kinematics, vibrations, structural mechanics
       Thermodynamics — heat transfer, energy systems, entropy, combustion, thermochemistry
       Electrical     — circuits, electronics, electromagnetism, signals, semiconductors
       Fluids         — fluid mechanics, aerodynamics, hydraulics, flow analysis, turbulence
       Materials      — material science, manufacturing, metallurgy, polymers, composites
       Mathematics    — calculus, linear algebra, numerical methods, differential equations
       Chemistry      — general chemistry, physical chemistry, reactions, stoichiometry
       Systems        — control systems, signal processing, feedback, system dynamics
   - tags: 5-10 precise buzzwords that bridge this topic to equivalent concepts in other
     engineering or CS domains. These are used for cross-course matching — a student searching
     "RLC circuit" should find ME340's spring-mass system because both share "second-order-ode".
     Format: lowercase hyphenated phrases, 2-4 words each.
     GOOD tags bridge domains — both RLC circuits AND spring-mass-dampers get "second-order-ode",
     "natural-frequency", "damped-oscillation", "characteristic-equation", "resonance".
     More examples: "eigenvalue-problem", "fourier-transform", "laplace-transform",
     "conservation-of-energy", "boundary-value-problem", "state-space-model",
     "feedback-control", "wave-propagation", "thermal-resistance", "stress-strain",
     "dynamic-programming", "gradient-descent", "phase-equilibrium", "transfer-function".
     BAD tags are too generic: "analysis", "method", "theory", "modeling", "equations".
     BAD tags are too domain-locked: "kirchhoffs-law" (only circuits), "hookes-law" (only solids).
     PREFER tags that a course in a DIFFERENT domain would legitimately also use.

Topic rules:
- Extract 5–20 topics. Skip all logistics (grading, policies, schedules, office hours).
- If a week-by-week schedule exists, extract the academic subjects listed.
- Assign non-zero weight to the 2-3 most relevant categories per topic. Be specific, not uniform.

Return ONLY raw valid JSON — no markdown, no code fences, no explanation:
{{
  "description": "...",
  "objectives": ["...", "..."],
  "topics": [
    {{
      "name": "...",
      "description": "...",
      "categories": {_CAT_SCHEMA},
      "tags": ["...", "..."]
    }}
  ]
}}"""


def analyze_course(course_id: str, course_name: str, text: str, client) -> dict:
    """
    ONE LLM call. Returns everything the ingest pipeline needs:
    {
      "description": str,
      "objectives":  [str, ...],
      "topics": [
        {"name": str, "description": str, "categories": {cat: float, ...}},
        ...
      ]
    }
    Raises on any failure — no silent fallbacks.
    """
    prompt = f"Course ID: {course_id}\nCourse Name: {course_name}\n\nSyllabus text:\n{text[:7000]}"
    response = client.models.generate_content(
        model=config.CATEGORY_LABEL_MODEL,
        contents=prompt,
        config=types.GenerateContentConfig(
            system_instruction=_ANALYZE_SYSTEM,
            max_output_tokens=4096,
            thinking_config=types.ThinkingConfig(thinking_budget=0),
        ),
    )
    raw = response.text.strip()
    start, end = raw.find('{'), raw.rfind('}') + 1
    if start == -1 or end <= start:
        raise ValueError(f"LLM returned invalid JSON: {raw[:300]}")
    data = json.loads(raw[start:end])

    description = data.get('description', '').strip()
    objectives  = [o.strip() for o in data.get('objectives', []) if o.strip()]

    topics = []
    for t in data.get('topics', [])[:20]:
        name = t.get('name', '').strip()
        if not name:
            continue
        desc     = t.get('description', name).strip()
        raw_cats = t.get('categories', {})
        total    = sum(raw_cats.get(c, 0.0) for c in CATEGORIES)
        if total <= 0:
            raise ValueError(f"LLM returned all-zero categories for topic '{name}'")
        categories = {c: raw_cats.get(c, 0.0) / total for c in CATEGORIES}
        raw_tags = t.get('tags', [])
        tags = [str(tag).lower().strip() for tag in raw_tags if str(tag).strip()][:15]
        topics.append({"name": name, "description": desc, "categories": categories, "tags": tags})

    if not topics:
        raise ValueError("LLM returned no topics from syllabus text")
    if not description:
        raise ValueError("LLM returned no course description")

    return {"description": description, "objectives": objectives, "topics": topics}


# ── Standalone functions (used by offline scripts, not during ingest) ─────────

def extract_topics(course_id: str, course_name: str, text: str,
                   api_key: str | None = None, client=None) -> list[tuple[str, str]]:
    """Standalone topic extraction. Used by label_categories.py script."""
    prompt = f"Course: {course_name} ({course_id})\n\nSyllabus text:\n{text[:5000]}"
    _c = client or _get_client(api_key)
    response = _c.models.generate_content(
        model=config.LLM_EXPLAIN_MODEL,
        contents=prompt,
        config=types.GenerateContentConfig(
            system_instruction=_EXTRACT_SYSTEM,
            max_output_tokens=1024,
            thinking_config=types.ThinkingConfig(thinking_budget=0),
        ),
    )
    raw = response.text.strip()
    start, end = raw.find('{'), raw.rfind('}') + 1
    if start == -1 or end <= start:
        raise ValueError(f"LLM returned invalid JSON for topic extraction: {raw[:200]}")
    data = json.loads(raw[start:end])
    topics = [
        (t['name'].strip(), t.get('description', t['name']).strip())
        for t in data.get('topics', [])[:20]
        if t.get('name', '').strip()
    ]
    if not topics:
        raise ValueError("LLM returned no topics from syllabus text")
    return topics


# kept for backward compat with extract_and_label_topics callers
def extract_and_label_topics(course_id: str, course_name: str, text: str,
                              client) -> list[tuple[str, str, dict]]:
    result = analyze_course(course_id, course_name, text, client)
    return [(t['name'], t['description'], t['categories']) for t in result['topics']]
