from app.services.verify import locate_quote


def test_normalized_quote_uses_pdf_text():
    page = "The State-of-the-Art method improves results."
    result = locate_quote([page], "the state of the art method improves results.")
    assert result["level"] == "normalized"
    assert result["quote"] == "The State-of-the-Art method improves results."
    assert result["quote"] in result["context"]


def test_normalized_quote_does_not_cross_paragraphs():
    pages = ["The method uses state-of-\n\nThe art system works separately."]
    assert locate_quote(pages, "state of the art system") is None


def test_normalized_quote_maps_unicode_expansion():
    page = "A ﬁne-grained result was reported."
    result = locate_quote([page], "fine grained result was reported.")
    assert result["quote"] == "A ﬁne-grained result was reported."
