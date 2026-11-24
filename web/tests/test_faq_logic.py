"""Unit tests for the pure functions in faq_logic.py (black-box first)."""
from faq_logic import (build_prompt, chunk_document, extractive_answer,
                       normalize_question, retrieve, stem, tokenize)

MANUAL = """Factory reset

To erase all settings, press and hold the center button for 15 seconds until the screen shows Reset.

Wi-Fi

The thermostat only supports 2.4 GHz networks. 5 GHz networks will not appear.

Warranty

The product includes a 2-year limited warranty covering defects in materials."""


def test_stem_plural_but_not_double_s():
    assert stem("filters") == "filter"
    assert stem("glass") == "glass"
    assert stem("gas") == "gas"          # too short to stem


def test_tokenize_drops_stopwords_and_lowercases():
    assert tokenize("How do I reset THE Thermostat?") == ["reset", "thermostat"]


def test_tokenize_empty():
    assert tokenize("") == []


def test_normalize_question_ignores_case_and_punctuation():
    assert normalize_question("How do I RESET it?!") == normalize_question("how do i reset it")


def test_chunk_merges_short_paragraphs():
    chunks = chunk_document("Heading\n\nShort body text.", target_chars=700)
    assert chunks == ["Heading\n\nShort body text."]


def test_chunk_splits_at_target_size():
    paras = "\n\n".join(["word " * 30] * 10)  # ten ~150-char paragraphs
    chunks = chunk_document(paras, target_chars=400)
    assert len(chunks) > 1
    assert all(len(c) <= 400 for c in chunks)


def test_chunk_splits_one_giant_paragraph_by_sentence():
    giant = " ".join(f"Sentence number {i} is here." for i in range(100))
    chunks = chunk_document(giant, target_chars=300)
    assert len(chunks) > 1
    assert "".join(chunks).replace(" ", "") == giant.replace(" ", "")


def test_chunk_empty_document():
    assert chunk_document("   \n\n  ") == []


def test_retrieve_ranks_relevant_section_first():
    chunks = chunk_document(MANUAL, target_chars=150)
    results = retrieve("How long is the warranty?", chunks)
    assert results
    assert "warranty" in results[0]["text"].lower()


def test_retrieve_returns_nothing_for_unrelated_question():
    chunks = chunk_document(MANUAL, target_chars=150)
    assert retrieve("What color is the sky on Mars?", chunks) == []


def test_retrieve_respects_k():
    chunks = ["reset one", "reset two", "reset three", "reset four"]
    assert len(retrieve("reset", chunks, k=2)) == 2


def test_extractive_answer_picks_matching_sentence():
    passages = [{"index": 0, "text": "Unrelated intro. Hold the button for 15 seconds to reset. Other stuff.",
                 "score": 1}]
    assert extractive_answer("How do I reset?", passages) == "Hold the button for 15 seconds to reset."


def test_extractive_answer_none_without_passages():
    assert extractive_answer("anything", []) is None


def test_build_prompt_numbers_passages_and_includes_question():
    system, user = build_prompt("Guide", "Why?", [{"text": "A"}, {"text": "B"}])
    assert "NOT_IN_DOC" in system
    assert "[1] A" in user and "[2] B" in user
    assert user.endswith("Question: Why?")
