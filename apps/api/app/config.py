"""Environment-driven settings."""

from __future__ import annotations

import os
import secrets
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent.parent
STATIC_DIR = Path(os.environ.get("STATIC_DIR", BASE_DIR.parent / "web" / "static"))
DATA_FILE = Path(os.environ.get("DATA_FILE", BASE_DIR / "data" / "db.json"))

DATABASE_URL = os.environ.get("DATABASE_URL", "").strip()
USE_POSTGRES = bool(DATABASE_URL)

# Render sets RENDER=true. Treat that, or ENV=production, as production.
IS_PRODUCTION = (
    os.environ.get("RENDER", "").lower() == "true"
    or os.environ.get("ENV", "").lower() == "production"
)

MIN_SECRET_LENGTH = 32
_jwt_secret = os.environ.get("JWT_SECRET", "").strip()
if not _jwt_secret:
    if IS_PRODUCTION:
        raise RuntimeError("JWT_SECRET must be set in production.")
    # Dev only: random per-process secret, so there is no guessable default.
    _jwt_secret = secrets.token_hex(32)
elif IS_PRODUCTION and len(_jwt_secret) < MIN_SECRET_LENGTH:
    # HS256 keys shorter than 32 bytes are weak. Render's generateValue is longer.
    raise RuntimeError(f"JWT_SECRET must be at least {MIN_SECRET_LENGTH} characters in production.")
JWT_SECRET = _jwt_secret

COOKIE_NAME = "fm_token"
TOKEN_TTL_SECONDS = 30 * 24 * 60 * 60
COOKIE_SECURE = IS_PRODUCTION

# Staff feed protection. If unset in production the feed is disabled (403).
STORE_STAFF_KEY = os.environ.get("STORE_STAFF_KEY", "").strip()
PORT = int(os.environ.get("PORT", "4000"))

# Hosted Postgres needs SSL. Set PGSSLMODE=disable only for a local, non-SSL database.
PG_SSL = False if os.environ.get("PGSSLMODE", "").lower() == "disable" else "require"
