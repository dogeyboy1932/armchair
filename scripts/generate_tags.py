"""
Use Gemini to fill in buzzword tags for every topic in a course JSON file.

Works with both export formats:
  - data/course_tags.json   (from export_course_tags.py — tags-only format)
  - data/courses_dump.json  (from dump_courses.py — full course format)

Sends ALL courses at once so the LLM assigns consistent cross-domain tags:
ME340's spring-mass-damper and ECE210's RLC circuit both get "second-order-ode"
because the LLM sees both simultaneously.

Run:
    python scripts/generate_tags.py
    python scripts/generate_tags.py --in data/courses_dump.json
    python scripts/generate_tags.py --dry-run
    python scripts/generate_tags.py --overwrite     # re-generate even if tags exist

Cost estimate: 1 Gemini Flash call ≈ $0.01–0.05
"""
import sys
import json
import argparse
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import config
from google import genai
from google.genai import types

_SYSTEM = """\
You are an engineering curriculum analyst generating buzzword tags for cross-course topic matching.

Given topics from multiple engineering and CS courses, assign 5-10 precise buzzword tags to each.
Tags surface non-obvious connections between topics in DIFFERENT courses.

THE KEY RULE: Topics from different domains that share the same underlying math or physics
MUST share the same tags. For example:
  - ME340 "Spring-Mass-Damper" and ECE210 "RLC Circuits" both get:
    "second-order-ode", "natural-frequency", "damped-oscillation", "characteristic-equation"
  - Any heat conduction topic and any mass diffusion topic both get:
    "parabolic-pde", "boundary-value-problem", "fourier-number"

Tag format rules:
  - Lowercase, hyphenated phrases, 2-4 words (e.g. "second-order-ode", "eigenvalue-problem")
  - GOOD cross-domain tags: "laplace-transform", "fourier-transform", "state-space-model",
    "feedback-control", "transfer-function", "conservation-of-energy",
    "variational-principle", "finite-element-method", "dimensionless-number",
    "stability-analysis", "phase-equilibrium", "stress-strain", "dynamic-programming",
    "gradient-descent", "monte-carlo", "wave-propagation", "continuum-mechanics",
    "coupled-equations", "superposition-principle", "matrix-methods"
  - GOOD specific-technology tags (when exact): "python", "matlab", "solidworks",
    "ansys", "arduino", "tensorflow", "finite-differences"
  - BAD — too generic: "analysis", "method", "theory", "modeling", "equations"
  - BAD — too domain-locked (only one field uses the name): "kirchhoffs-law",
    "newtons-second-law", "hookes-law"

Return ONLY raw valid JSON — no markdown, no explanation:
{
  "COURSE_ID": {
    "Exact Topic Name": ["tag1", "tag2", "tag3", ...]
  }
}
"""


def _iter_topics(courses: dict):
    """Yield (course_id, topic_dict) for both file formats."""
    for course_id, value in courses.items():
        if isinstance(value, list):
            # tags-only format: {course_id: [{topic, description, categories, tags}, ...]}
            for t in value:
                yield course_id, t
        elif isinstance(value, dict):
            # full dump format: {course_id: {topics: [{name, description, ...}, ...], ...}}
            for t in value.get("topics", []):
                # normalize to common shape
                yield course_id, {
                    "topic":       t.get("name", t.get("topic", "")),
                    "description": t.get("description", ""),
                    "categories":  t.get("categories", {}),
                    "tags":        t.get("tags", []),
                }


