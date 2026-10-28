"""Bot state kept in a JSON file that the workflow commits to the `state` branch."""
from __future__ import annotations

import copy
import json
import time
from pathlib import Path

import yaml

DEFAULT_PREFS_PATH = Path(__file__).resolve().parent.parent / "config" / "preferences.yaml"
SEEN_TTL_DAYS = 120


def load_default_prefs(path: Path = DEFAULT_PREFS_PATH) -> dict:
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


class State:
    def __init__(self, path: Path, data: dict | None = None):
        self.path = Path(path)
        self.data = data or {}
        self.data.setdefault("telegram_offset", 0)
        self.data.setdefault("chats", [])
        self.data.setdefault("prefs", None)
        self.data.setdefault("seen", {})        # listing url -> unix time first seen
        self.data.setdefault("sent", {})        # listing id -> listing dict (for viewing requests)
        self.data.setdefault("paused", False)
        self.data.setdefault("last_email_uid", 0)

    @classmethod
    def load(cls, path: Path) -> "State":
        path = Path(path)
        if path.exists():
            with open(path, encoding="utf-8") as f:
                return cls(path, json.load(f))
        return cls(path)

    def save(self) -> None:
        self._prune()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(self.data, f, ensure_ascii=False, indent=1, sort_keys=True)
        tmp.replace(self.path)

    def _prune(self) -> None:
        cutoff = time.time() - SEEN_TTL_DAYS * 86400
        self.data["seen"] = {u: t for u, t in self.data["seen"].items() if t >= cutoff}
        sent = self.data["sent"]
        if len(sent) > 300:
            keep = sorted(sent, key=lambda k: sent[k].get("_sent_at", 0))[-300:]
            self.data["sent"] = {k: sent[k] for k in keep}

    @property
    def prefs(self) -> dict:
        if self.data["prefs"] is None:
            self.data["prefs"] = load_default_prefs()
        return self.data["prefs"]

    def reset_prefs(self) -> None:
        self.data["prefs"] = copy.deepcopy(load_default_prefs())

    def is_seen(self, url: str) -> bool:
        return url in self.data["seen"]

    def mark_seen(self, url: str) -> None:
        self.data["seen"].setdefault(url, int(time.time()))
