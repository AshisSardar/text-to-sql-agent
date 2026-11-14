"""Settings loaded from the .env file (see .env.example)."""

import os

from dotenv import load_dotenv

load_dotenv()

LLM_PROVIDER = os.getenv("LLM_PROVIDER", "anthropic")
LLM_MODEL = os.getenv("LLM_MODEL", "claude-opus-5-5")
LLM_MAX_TOKENS = int(os.getenv("LLM_MAX_TOKENS", "8000"))
# Give up on one LLM call after this many seconds, and retry it this many times
# (rate limits, network blips). Without a timeout a stuck call hangs forever.
LLM_TIMEOUT_S = float(os.getenv("LLM_TIMEOUT_S", "60"))
LLM_MAX_RETRIES = int(os.getenv("LLM_MAX_RETRIES", "2"))

DATABASE_URL = os.getenv("DATABASE_URL", "")
MAX_ROWS = int(os.getenv("MAX_ROWS", "200"))
STATEMENT_TIMEOUT_MS = int(os.getenv("STATEMENT_TIMEOUT_MS", "5000"))

# Total SQL generation attempts per question (1 first try + retries).
MAX_ATTEMPTS = int(os.getenv("MAX_ATTEMPTS", "3"))

# The only tables generated SQL may read.
ALLOWED_TABLES = frozenset({"stores", "products", "customers", "orders", "order_items"})
