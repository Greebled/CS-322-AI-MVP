"""
All environment-specific settings live here (factor variable from fixed).
Values come from environment variables set by docker-compose.yml.
"""
import os


class Config:
    def __init__(self, env=None):
        env = os.environ if env is None else env
        self.MONGO_URL = env.get("MONGO_URL", "mongodb://localhost:27017/faqbuilder")
        self.AI_PROVIDER = env.get("AI_PROVIDER", "auto").strip().lower()
        self.ANTHROPIC_API_KEY = env.get("ANTHROPIC_API_KEY", "").strip()
        self.CLAUDE_MODEL = env.get("CLAUDE_MODEL", "claude-haiku-5-5").strip()
        self.DEBUG = env.get("FLASK_DEBUG", "0") == "1"
        # Treat the placeholder from .env.example as "no key"
        if self.ANTHROPIC_API_KEY in ("your-api-key-here",):
            self.ANTHROPIC_API_KEY = ""
