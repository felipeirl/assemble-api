from app.catalog.summary import TAGLINE_MAX_CHARS, tagline


def test_tagline_strips_section_heading_and_keeps_first_sentence():
    doc = {"bio": "Origin Warren Worthington III was born rich. His life changed."}
    assert tagline(doc, "en") == "Warren Worthington III was born rich."


def test_tagline_prefers_pt_br_translation_only_for_pt_br():
    doc = {
        "bio": "Storm controls the weather.",
        "translations": {"pt-BR": {"bio": "Tempestade controla o clima."}},
    }
    assert tagline(doc, "pt-BR") == "Tempestade controla o clima."
    assert tagline(doc, "en") == "Storm controls the weather."


def test_tagline_truncates_long_sentence_at_word_boundary():
    doc = {"bio": "word " * 100}
    result = tagline(doc, "en")
    assert result is not None and result.endswith("…") and len(result) <= TAGLINE_MAX_CHARS


def test_tagline_missing_bio_is_none():
    assert tagline({}, "en") is None
    assert tagline({"bio": "   "}, "pt-BR") is None
