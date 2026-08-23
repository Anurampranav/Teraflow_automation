"""
Central, thread-safe application state.

This holds everything that used to live scattered across a YAML file
and CLI args: Tuya credentials, device IDs/DP-code mappings, automation
thresholds, and live runtime status (moisture, valve state, etc.) for
the dashboard to poll.

Persisted fields (credentials, device mapping, automation settings) are
written to CONFIG_PATH as plain JSON on every change, so a server
restart doesn't lose your setup. This file is NOT encrypted — this app
is designed to run on your own local machine only. Do not expose this
server's port to the public internet.
"""

import json
import os
import threading
import time
from typing import Any, Optional

CONFIG_PATH = "runtime_config.json"

DEFAULT_AUTOMATION_SETTINGS = {
    "moisture_threshold_percent": 30,
    "cooldown_minutes": 60,
    "max_irrigation_duration_minutes": 10,
    "stale_data_minutes": 30,
    "poll_interval_minutes": 10,
    "dry_run": True,
}


class AppState:
    def __init__(self, config_path: str = CONFIG_PATH):
        self.config_path = config_path
        self._lock = threading.RLock()

        # --- Persisted config ---
        self.tuya_access_id: Optional[str] = None
        self.tuya_access_secret: Optional[str] = None
        self.tuya_api_endpoint: Optional[str] = None
        self.tuya_connected: bool = False

        self.soil_sensor_id: Optional[str] = None
        self.xpr3ss_id: Optional[str] = None
        self.soil_moisture_dp_code: Optional[str] = None
        self.soil_temperature_dp_code: Optional[str] = None
        self.valve_switch_dp_code: Optional[str] = None
        self.devices_verified: bool = False
        self.devices_mapped: bool = False

        self.automation_settings: dict = dict(DEFAULT_AUTOMATION_SETTINGS)

        # --- Runtime-only (not persisted) ---
        self.automation_running: bool = False
        self.stop_event = threading.Event()
        self.worker_thread: Optional[threading.Thread] = None

        self.last_status: dict = {
            "moisture_percent": None,
            "temperature": None,
            "valve_on": False,
            "valve_on_since_ts": None,
            "last_cycle_ts": None,
            "last_cycle_action": None,
            "last_cycle_reason": None,
            "last_error": None,
        }

        self._load_config()

    # ---------------------------------------------------------
    # Persistence
    # ---------------------------------------------------------
    def _load_config(self) -> None:
        if not os.path.exists(self.config_path):
            return
        try:
            with open(self.config_path, "r") as f:
                data = json.load(f)
        except (json.JSONDecodeError, OSError):
            return  # start fresh rather than crash on a corrupt file

        with self._lock:
            self.tuya_access_id = data.get("tuya_access_id")
            self.tuya_access_secret = data.get("tuya_access_secret")
            self.tuya_api_endpoint = data.get("tuya_api_endpoint")
            self.tuya_connected = data.get("tuya_connected", False)

            self.soil_sensor_id = data.get("soil_sensor_id")
            self.xpr3ss_id = data.get("xpr3ss_id")
            self.soil_moisture_dp_code = data.get("soil_moisture_dp_code")
            self.soil_temperature_dp_code = data.get("soil_temperature_dp_code")
            self.valve_switch_dp_code = data.get("valve_switch_dp_code")
            self.devices_verified = data.get("devices_verified", False)
            self.devices_mapped = data.get("devices_mapped", False)

            saved_settings = data.get("automation_settings", {})
            merged = dict(DEFAULT_AUTOMATION_SETTINGS)
            merged.update(saved_settings)
            self.automation_settings = merged

    def _save_config(self) -> None:
        data = {
            "tuya_access_id": self.tuya_access_id,
            "tuya_access_secret": self.tuya_access_secret,
            "tuya_api_endpoint": self.tuya_api_endpoint,
            "tuya_connected": self.tuya_connected,
            "soil_sensor_id": self.soil_sensor_id,
            "xpr3ss_id": self.xpr3ss_id,
            "soil_moisture_dp_code": self.soil_moisture_dp_code,
            "soil_temperature_dp_code": self.soil_temperature_dp_code,
            "valve_switch_dp_code": self.valve_switch_dp_code,
            "devices_verified": self.devices_verified,
            "devices_mapped": self.devices_mapped,
            "automation_settings": self.automation_settings,
        }
        tmp_path = self.config_path + ".tmp"
        with open(tmp_path, "w") as f:
            json.dump(data, f, indent=2)
        os.replace(tmp_path, self.config_path)

    # ---------------------------------------------------------
    # Mutators (all lock-protected + persist immediately)
    # ---------------------------------------------------------
    def set_tuya_credentials(self, access_id: str, access_secret: str,
                              api_endpoint: str, connected: bool) -> None:
        with self._lock:
            self.tuya_access_id = access_id
            self.tuya_access_secret = access_secret
            self.tuya_api_endpoint = api_endpoint
            self.tuya_connected = connected
            self._save_config()

    def set_devices(self, soil_sensor_id: str, xpr3ss_id: str) -> None:
        with self._lock:
            self.soil_sensor_id = soil_sensor_id
            self.xpr3ss_id = xpr3ss_id
            self.devices_verified = True
            self.devices_mapped = False  # must re-map DP codes for new IDs
            self._save_config()

    def set_dp_mapping(self, moisture_code: str, temperature_code: Optional[str],
                        switch_code: str) -> None:
        with self._lock:
            self.soil_moisture_dp_code = moisture_code
            self.soil_temperature_dp_code = temperature_code
            self.valve_switch_dp_code = switch_code
            self.devices_mapped = True
            self._save_config()

    def update_automation_settings(self, **kwargs: Any) -> None:
        with self._lock:
            for key, value in kwargs.items():
                if key in DEFAULT_AUTOMATION_SETTINGS:
                    self.automation_settings[key] = value
            self._save_config()

    def is_ready_for_automation(self) -> tuple[bool, str]:
        with self._lock:
            if not self.tuya_connected:
                return False, "Tuya Cloud is not connected yet."
            if not self.devices_verified:
                return False, "Devices have not been verified yet."
            if not self.devices_mapped:
                return False, "Device data points have not been mapped yet."
            return True, ""

    def update_status(self, **kwargs: Any) -> None:
        with self._lock:
            self.last_status.update(kwargs)

    def try_start_automation(self) -> bool:
        """Atomically starts automation if not already running.
        Returns True if this call started it, False if already running."""
        with self._lock:
            if self.automation_running:
                return False
            self.stop_event.clear()
            self.automation_running = True
            return True

    def stop_automation(self) -> None:
        with self._lock:
            self.stop_event.set()
            self.automation_running = False

    def set_worker_thread(self, thread) -> None:
        with self._lock:
            self.worker_thread = thread

    def get_status_snapshot(self) -> dict:
        with self._lock:
            snapshot = dict(self.last_status)
            snapshot["automation_running"] = self.automation_running
            snapshot["dry_run"] = self.automation_settings.get("dry_run", True)
            snapshot["automation_settings"] = dict(self.automation_settings)
            snapshot["tuya_connected"] = self.tuya_connected
            snapshot["devices_verified"] = self.devices_verified
            snapshot["devices_mapped"] = self.devices_mapped
            snapshot["server_time"] = time.time()
            return snapshot
