# FAQ Builder

**Bitbucket:** `https://bitbucket.org/<your-username>/<your-repo>`
**Video demo (Canvas):** `<paste Canvas link here>`
**Author:** `<your name>`

Paste a product document, ask questions in plain English, and get answers grounded in that document. The source passages are highlighted, and every answer is saved as an editable FAQ entry in MongoDB.

---

## Tech stack

| Layer | Technology |
|---|---|
| Containers | Docker + Docker Compose (2 services: `web`, `db`) |
| Backend | Python 3.12, Flask 3.0.3 |
| Database | MongoDB 7.0 (PyMongo 4.8.0) |
| Frontend | HTML, CSS, vanilla JavaScript (`fetch` for AJAX), no JS libraries |
| AI | Anthropic Claude via the Messages API (`requests` 2.32.3), with a no-AI keyword fallback |
| Tests | pytest 8.3.2 |

## How to run locally

```bash
git clone <bitbucket-url>
cd faq-builder
cp .env.example .env          # then paste your Anthropic API key into .env (optional)
docker compose up --build
```

Open **http://localhost:5001**. Flask listens on port 5000 inside the container, and Compose maps it to 5001 on your machine. MongoDB stays inside the Docker network and is not exposed.

No API key? Leave `.env` as is, or set `AI_PROVIDER=extractive`. The app still runs and answers by quoting the most relevant sentences, and the sidebar shows which mode is active.

To stop it, run `docker compose down`. Your data stays in the `mongo_data` volume. To wipe it as well, run `docker compose down -v`.

## How to run tests

```bash
docker compose run --rm web pytest -q
```

The suite has 34 tests and needs no database or API key. The API tests swap in an in-memory `FakeRepo` and a `FakeProvider` (see `web/tests/fakes.py`).

- `test_faq_logic.py`: unit tests for chunking, retrieval, tokenizing, and prompt building (pure functions)
- `test_validation.py`: input validation rules
- `test_api.py`: REST endpoints through Flask's test client. Covers status codes, caching of repeated questions, fallback when the AI fails, and cascade delete.

---

## REST API

| Method | URI | Purpose | Success |
|---|---|---|---|
| GET | `/api/docs` | List documents (with FAQ counts) | 200 |
| POST | `/api/docs` | Create a document `{title, content}` | 201 + `Location` |
| GET | `/api/docs/<id>` | Read one document | 200 |
| PUT | `/api/docs/<id>` | Replace title/content (re-chunks it) | 200 |
| DELETE | `/api/docs/<id>` | Delete document **and** its FAQ entries | 204 |
| GET | `/api/docs/<id>/faqs` | List saved Q/A pairs (pinned first) | 200 |
| POST | `/api/docs/<id>/faqs` | Ask a question → creates a FAQ entry. Include `answer` to add one manually. | 201 (new) / 200 (already saved) |
| GET | `/api/faqs/<id>` | Read one FAQ entry | 200 |
| PUT | `/api/faqs/<id>` | Update `question`, `answer`, and/or `pinned` | 200 |
| DELETE | `/api/faqs/<id>` | Delete a FAQ entry | 204 |
| POST | `/api/faqs/<id>/regenerate` | Ask the AI again for an existing question | 200 |
| GET | `/api/health` | Database status + which AI provider is active | 200 |

Errors use standard codes with a JSON body: `{"error": "...", "details": {"field": "message"}}`. The codes are 400 (validation), 404, 405, and 503 (database down).

The main design decision: **asking a question is modeled as creating a resource.** `POST /api/docs/<id>/faqs` creates a FAQ entry, so the AI call is part of resource creation, not a custom "ask" verb. Only `/regenerate` is a pragmatic action-style endpoint.

Example:

```bash
curl -X POST localhost:5001/api/docs/<id>/faqs \
     -H "Content-Type: application/json" \
     -d '{"question": "How do I reset it?"}'
```

## How it works

```
Browser (app.js) --fetch/JSON--> Flask routes (app.py)
                                   |-- validation.py   check input
                                   |-- faq_logic.py    chunk doc, rank passages (pure functions)
                                   |-- ai_providers.py Claude or keyword fallback (shim)
                                   '-- db.py           MongoDB access layer
```

