"""
Integration tests for the REST API using Flask's test client,
an in-memory FakeRepo, and a FakeProvider (no database, no network).
"""
from app import create_app
from config import Config
from fakes import FakeProvider, FakeRepo

MANUAL = (
    "Factory reset\n\nTo erase all settings, press and hold the center button for 15 seconds "
    "until the screen shows Reset.\n\nWarranty\n\nThe thermostat includes a 2-year limited warranty."
)


def make_client(provider=None):
    repo = FakeRepo()
    provider = provider or FakeProvider()
    app = create_app(repo=repo, provider=provider, config=Config(env={}))
    app.testing = True
    return app.test_client(), repo, provider


def create_doc(client):
    res = client.post("/api/docs", json={"title": "Nimbus guide", "content": MANUAL})
    assert res.status_code == 201
    return res.get_json()


def test_health_reports_provider():
    client, _, _ = make_client()
    body = client.get("/api/health").get_json()
    assert body["database"] == "ok" and body["provider"]["name"] == "claude"


def test_create_document_returns_201_with_location():
    client, _, _ = make_client()
    res = client.post("/api/docs", json={"title": "Guide", "content": MANUAL})
    assert res.status_code == 201
    doc = res.get_json()
    assert res.headers["Location"].endswith(f"/api/docs/{doc['id']}")
    assert doc["chunk_count"] >= 1
    assert "chunks" not in doc   # internal field is not exposed


def test_create_document_validation_error():
    client, _, _ = make_client()
    res = client.post("/api/docs", json={"title": "", "content": "too short"})
    assert res.status_code == 400
    assert set(res.get_json()["details"]) == {"title", "content"}


def test_non_json_body_rejected():
    client, _, _ = make_client()
    res = client.post("/api/docs", data="not json", content_type="text/plain")
    assert res.status_code == 400


def test_unknown_document_is_404():
    client, _, _ = make_client()
    assert client.get("/api/docs/doesnotexist").status_code == 404
    assert client.post("/api/docs/doesnotexist/faqs", json={"question": "Hello there?"}).status_code == 404


def test_ask_creates_faq_and_calls_ai_once():
    client, _, provider = make_client()
    doc = create_doc(client)
    res = client.post(f"/api/docs/{doc['id']}/faqs", json={"question": "How do I reset it?"})
    assert res.status_code == 201
    body = res.get_json()
    assert body["cached"] is False
    assert body["faq"]["provider"] == "claude"
    assert body["faq"]["sources"], "answer should cite at least one passage"
    assert len(provider.calls) == 1


def test_repeated_question_is_served_from_saved_faq():
    client, _, provider = make_client()
    doc = create_doc(client)
    client.post(f"/api/docs/{doc['id']}/faqs", json={"question": "How do I reset it?"})
    res = client.post(f"/api/docs/{doc['id']}/faqs", json={"question": "how do i RESET it"})
    assert res.status_code == 200
    assert res.get_json()["cached"] is True
    assert len(provider.calls) == 1   # no second AI call


def test_ai_outage_falls_back_to_keyword_matching():
    client, _, _ = make_client(FakeProvider(fail=True))
    doc = create_doc(client)
    body = client.post(f"/api/docs/{doc['id']}/faqs", json={"question": "How do I reset it?"}).get_json()
    assert body["faq"]["provider"] == "extractive"
    assert "15 seconds" in body["faq"]["answer"]
    assert body["notice"]


def test_question_not_in_document():
    client, _, _ = make_client(FakeProvider(reply=None))
    doc = create_doc(client)
    faq = client.post(f"/api/docs/{doc['id']}/faqs", json={"question": "Is it waterproof?"}).get_json()["faq"]
    assert faq["found"] is False
    assert faq["sources"] == []


def test_manual_faq_skips_ai():
    client, _, provider = make_client()
    doc = create_doc(client)
    res = client.post(f"/api/docs/{doc['id']}/faqs",
                      json={"question": "Who makes it?", "answer": "Nimbus Home."})
    assert res.status_code == 201
    assert res.get_json()["faq"]["provider"] == "manual"
    assert provider.calls == []


def test_update_pin_and_edit_answer():
    client, _, _ = make_client()
    doc = create_doc(client)
    first = client.post(f"/api/docs/{doc['id']}/faqs", json={"question": "How do I reset it?"}).get_json()["faq"]
    client.post(f"/api/docs/{doc['id']}/faqs", json={"question": "What is the warranty?"})

    pinned = client.put(f"/api/faqs/{first['id']}", json={"pinned": True}).get_json()
    assert pinned["pinned"] is True
    listed = client.get(f"/api/docs/{doc['id']}/faqs").get_json()
    assert listed[0]["id"] == first["id"]   # pinned entries come first

    edited = client.put(f"/api/faqs/{first['id']}", json={"answer": "Hold it for 15s."}).get_json()
    assert edited["answer"] == "Hold it for 15s." and edited["provider"] == "edited"


def test_delete_document_cascades_to_faqs():
    client, repo, _ = make_client()
    doc = create_doc(client)
    client.post(f"/api/docs/{doc['id']}/faqs", json={"question": "How do I reset it?"})
    assert client.delete(f"/api/docs/{doc['id']}").status_code == 204
    assert repo.faqs == {}
    assert client.get(f"/api/docs/{doc['id']}").status_code == 404


def test_delete_faq_then_404():
    client, _, _ = make_client()
    doc = create_doc(client)
    faq = client.post(f"/api/docs/{doc['id']}/faqs", json={"question": "How do I reset it?"}).get_json()["faq"]
    assert client.delete(f"/api/faqs/{faq['id']}").status_code == 204
    assert client.get(f"/api/faqs/{faq['id']}").status_code == 404


def test_wrong_method_is_405_json():
    client, _, _ = make_client()
    res = client.patch("/api/docs")
    assert res.status_code == 405 and "error" in res.get_json()
