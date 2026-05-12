"""
Generate natural-language explanations for non-obvious course connections using Gemini.
Called on pre-filtered top-K pairs after deterministic scoring identifies candidates.
"""
import json
from google import genai
from google.genai import types
import config



_SYSTEM = (
    "You are a curriculum mapping expert identifying non-obvious conceptual bridges between engineering courses.\n\n"
    "Be concise. Each field must be SHORT — 1-2 sentences max. No bullet points inside JSON values. No markdown.\n\n"
    "Return ONLY raw valid JSON with no markdown, no code blocks, no backticks:\n"
    '{"shared_math": "one sentence: the mathematical or structural pattern both courses share", '
    '"why_surprising": "one sentence: why this connection is not obvious", '
    '"analogy": "one concrete analogy in plain English, one sentence"}'
)


def explain_connection(
    course_a: str,
    topics_a: list[str],
    course_b: str,
    topics_b: list[str],
    sem_score: float,
    cat_jsd: float,
    client=None,
    api_key: str | None = None,
) -> dict:
    """
    Generate a plain-language explanation for a non-obvious course pair.

    course_a/b:  course IDs (e.g. "ME 340")
    topics_a/b:  up to 5 representative topic strings from each course
    sem_score:   calibrated semantic similarity [0,1]
    cat_jsd:     category Jensen-Shannon divergence [0,1]
    Returns: {"explanation": str, "analogy": str}
    """
    def fmt_topics(topics: list[str]) -> str:
        return "\n".join(f"  • {t}" for t in topics[:5]) if topics else "  (no topics available)"

    user_msg = (
        f"Course A: {course_a}\n"
        f"Representative topics:\n{fmt_topics(topics_a)}\n\n"
        f"Course B: {course_b}\n"
        f"Representative topics:\n{fmt_topics(topics_b)}\n\n"
        f"Semantic similarity score: {sem_score:.2f} (high = conceptually similar)\n"
        f"Category divergence:       {cat_jsd:.2f} (high = very different disciplines)\n"
        f"\nExplain why this cross-domain similarity is interesting and non-obvious."
    )

    if client is None:
        client = genai.Client(api_key=api_key or config.GEMINI_API_KEY)
    response = client.models.generate_content(
        model=config.LLM_EXPLAIN_MODEL,
        contents=user_msg,
        config=types.GenerateContentConfig(
            system_instruction=_SYSTEM,
            max_output_tokens=1024,
            thinking_config=types.ThinkingConfig(thinking_budget=0),
        ),
    )
    text = response.text.strip()
    start, end = text.find('{'), text.rfind('}') + 1
    if start == -1 or end <= start:
        raise ValueError(f"LLM returned invalid JSON: {text[:200]}")
    return json.loads(text[start:end])