1. When a document is saved, it is split into ~700-character sections (`chunk_document`).
2. When a question comes in, its normalized form is checked against saved FAQ entries. If it was already asked ("How do I reset it?" vs "how do i RESET it"), the saved answer comes back without another AI call.
3. Otherwise, sections are ranked by a small TF-IDF keyword score (`retrieve`). The top 4 go to Claude with instructions to answer only from those passages, or to reply `NOT_IN_DOC`.
4. If Claude fails (no network, bad key, rate limit), the app falls back to quoting the best-matching sentences and tells the user it did.
5. The answer, its source passages, and which provider produced it are saved in MongoDB. The UI highlights the question's keywords inside each source passage.

### Project layout

```
docker-compose.yml        db + web services, named volume, health check
.env.example              template for secrets (real .env is git-ignored)
web/
  Dockerfile
  requirements.txt
  app.py                  Flask app + REST routes
  config.py               reads environment variables
  db.py                   MongoRepository (all PyMongo code)
  faq_logic.py            pure domain logic
  ai_providers.py         ClaudeProvider / ExtractiveProvider + provider table
  validation.py           request validation
  templates/index.html
  static/css/style.css
  static/js/app.js        AJAX + UI
  static/samples/         sample thermostat manual for the demo
  tests/                  pytest suite + fakes
```

---

## What is cool about this project?

> ✏️ *Rewrite this in your own words. These are starting points.*

- **Answers show their evidence.** Each answer expands to the exact document passages it came from, with the question's keywords highlighted. You can check the AI instead of trusting it.
- **It saves money and stays consistent.** Repeated questions (even with different capitalization or punctuation) return the saved answer instantly instead of calling the AI again.
- **It degrades gracefully.** With no API key, or if Claude is down, the app still works using keyword matching, and it tells you which mode answered.
- **The FAQ is curated, not just generated.** You can pin, edit, re-ask, or delete answers, and edited answers are labeled as human-edited.

## What AI tool(s) did I use, and for what?

> ✏️ *Fill in honestly. Your instructor asked for exact prompts.*

**1. Claude (Anthropic) as part of the running app (model inference).**
- Endpoint: `POST https://api.anthropic.com/v1/messages`, header `anthropic-version: 2023-06-01`
- Model: set by `CLAUDE_MODEL` in `.env` (default `claude-haiku-5-5`)
- System prompt (from `web/faq_logic.py`):
  > You answer customer questions about a product using only the documentation passages provided. Reply in 1 to 4 plain sentences with no markdown, no headings, and no preamble. Do not invent details that are not in the passages. If the passages do not contain the answer, reply with exactly: NOT_IN_DOC
- User message format:
  ```
  Document: <title>

  Passages:
  [1] <passage>
  [2] <passage>

  Question: <user's question>
  ```

**2. `<AI assistant you used while building>` for code generation and design.**
- `<What you asked it to do, e.g. generate the initial Flask + Docker Compose scaffold, the REST design, tests, and UI>`
- Prompt(s): `<paste the prompt(s) you used>`
- `<What you changed, debugged, or decided yourself afterwards>`

## What did I learn?

> ✏️ *Write this yourself; it should reflect your experience. Some topics you might speak to:*
> - How separating pure logic (`faq_logic.py`) from Flask and Mongo made the AI feature testable without a network (Ch. 11)
> - Using a shim/adapter so the app doesn't care which AI service answers (Ch. 4)
> - Modeling "ask a question" as creating a REST resource, and choosing 201 vs 200 (Ch. 14)
> - Why validation must happen on the server even when JavaScript validates first (Ch. 17)
> - Keeping the API key out of git with `.env` + `.env.example` (Ch. 6)

## Main technical challenges and how I solved them

> ✏️ *Describe what actually happened to you. Examples of challenges this design addresses:*
> - **Long documents vs. what to send the AI:** split documents into sections and send only the most relevant ones.
> - **The AI making things up:** a strict prompt plus a `NOT_IN_DOC` sentinel, and showing sources so users can verify.
> - **Flask starting before MongoDB was ready:** a Compose `healthcheck` with `depends_on: condition: service_healthy`.
> - **Testing code that calls a paid API:** dependency injection with fake providers and repositories.
> - **XSS from user-supplied documents:** the frontend only inserts text via `textContent`, never `innerHTML`.