def _build_prompt(courses: dict, overwrite: bool):
    lines = []
    to_tag: list[tuple[str, str]] = []
    skipped: list[tuple[str, str]] = []

    # Group by course_id
    grouped: dict = {}
    for course_id, t in _iter_topics(courses):
        grouped.setdefault(course_id, []).append(t)

    for course_id, topics in sorted(grouped.items()):
        course_lines = []
        for t in topics:
            if t["tags"] and not overwrite:
                skipped.append((course_id, t["topic"]))
                continue
            to_tag.append((course_id, t["topic"]))
            desc = t.get("description", "").strip()
            cats = t.get("categories", {})
            top_cats = ", ".join(
                f"{k}: {v:.2f}" for k, v in
                sorted(cats.items(), key=lambda x: x[1], reverse=True)[:3]
                if v > 0.05
            )
            course_lines.append(
                f'  Topic: "{t["topic"]}"\n'
                f'  Description: {desc[:200] or "(none)"}\n'
                f'  Primary domains: {top_cats or "unknown"}'
            )
        if course_lines:
            lines.append(f'COURSE: {course_id}\n' + "\n\n".join(course_lines))

    prompt = "\n\n" + ("\n\n---\n\n".join(lines))
    return prompt, skipped, to_tag


def _apply_tags(courses: dict, tag_map: dict) -> int:
    """Write generated tags back into the courses dict. Returns count updated."""
    updated = 0
    for course_id, value in courses.items():
        course_tags = tag_map.get(course_id, {})
        if not course_tags:
            continue

        if isinstance(value, list):
            # tags-only format
            for t in value:
                if t["topic"] in course_tags:
                    t["tags"] = [str(x).lower().strip() for x in course_tags[t["topic"]] if str(x).strip()][:15]
                    updated += 1
        elif isinstance(value, dict):
            # full dump format
            for t in value.get("topics", []):
                key = t.get("name", t.get("topic", ""))
                if key in course_tags:
                    t["tags"] = [str(x).lower().strip() for x in course_tags[key] if str(x).strip()][:15]
                    updated += 1
    return updated


def main():
    parser = argparse.ArgumentParser(description="LLM-generate tags for all topics")
    parser.add_argument("--in",       dest="infile", default="data/courses_dump.json",
                        help="Input JSON (default: data/courses_dump.json)")
    parser.add_argument("--dry-run",  action="store_true")
    parser.add_argument("--overwrite", action="store_true",
                        help="Re-generate even for topics that already have tags")
    args = parser.parse_args()

    if not config.GEMINI_API_KEY:
        print("ERROR: GEMINI_API_KEY not set in .env")
        sys.exit(1)

    in_path = Path(args.infile)
    if not in_path.exists():
        print(f"ERROR: {in_path} not found.")
        print("Run:  python scripts/dump_courses.py  (full export)")
        print("  or: python scripts/export_course_tags.py  (tags-only export)")
        sys.exit(1)

    with open(in_path) as f:
        courses: dict = json.load(f)

    prompt, skipped, to_tag = _build_prompt(courses, args.overwrite)

    print(f"Topics to tag:    {len(to_tag)}")
    print(f"Topics skipped (already tagged): {len(skipped)}")
    print(f"Prompt size:      ~{len(prompt) // 4} tokens")

    if args.dry_run:
        print("\n--- DRY RUN: first 600 chars of prompt ---")
        print(prompt[:600])
        return

    if not to_tag:
        print("Nothing to do — all topics already have tags. Use --overwrite to regenerate.")
        return

    print("\nCalling Gemini… (may take 15-45 seconds for a full 33-course dump)")
    client = genai.Client(api_key=config.GEMINI_API_KEY)
    response = client.models.generate_content(
        model=config.CATEGORY_LABEL_MODEL,
        contents=prompt,
        config=types.GenerateContentConfig(
            system_instruction=_SYSTEM,
            max_output_tokens=8192,
            thinking_config=types.ThinkingConfig(thinking_budget=0),
        ),
    )
    raw = response.text.strip()
    start, end = raw.find('{'), raw.rfind('}') + 1
    if start == -1 or end <= start:
        print(f"ERROR: LLM returned invalid JSON:\n{raw[:400]}")
        sys.exit(1)

    tag_map: dict = json.loads(raw[start:end])
    updated = _apply_tags(courses, tag_map)

    with open(in_path, "w") as f:
        json.dump(courses, f, indent=2)

    print(f"✓ Updated {updated} topics with tags → {in_path}")
    print()
    print("Review / edit the file, then run:")
    print("  python scripts/load_courses.py")


if __name__ == "__main__":
    main()
