from keybert import KeyBERT

_kw_model: KeyBERT | None = None


def get_kw_model() -> KeyBERT:
    global _kw_model
    if _kw_model is None:
        from pipeline.encoder import get_model   # reuse SciNCL — no second download
        _kw_model = KeyBERT(model=get_model())
    return _kw_model


def extract_keyphrases(text: str, top_n: int = 5) -> list[str]:
    """Return top_n n-gram keyphrases extracted by KeyBERT + SciNCL."""
    try:
        kws = get_kw_model().extract_keywords(
            text,
            keyphrase_ngram_range=(1, 2),
            stop_words='english',
            top_n=top_n,
            use_mmr=True,
            diversity=0.5,
        )
        return [kw for kw, _ in kws]
    except Exception:
        return []
