"""
Pure domain logic for the FAQ builder.

Nothing in this module touches Flask, MongoDB, or the network, so every
function here can be unit tested with plain inputs and outputs.
"""
import math
import re
from collections import Counter
from datetime import datetime, timezone

WORD_RE = re.compile(r"[a-z0-9]+")
SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+")

# Common words that carry no meaning for matching a question to a passage.
# static/js/app.js keeps a copy of this list for highlighting; keep them in sync.
STOPWORDS = frozenset("""
a an the and or but if then else of to in on at by for with from as is are was
were be been being do does did doing can could should would will shall may might
must i you he she it we they me my your our their this that these those there
here what which who whom whose when where why how not no yes so than too very
just about into over under again once all any both each few more most other some
such only own same up down out off also its am have has had get got
s t d ll re ve m don doesn didn isn aren wasn weren won can't
""".split())


def now_iso():
    """Current UTC time as an ISO-8601 string (sortable as text)."""
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def stem(word):
    """Very small stemmer: 'filters' -> 'filter', but 'glass' stays 'glass'."""
    if len(word) > 3 and word.endswith("s") and not word.endswith("ss"):
        return word[:-1]
    return word


def tokenize(text):
    """Lowercase, split into words, drop stopwords, stem."""
    return [stem(w) for w in WORD_RE.findall(text.lower()) if w not in STOPWORDS]


def normalize_question(question):
    """
    Canonical form used to detect repeated questions.
    'How do I RESET it?' and 'how do i reset it' normalize the same.
    """
    return " ".join(WORD_RE.findall(question.lower()))


def chunk_document(text, target_chars=700):
    """
    Split a document into passages of roughly target_chars characters.

    Short paragraphs (like headings) are merged with the paragraphs that
    follow them; very long paragraphs are split on sentence boundaries.
    """
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    chunks = []
    buffer = ""

    def flush():
        nonlocal buffer
        if buffer:
            chunks.append(buffer)
            buffer = ""

    for para in paragraphs:
        if len(para) > target_chars:
            flush()
            for sentence in SENTENCE_SPLIT_RE.split(para):
                if buffer and len(buffer) + len(sentence) + 1 > target_chars:
                    flush()
                buffer = f"{buffer} {sentence}".strip()
            flush()
        elif buffer and len(buffer) + len(para) + 2 > target_chars:
            flush()
            buffer = para
        else:
            buffer = f"{buffer}\n\n{para}" if buffer else para
    flush()
    return chunks


def retrieve(question, chunks, k=3):
    """
    Rank chunks by keyword relevance to the question (a small TF-IDF).

    Returns up to k dicts {index, text, score}, best first. Chunks that share
    no meaningful words with the question are left out.
    """
    q_terms = set(tokenize(question))
    if not q_terms or not chunks:
        return []

    chunk_counts = [Counter(tokenize(c)) for c in chunks]
    n = len(chunks)
    results = []
    for i, counts in enumerate(chunk_counts):
        score = 0.0
        for term in q_terms:
            tf = counts.get(term, 0)
            if tf:
                df = sum(1 for c in chunk_counts if term in c)
                idf = math.log((n + 1) / (df + 1)) + 1
                score += idf * (1 + math.log(tf))
        if score > 0:
            results.append({"index": i, "text": chunks[i], "score": round(score, 3)})

    results.sort(key=lambda r: (-r["score"], r["index"]))
    return results[:k]


def extractive_answer(question, passages, max_sentences=2):
    """
    Fallback answer that needs no AI: pick the sentences from the best
    passage that share the most words with the question.
    Returns None if there is nothing relevant.
    """
    if not passages:
        return None
    q_terms = set(tokenize(question))
    sentences = [
        s.strip()
        for line in passages[0]["text"].splitlines()
        for s in SENTENCE_SPLIT_RE.split(line)
        if len(s.split()) >= 4          # skip headings like "Factory reset"
    ]
    scored = [(len(q_terms & set(tokenize(s))), i, s) for i, s in enumerate(sentences)]
    best = sorted((t for t in scored if t[0] > 0), key=lambda t: (-t[0], t[1]))[:max_sentences]
    if not best:
        return None
    best.sort(key=lambda t: t[1])  # restore document order so it reads naturally
    return " ".join(s for _, _, s in best)


SYSTEM_PROMPT = (
    "You answer customer questions about a product using only the documentation "
    "passages provided. Reply in 1 to 4 plain sentences with no markdown, no headings, "
    "and no preamble. Do not invent details that are not in the passages. "
    "If the passages do not contain the answer, reply with exactly: NOT_IN_DOC"
)


def build_prompt(doc_title, question, passages):
    """Return (system, user) prompt strings for a chat model."""
    numbered = "\n\n".join(f"[{n}] {p['text']}" for n, p in enumerate(passages, start=1))
    user = (
        f"Document: {doc_title}\n\n"
        f"Passages:\n{numbered}\n\n"
        f"Question: {question}"
    )
    return SYSTEM_PROMPT, user
