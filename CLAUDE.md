# Armchair — Quick Context for Claude

A locally-runnable semantic similarity engine for 33 UIUC MechSE courses. Goal:
surface **non-obvious cross-domain connections** between course topics
(ME 340 spring-mass ↔ ECE 206 RLC circuit — same 2nd-order ODE, different domain).

**Authoritative docs (read these for anything substantive):**
- `README.md` — quick start + doc index
- `docs/ARCHITECTURE.md` — system design, file reference, scoring math, API, UI
- `deploy/free/README.md` — production deploy (Supabase + Aura + Fly) + CI/CD
- `deploy/legacy/` — quarantined local Docker stack + Oracle self-host path

## The one-liner you'll be asked about most

```
non_obvious_score = sem_score × category_jsd
final_score       = 0.4 × lex_score + 0.6 × sem_score
```

Math scores; LLM only explains. Gemini key lives in browser `localStorage` and is
sent as `X-Api-Key` — server never stores it.

## Research context

- Supervisor: Eliot Bethke (bethke2@illinois.edu)
- Goal: non-obvious matches spanning departments (fluids ↔ mechanics, electronics ↔ materials)
- The team wants clean, explained, non-obvious matches they can evaluate without reading score math
