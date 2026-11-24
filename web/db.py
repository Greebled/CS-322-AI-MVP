"""
MongoDB data-access layer. Routes never touch PyMongo directly -- they call
these methods, so tests can swap in an in-memory FakeRepo with the same
interface (see tests/fakes.py).

Collections:
  documents { title, content, preview, chunks[], chunk_count, created_at, updated_at }
  faqs      { doc_id, question, norm_question, answer, found, sources[],
              provider, model, pinned, created_at, updated_at }
"""
from bson import ObjectId
from bson.errors import InvalidId
from pymongo import MongoClient, ReturnDocument

SUMMARY_FIELDS = {"content": 0, "chunks": 0}


def _oid(value):
    try:
        return ObjectId(value)
    except (InvalidId, TypeError):
        return None


def _out(record):
    """Mongo record -> JSON-friendly dict with a string 'id'."""
    if record is None:
        return None
    record = dict(record)
    record["id"] = str(record.pop("_id"))
    return record


class MongoRepository:
    def __init__(self, url):
        self.client = MongoClient(url, serverSelectionTimeoutMS=3000)
        database = self.client.get_default_database(default="faqbuilder")
        self.documents = database.documents
        self.faqs = database.faqs
        self._indexes_ready = False

    def _ensure_indexes(self):
        # Created lazily: the database may not be reachable at import time.
        if not self._indexes_ready:
            self.faqs.create_index([("doc_id", 1), ("norm_question", 1)])
            self.faqs.create_index([("doc_id", 1), ("pinned", -1), ("created_at", -1)])
            self._indexes_ready = True

    def ping(self):
        try:
            self.client.admin.command("ping")
            return True
        except Exception:
            return False

    # ---- documents ----
    def list_docs(self):
        docs = [_out(d) for d in self.documents.find({}, SUMMARY_FIELDS).sort("updated_at", -1)]
        for d in docs:
            d["faq_count"] = self.faqs.count_documents({"doc_id": d["id"]})
        return docs

    def get_doc(self, doc_id):
        oid = _oid(doc_id)
        return _out(self.documents.find_one({"_id": oid})) if oid else None

    def create_doc(self, data):
        result = self.documents.insert_one(dict(data))
        return self.get_doc(str(result.inserted_id))

    def update_doc(self, doc_id, data):
        oid = _oid(doc_id)
        if not oid:
            return None
        return _out(self.documents.find_one_and_update(
            {"_id": oid}, {"$set": data}, return_document=ReturnDocument.AFTER))

    def delete_doc(self, doc_id):
        oid = _oid(doc_id)
        if not oid:
            return False
        deleted = self.documents.delete_one({"_id": oid}).deleted_count == 1
        if deleted:
            self.faqs.delete_many({"doc_id": doc_id})  # cascade: a doc owns its FAQ
        return deleted

    # ---- faqs ----
    def list_faqs(self, doc_id):
        self._ensure_indexes()
        cursor = self.faqs.find({"doc_id": doc_id}).sort([("pinned", -1), ("created_at", -1)])
        return [_out(f) for f in cursor]

    def get_faq(self, faq_id):
        oid = _oid(faq_id)
        return _out(self.faqs.find_one({"_id": oid})) if oid else None

    def find_faq_by_norm(self, doc_id, norm_question):
        self._ensure_indexes()
        return _out(self.faqs.find_one({"doc_id": doc_id, "norm_question": norm_question}))

    def create_faq(self, data):
        self._ensure_indexes()
        result = self.faqs.insert_one(dict(data))
        return self.get_faq(str(result.inserted_id))

    def update_faq(self, faq_id, data):
        oid = _oid(faq_id)
        if not oid:
            return None
        return _out(self.faqs.find_one_and_update(
            {"_id": oid}, {"$set": data}, return_document=ReturnDocument.AFTER))

    def delete_faq(self, faq_id):
        oid = _oid(faq_id)
        return bool(oid) and self.faqs.delete_one({"_id": oid}).deleted_count == 1
