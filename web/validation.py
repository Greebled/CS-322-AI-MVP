"""
Input validation for the REST API. Each function returns (clean_data, errors)
where errors maps field name -> message the UI can show next to that field.
"""
TITLE_MAX = 120
CONTENT_MIN = 50
CONTENT_MAX = 50_000
QUESTION_MIN = 3
QUESTION_MAX = 300
ANSWER_MAX = 4_000


def _clean_str(payload, key):
    value = payload.get(key)
    return value.strip() if isinstance(value, str) else None


def validate_document(payload):
    errors, clean = {}, {}
    title = _clean_str(payload, "title")
    content = _clean_str(payload, "content")

    if not title:
        errors["title"] = "Give the document a title."
    elif len(title) > TITLE_MAX:
        errors["title"] = f"Keep the title under {TITLE_MAX} characters."
    else:
        clean["title"] = title

    if not content:
        errors["content"] = "Paste the document text."
    elif len(content) < CONTENT_MIN:
        errors["content"] = f"Paste at least {CONTENT_MIN} characters so there is something to answer from."
    elif len(content) > CONTENT_MAX:
        errors["content"] = f"Documents are limited to {CONTENT_MAX:,} characters."
    else:
        clean["content"] = content
    return clean, errors


def _check_question(question, errors):
    if not question:
        errors["question"] = "Type a question."
    elif len(question) < QUESTION_MIN:
        errors["question"] = "That question is too short to answer."
    elif len(question) > QUESTION_MAX:
        errors["question"] = f"Keep questions under {QUESTION_MAX} characters."


def _check_answer(answer, errors):
    if not answer:
        errors["answer"] = "The answer can't be empty."
    elif len(answer) > ANSWER_MAX:
        errors["answer"] = f"Keep answers under {ANSWER_MAX:,} characters."


def validate_question_payload(payload):
    """POST /api/docs/<id>/faqs: question required, answer optional (manual entry)."""
    errors, clean = {}, {}
    question = _clean_str(payload, "question")
    _check_question(question, errors)
    if not errors:
        clean["question"] = question
    if "answer" in payload:
        answer = _clean_str(payload, "answer")
        _check_answer(answer, errors)
        if "answer" not in errors:
            clean["answer"] = answer
    return clean, errors


def validate_faq_update(payload):
    """PUT /api/faqs/<id>: any of question, answer, pinned."""
    errors, clean = {}, {}
    allowed = {"question", "answer", "pinned"}
    unknown = set(payload) - allowed
    if unknown:
        errors["_"] = f"Unknown field(s): {', '.join(sorted(unknown))}"
    if not set(payload) & allowed:
        errors["_"] = "Send at least one of: question, answer, pinned."

    if "question" in payload:
        q = _clean_str(payload, "question")
        _check_question(q, errors)
        if "question" not in errors:
            clean["question"] = q
    if "answer" in payload:
        a = _clean_str(payload, "answer")
        _check_answer(a, errors)
        if "answer" not in errors:
            clean["answer"] = a
    if "pinned" in payload:
        if isinstance(payload["pinned"], bool):
            clean["pinned"] = payload["pinned"]
        else:
            errors["pinned"] = "pinned must be true or false."
    return clean, errors
