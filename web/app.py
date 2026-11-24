"""
FAQ Builder -- Flask REST API + single-page UI.

Resources
  /api/docs                 GET list, POST create
  /api/docs/<id>            GET, PUT, DELETE
  /api/docs/<id>/faqs       GET list, POST ask a question (creates a FAQ entry)
  /api/faqs/<id>            GET, PUT, DELETE
  /api/faqs/<id>/regenerate POST  (re-ask the AI for an existing question)
  /api/health               GET

Routes only parse requests and format responses. The real work lives in
faq_logic.py (pure functions), ai_providers.py (AI shim) and db.py (storage).
"""
import logging

from flask import Flask, jsonify, render_template, request, url_for

from ai_providers import ExtractiveProvider, ProviderError, build_provider
from config import Config
from faq_logic import chunk_document, normalize_question, now_iso, retrieve
from validation import validate_document, validate_faq_update, validate_question_payload

NOT_FOUND_ANSWER = "The document doesn't cover this question."
SOURCE_PREVIEW_CHARS = 600


def create_app(repo=None, provider=None, config=None):
    cfg = config or Config()
    app = Flask(__name__)
    app.logger.setLevel(logging.INFO)

    if repo is None:
        from db import MongoRepository  # imported here so tests don't need pymongo
        repo = MongoRepository(cfg.MONGO_URL)
    if provider is None:
        provider = build_provider(cfg)
    fallback = ExtractiveProvider()

    # ---------- helpers ----------
    def error(message, status, details=None):
        body = {"error": message}
        if details:
            body["details"] = details
        return jsonify(body), status

    def json_body():
        body = request.get_json(silent=True)
        return body if isinstance(body, dict) else None

    def public_doc(doc):
        return {k: v for k, v in doc.items() if k != "chunks"}

    def answer_question(doc, question):
        """Run retrieval + the AI provider. Returns (fields_for_faq, notice)."""
        chunks = doc.get("chunks", [])
        passages = retrieve(question, chunks, k=4)
        if not passages and not provider.needs_keyword_match:
            # No keyword overlap (e.g. synonyms): give the model the opening passages
            passages = [{"index": i, "text": c, "score": 0} for i, c in enumerate(chunks[:4])]

        used, notice = provider, None
        try:
            result = provider.answer(question, passages, doc["title"])
        except ProviderError as exc:
            app.logger.warning("AI provider failed, using keyword fallback: %s", exc)
            used = fallback
            result = fallback.answer(question, passages, doc["title"])
            notice = "The AI service didn't respond, so this answer uses keyword matching instead."

        found = result["found"]
        sources = [
            {"index": p["index"], "text": p["text"][:SOURCE_PREVIEW_CHARS], "score": p["score"]}
            for p in passages if p["score"] > 0
        ] if found else []
        return {
            "answer": result["answer"] if found else NOT_FOUND_ANSWER,
            "found": found,
            "sources": sources,
            "provider": used.name,
            "model": result.get("model"),
        }, notice

    # ---------- pages ----------
    @app.get("/")
    def index():
        return render_template("index.html")

    @app.get("/api/health")
    def health():
        return jsonify({
            "status": "ok",
            "database": "ok" if repo.ping() else "unavailable",
            "provider": provider.info(),
        })

    # ---------- documents ----------
    @app.get("/api/docs")
    def list_docs():
        return jsonify(repo.list_docs())

    @app.post("/api/docs")
    def create_doc():
        body = json_body()
        if body is None:
            return error("Send a JSON object.", 400)
        clean, errors = validate_document(body)
        if errors:
            return error("Some fields need attention.", 400, errors)
        chunks = chunk_document(clean["content"])
        stamp = now_iso()
        doc = repo.create_doc({
            **clean,
            "preview": clean["content"][:160],
            "chunks": chunks,
            "chunk_count": len(chunks),
            "created_at": stamp,
            "updated_at": stamp,
        })
        response = jsonify(public_doc(doc))
        response.status_code = 201
        response.headers["Location"] = url_for("get_doc", doc_id=doc["id"])
        return response

    @app.get("/api/docs/<doc_id>")
    def get_doc(doc_id):
        doc = repo.get_doc(doc_id)
        return jsonify(public_doc(doc)) if doc else error("Document not found.", 404)

    @app.put("/api/docs/<doc_id>")
    def update_doc(doc_id):
        body = json_body()
        if body is None:
            return error("Send a JSON object.", 400)
        if not repo.get_doc(doc_id):
            return error("Document not found.", 404)
        clean, errors = validate_document(body)
        if errors:
            return error("Some fields need attention.", 400, errors)
        chunks = chunk_document(clean["content"])
        doc = repo.update_doc(doc_id, {
            **clean,
            "preview": clean["content"][:160],
            "chunks": chunks,
            "chunk_count": len(chunks),
            "updated_at": now_iso(),
        })
        return jsonify(public_doc(doc))

    @app.delete("/api/docs/<doc_id>")
    def delete_doc(doc_id):
        return ("", 204) if repo.delete_doc(doc_id) else error("Document not found.", 404)

    # ---------- FAQ entries ----------
    @app.get("/api/docs/<doc_id>/faqs")
    def list_faqs(doc_id):
        if not repo.get_doc(doc_id):
            return error("Document not found.", 404)
        return jsonify(repo.list_faqs(doc_id))

    @app.post("/api/docs/<doc_id>/faqs")
    def ask(doc_id):
        """
        Asking a question creates a FAQ resource. If the same question was
        already answered for this document, return the saved one (200)
        instead of calling the AI again.
        """
        body = json_body()
        if body is None:
            return error("Send a JSON object.", 400)
        doc = repo.get_doc(doc_id)
        if not doc:
            return error("Document not found.", 404)
        clean, errors = validate_question_payload(body)
        if errors:
            return error("Some fields need attention.", 400, errors)

        norm = normalize_question(clean["question"])
        existing = repo.find_faq_by_norm(doc_id, norm)
        if existing:
            return jsonify({"faq": existing, "cached": True, "notice": None}), 200

        if "answer" in clean:  # manual entry, no AI involved
            fields, notice = {"answer": clean["answer"], "found": True, "sources": [],
                              "provider": "manual", "model": None}, None
        else:
            fields, notice = answer_question(doc, clean["question"])

        stamp = now_iso()
        faq = repo.create_faq({
            "doc_id": doc_id,
            "question": clean["question"],
            "norm_question": norm,
            **fields,
            "pinned": False,
            "created_at": stamp,
            "updated_at": stamp,
        })
        response = jsonify({"faq": faq, "cached": False, "notice": notice})
        response.status_code = 201
        response.headers["Location"] = url_for("get_faq", faq_id=faq["id"])
        return response

    @app.get("/api/faqs/<faq_id>")
    def get_faq(faq_id):
        faq = repo.get_faq(faq_id)
        return jsonify(faq) if faq else error("FAQ entry not found.", 404)

    @app.put("/api/faqs/<faq_id>")
    def update_faq(faq_id):
        body = json_body()
        if body is None:
            return error("Send a JSON object.", 400)
        faq = repo.get_faq(faq_id)
        if not faq:
            return error("FAQ entry not found.", 404)
        clean, errors = validate_faq_update(body)
        if errors:
            return error("Some fields need attention.", 400, errors)
        if "question" in clean:
            clean["norm_question"] = normalize_question(clean["question"])
        if "answer" in clean and clean["answer"] != faq["answer"]:
            clean["provider"] = "edited"
            clean["found"] = True
        clean["updated_at"] = now_iso()
        return jsonify(repo.update_faq(faq_id, clean))

    @app.delete("/api/faqs/<faq_id>")
    def delete_faq(faq_id):
        return ("", 204) if repo.delete_faq(faq_id) else error("FAQ entry not found.", 404)

    @app.post("/api/faqs/<faq_id>/regenerate")
    def regenerate(faq_id):
        faq = repo.get_faq(faq_id)
        if not faq:
            return error("FAQ entry not found.", 404)
        doc = repo.get_doc(faq["doc_id"])
        if not doc:
            return error("Document not found.", 404)
        fields, notice = answer_question(doc, faq["question"])
        updated = repo.update_faq(faq_id, {**fields, "updated_at": now_iso()})
        return jsonify({"faq": updated, "cached": False, "notice": notice})

    # ---------- errors ----------
    @app.errorhandler(404)
    def not_found(_e):
        if request.path.startswith("/api/"):
            return error("No such endpoint.", 404)
        return render_template("index.html"), 404

    @app.errorhandler(405)
    def method_not_allowed(_e):
        return error(f"{request.method} isn't supported on {request.path}.", 405)

    @app.errorhandler(500)
    def server_error(_e):
        return error("Something went wrong on the server. Check `docker compose logs web`.", 500)

    try:
        from pymongo.errors import PyMongoError

        @app.errorhandler(PyMongoError)
        def database_down(exc):
            app.logger.error("Database error: %s", exc)
            return error("The database isn't reachable. Is the db container running?", 503)
    except ImportError:
        pass

    app.logger.info("AI provider: %s", provider.info())
    return app


if __name__ == "__main__":
    config = Config()
    create_app(config=config).run(host="0.0.0.0", port=5000, debug=config.DEBUG)
