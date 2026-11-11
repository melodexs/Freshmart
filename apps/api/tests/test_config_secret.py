"""Production must not start with a missing or weak signing secret.

Each case runs in a fresh Python process, so importing the config under
production settings cannot disturb the other tests.
"""

import os
import subprocess
import sys
from pathlib import Path

API_DIR = Path(__file__).resolve().parents[1]


def import_config(env: str, secret: str | None) -> subprocess.CompletedProcess:
    child_env = {k: v for k, v in os.environ.items() if k not in {"JWT_SECRET", "RENDER", "ENV"}}
    child_env["ENV"] = env
    if secret is not None:
        child_env["JWT_SECRET"] = secret
    return subprocess.run(
        [sys.executable, "-c", "from app import config; print(len(config.JWT_SECRET))"],
        cwd=API_DIR,
        env=child_env,
        capture_output=True,
        text=True,
        timeout=30,
    )


def test_production_rejects_a_short_secret():
    r = import_config("production", "too-short")
    assert r.returncode != 0 and "at least 32" in r.stderr


def test_production_rejects_a_missing_secret():
    r = import_config("production", None)
    assert r.returncode != 0 and "must be set" in r.stderr


def test_production_accepts_a_long_secret():
    r = import_config("production", "x" * 40)
    assert r.returncode == 0 and r.stdout.strip() == "40"


def test_development_generates_a_random_secret_when_unset():
    r = import_config("development", None)
    assert r.returncode == 0 and r.stdout.strip() == "64"
