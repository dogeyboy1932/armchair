"""
Assign engineering category probability distributions to course topics using Gemini.
Each topic gets scored across 8 predefined categories that sum to 1.0.
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


_SYSTEM = (
    "You are an engineering curriculum expert. Given an engineering topic and its definition, "
    "assign a probability distribution over exactly 8 engineering categories. "
    "Probabilities must sum to 1.0. Be precise.\n\n"
    "Categories:\n"
    "- Mechanics: dynamics, statics, kinematics, structural mechanics, vibrations, solid mechanics\n"
    "- Thermodynamics: heat transfer, energy systems, entropy, combustion, thermochemistry\n"
    "- Electrical: circuits, electronics, electromagnetism, signals, power systems, semiconductors\n"
    "- Fluids: fluid mechanics, aerodynamics, hydraulics, flow analysis, turbulence\n"
    "- Materials: material science, manufacturing, metallurgy, polymers, composites\n"
    "- Mathematics: calculus, linear algebra, numerical methods, differential equations, statistics\n"
    "- Chemistry: general chemistry, physical chemistry, reactions, molecular structure, stoichiometry\n"
    "- Systems: control systems, signal processing, feedback, system dynamics, optimization\n\n"
    'Return ONLY raw valid JSON with no markdown, no code blocks, no backticks: '
    '{"Mechanics":0.0,"Thermodynamics":0.0,"Electrical":0.0,'
    '"Fluids":0.0,"Materials":0.0,"Mathematics":0.0,"Chemistry":0.0,"Systems":0.0}'
)

def _normalize(raw: dict) -> dict:
    total = sum(raw.get(c, 0.0) for c in CATEGORIES)
    if total <= 0:
        raise ValueError("LLM returned all-zero category distribution")
    return {c: raw.get(c, 0.0) / total for c in CATEGORIES}


def label_topic(course_id: str, topic_text: str, definition: str,
                api_key: str | None = None, client=None) -> dict:
    """Return a normalized category distribution for one topic. Raises on failure."""
    user_msg = f'Topic: "{course_id}: {topic_text}"\nDefinition: "{definition[:600]}"'
    _c = client or _get_client(api_key)
    response = _c.models.generate_content(
        model=config.CATEGORY_LABEL_MODEL,
        contents=user_msg,
        config=types.GenerateContentConfig(
            system_instruction=_SYSTEM,
            max_output_tokens=200,
        ),
    )
    text = response.text.strip()
    start, end = text.find('{'), text.rfind('}') + 1
    if start == -1 or end <= start:
        raise ValueError(f"LLM returned invalid JSON for topic '{topic_text}': {text[:200]}")
    return _normalize(json.loads(text[start:end]))


def label_topics_batch(
    topics: list[tuple[str, str, str]],
) -> list[dict]:
    """
    Label a list of (course_id, topic_text, definition) tuples.
    Returns list of dicts with keys: course_id, topic_text, categories.
    """
    results = []
    for course_id, topic_text, definition in topics:
        cats = label_topic(course_id, topic_text, definition)
        results.append({
            "course_id":  course_id,
            "topic_text": topic_text,
            "categories": cats,
        })
    return results
