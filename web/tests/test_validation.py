from validation import validate_document, validate_faq_update, validate_question_payload

GOOD_CONTENT = "x" * 60


def test_valid_document():
    clean, errors = validate_document({"title": "  Guide ", "content": GOOD_CONTENT})
    assert errors == {}
    assert clean["title"] == "Guide"


def test_document_missing_fields():
    _, errors = validate_document({})
    assert set(errors) == {"title", "content"}


def test_document_too_short_and_wrong_type():
    _, errors = validate_document({"title": 42, "content": "short"})
    assert "title" in errors and "content" in errors


def test_question_bounds():
    assert validate_question_payload({"question": "hi"})[1]["question"]
    assert validate_question_payload({"question": "q" * 301})[1]["question"]
    assert validate_question_payload({"question": "Is it waterproof?"})[1] == {}


def test_manual_answer_must_not_be_blank():
    _, errors = validate_question_payload({"question": "Is it waterproof?", "answer": "  "})
    assert "answer" in errors


def test_faq_update_rules():
    assert validate_faq_update({})[1]
    assert validate_faq_update({"color": "red"})[1]
    assert validate_faq_update({"pinned": "yes"})[1]["pinned"]
    clean, errors = validate_faq_update({"pinned": True})
    assert errors == {} and clean == {"pinned": True}
