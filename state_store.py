"""
Persistent state store for watering history.

Tracks facts the decision engine must not lose across restarts:
last watering start/stop times. Thread-safe since it's accessed both
from Flask request handlers and the background automation thread.
"""

import json
import os
import threading
import time
from typing import Optional


class StateStore:
    def __init__(self, path: str):
        self.path = path
        self._lock = threading.Lock()
        self._state = self._load()

    def _load(self) -> dict:
        if os.path.exists(self.path):
            try:
                with open(self.path, "r") as f:
                    return json.load(f)
            except (json.JSONDecodeError, OSError):
                # Corrupt state file -> start fresh rather than crash.
                pass
        return {
            "last_watering_start_ts": None,
            "last_watering_stop_ts": None,
            "believed_valve_on": False,
        }

    def _save(self) -> None:
        tmp_path = self.path + ".tmp"
        with open(tmp_path, "w") as f:
            json.dump(self._state, f, indent=2)
        os.replace(tmp_path, self.path)  # atomic on POSIX

    def record_watering_start(self) -> None:
        with self._lock:
            self._state["last_watering_start_ts"] = time.time()
            self._state["believed_valve_on"] = True
            self._save()

    def record_watering_stop(self) -> None:
        with self._lock:
            self._state["last_watering_stop_ts"] = time.time()
            self._state["believed_valve_on"] = False
            self._save()

    def last_watering_start_ts(self) -> Optional[float]:
        with self._lock:
            return self._state.get("last_watering_start_ts")

    def last_watering_stop_ts(self) -> Optional[float]:
        with self._lock:
            return self._state.get("last_watering_stop_ts")

    def believed_valve_on(self) -> bool:
        with self._lock:
            return self._state.get("believed_valve_on", False)
