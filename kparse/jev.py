"""Minimal Jev (TypeSafe System One) client with an on-disk answer cache.

Raw HTTP rather than typesafe-sdk: the API is one POST, and this keeps the
parser dependency-free beyond requests. Docs: https://docs.typesafe.ai/api.md

The key comes from $TYPESAFE_API_KEY, or from a TYPESAFE_API_KEY=... line
in korean-parser/.env (gitignored).
"""
import hashlib
import json
import os
import sqlite3
import threading
import time
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
ENDPOINT = "https://api.typesafe.ai/v1/systemone"
MODEL = "jev-latest"


def api_key() -> str | None:
    key = os.environ.get("TYPESAFE_API_KEY")
    if key:
        return key.strip()
    env = ROOT / ".env"
    if env.exists():
        for line in env.read_text(encoding="utf-8").splitlines():
            name, _, value = line.partition("=")
            if name.strip() == "TYPESAFE_API_KEY" and value.strip():
                return value.strip().strip('"').strip("'")
    return None


class JevError(RuntimeError):
    pass


class Jev:
    def __init__(self, key: str | None = None, model: str = MODEL,
                 cache_path: Path = ROOT / ".cache" / "jev.sqlite"):
        self.key = key or api_key()
        if not self.key:
            raise JevError("No TYPESAFE_API_KEY (env var or korean-parser/.env)")
        self.model = model
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(cache_path, check_same_thread=False)
        self.db.execute("CREATE TABLE IF NOT EXISTS answers (k TEXT PRIMARY KEY, v TEXT)")
        self.lock = threading.Lock()
        self.session = requests.Session()
        self.input_tokens = 0
        self.calls = 0

    def ask(self, state, questions: dict) -> dict:
        """Returns the `answers` map. Identical requests are served from cache."""
        body = {"model": self.model, "state": state, "questions": questions}
        k = hashlib.sha256(json.dumps(body, ensure_ascii=False,
                                      sort_keys=True).encode()).hexdigest()
        with self.lock:
            row = self.db.execute("SELECT v FROM answers WHERE k=?", (k,)).fetchone()
        if row:
            return json.loads(row[0])

        r = None
        for attempt in range(6):
            try:
                r = self.session.post(
                    ENDPOINT, json=body, timeout=30,
                    headers={"Authorization": f"Bearer {self.key}"})
            except requests.RequestException:          # DNS/network blips: retry like a 5xx
                time.sleep(min(2 ** attempt, 30))
                continue
            if r.status_code in (429, 529) or r.status_code >= 500:
                time.sleep(min(2 ** attempt, 30))
                continue
            if r.status_code != 200:
                raise JevError(f"HTTP {r.status_code}: {r.text[:500]}")
            data = r.json()
            break
        else:
            raise JevError(f"gave up after retries (last HTTP {r.status_code if r is not None else 'no connection'})")

        answers = data["answers"]
        with self.lock:
            self.calls += 1
            self.input_tokens += data.get("usage", {}).get("input_tokens", 0)
            self.db.execute("INSERT OR REPLACE INTO answers VALUES (?, ?)",
                            (k, json.dumps(answers, ensure_ascii=False)))
            self.db.commit()
        return answers

    @property
    def cost_usd(self) -> float:
        return self.input_tokens * 0.042 / 1_000_000
