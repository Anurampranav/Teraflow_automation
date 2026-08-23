"""
Append-only JSON-lines audit log, with a read-back helper so the
dashboard can display recent history.
"""

import json
import os
import threading
import time
import datetime
from typing import Any


class AuditLog:
    def __init__(self, path: str):
        self.path = path
        self._lock = threading.Lock()

    def write(self, **fields: Any) -> dict:
        record = {"timestamp": time.time(), "timestamp_iso": _iso_now()}
        record.update(fields)
        with self._lock:
            with open(self.path, "a") as f:
                f.write(json.dumps(record) + "\n")
        return record

    def read_recent(self, limit: int = 50) -> list[dict]:
        if not os.path.exists(self.path):
            return []
        with self._lock:
            with open(self.path, "r") as f:
                lines = f.readlines()
        entries = []
        for line in lines[-limit:]:
            line = line.strip()
            if not line:
                continue
            try:
                entries.append(json.loads(line))
            except json.JSONDecodeError:
                continue
        entries.sort(key=lambda e: e.get("timestamp", 0), reverse=True)
        return entries


def _iso_now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat()
