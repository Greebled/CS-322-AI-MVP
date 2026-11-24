"""
Test doubles. FakeRepo has the same methods as db.MongoRepository but keeps
everything in dictionaries, so API tests run without a database.
"""
import itertools

from ai_providers import ProviderError


class FakeRepo:
    def __init__(self):
        self.docs, self.faqs = {}, {}
        self._seq = itertools.count(1)

    def _new_id(self):
        return f"{next(self._seq):024x}"  # looks like a Mongo ObjectId

    def ping(self):
        return True

    def list_docs(self):
        out = []
        for d in sorted(self.docs.values(), key=lambda d: d["id"], reverse=True):
            summary = {k: v for k, v in d.items() if k not in ("content", "chunks")}
            summary["faq_count"] = sum(1 for f in self.faqs.values() if f["doc_id"] == d["id"])
            out.append(summary)
        return out

    def get_doc(self, doc_id):
        d = self.docs.get(doc_id)
        return dict(d) if d else None

    def create_doc(self, data):
        doc = dict(data, id=self._new_id())
        self.docs[doc["id"]] = doc
        return dict(doc)

    def update_doc(self, doc_id, data):
        if doc_id not in self.docs:
            return None
        self.docs[doc_id].update(data)
        return dict(self.docs[doc_id])

    def delete_doc(self, doc_id):
        if doc_id not in self.docs:
            return False
        del self.docs[doc_id]
        self.faqs = {k: f for k, f in self.faqs.items() if f["doc_id"] != doc_id}
        return True

    def list_faqs(self, doc_id):
        items = [dict(f) for f in self.faqs.values() if f["doc_id"] == doc_id]
        return sorted(items, key=lambda f: (f["pinned"], f["id"]), reverse=True)

    def get_faq(self, faq_id):
        f = self.faqs.get(faq_id)
        return dict(f) if f else None

    def find_faq_by_norm(self, doc_id, norm):
        for f in self.faqs.values():
            if f["doc_id"] == doc_id and f["norm_question"] == norm:
                return dict(f)
        return None

    def create_faq(self, data):
        faq = dict(data, id=self._new_id())
        self.faqs[faq["id"]] = faq
        return dict(faq)

    def update_faq(self, faq_id, data):
        if faq_id not in self.faqs:
            return None
        self.faqs[faq_id].update(data)
        return dict(self.faqs[faq_id])

    def delete_faq(self, faq_id):
        return self.faqs.pop(faq_id, None) is not None


class FakeProvider:
    """Pretends to be Claude. Records every call; can be told to fail."""
    name = "claude"
    needs_keyword_match = False

    def __init__(self, reply="Hold the center button for 15 seconds.", fail=False):
        self.reply, self.fail, self.calls = reply, fail, []

    def info(self):
        return {"name": self.name, "label": "Fake", "model": "fake-model"}

    def answer(self, question, passages, doc_title):
        self.calls.append((question, passages, doc_title))
        if self.fail:
            raise ProviderError("simulated outage")
        if self.reply is None:
            return {"answer": None, "found": False, "model": "fake-model"}
        return {"answer": self.reply, "found": True, "model": "fake-model"}
