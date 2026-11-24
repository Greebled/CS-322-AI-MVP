"""
AI provider shim (see Ch. 4: portability layers).

The Flask app only ever calls provider.answer(question, passages, doc_title)
and reads provider.info(). Which implementation sits behind that interface is
chosen from a table, so adding another AI service means adding one class and
one table entry -- no route code changes.
"""
import requests

from faq_logic import build_prompt, extractive_answer

ANTHROPIC_URL = "https://api.anthropic.com/v1/messages"
ANTHROPIC_VERSION = "2023-06-01"


class ProviderError(Exception):
    """Raised when an AI service call fails (network, auth, rate limit...)."""


class ExtractiveProvider:
    """No AI: answers by quoting the most relevant sentences."""
    name = "extractive"
    needs_keyword_match = True   # can't answer anything without matching passages

    def info(self):
        return {"name": self.name, "label": "Keyword matching", "model": None}

    def answer(self, question, passages, doc_title):
        text = extractive_answer(question, passages)
        return {"answer": text, "found": text is not None, "model": None}


class ClaudeProvider:
    """Anthropic Claude via the Messages API."""
    name = "claude"
    needs_keyword_match = False  # can reason over passages even without exact word overlap

    def __init__(self, api_key, model, timeout=30, http=None):
        self.api_key = api_key
        self.model = model
        self.timeout = timeout
        self.http = http or requests  # injectable so tests never hit the network

    def info(self):
        return {"name": self.name, "label": "Claude", "model": self.model}

    def answer(self, question, passages, doc_title):
        system, user = build_prompt(doc_title, question, passages)
        try:
            resp = self.http.post(
                ANTHROPIC_URL,
                headers={
                    "x-api-key": self.api_key,
                    "anthropic-version": ANTHROPIC_VERSION,
                    "content-type": "application/json",
                },
                json={
                    "model": self.model,
                    "max_tokens": 400,
                    "system": system,
                    "messages": [{"role": "user", "content": user}],
                },
                timeout=self.timeout,
            )
        except requests.RequestException as exc:
            raise ProviderError(f"Could not reach the Claude API: {exc}") from exc

        if resp.status_code != 200:
            try:
                detail = resp.json().get("error", {}).get("message", "")
            except ValueError:
                detail = resp.text[:200]
            raise ProviderError(f"Claude API returned {resp.status_code}: {detail}")

        data = resp.json()
        text = "".join(
            block.get("text", "") for block in data.get("content", []) if block.get("type") == "text"
        ).strip()
        if not text or text.startswith("NOT_IN_DOC"):
            return {"answer": None, "found": False, "model": self.model}
        return {"answer": text, "found": True, "model": self.model}


# Table-driven provider selection (Ch. 12): name -> factory(config)
PROVIDERS = {
    "claude": lambda cfg: ClaudeProvider(cfg.ANTHROPIC_API_KEY, cfg.CLAUDE_MODEL),
    "extractive": lambda cfg: ExtractiveProvider(),
}


def build_provider(cfg):
    name = cfg.AI_PROVIDER
    if name == "auto":
        name = "claude" if cfg.ANTHROPIC_API_KEY else "extractive"
    if name == "claude" and not cfg.ANTHROPIC_API_KEY:
        name = "extractive"  # asked for Claude without a key: stay usable
    if name not in PROVIDERS:
        raise ValueError(f"Unknown AI_PROVIDER '{name}'. Choose one of: auto, {', '.join(PROVIDERS)}")
    return PROVIDERS[name](cfg)
