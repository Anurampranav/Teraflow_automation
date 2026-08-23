"""
Smart Irrigation Dashboard - Flask server.

Serves the dashboard UI and a small JSON API. Automation runs in a
background thread; the dashboard polls /api/state on a short interval
(cheap, local, in-memory) while the actual Tuya Cloud API is only
called on the user-configured poll_interval_minutes, protecting your
API quota.

Run: python3 server.py
Then open http://localhost:5000 (or http://<your-lan-ip>:5000 from
your phone, if on the same network).

SECURITY NOTE: this server has no login/auth and stores your Tuya
credentials in plaintext in runtime_config.json. It is designed to run
on your own trusted local machine/network only. Do not port-forward
or expose it to the public internet as-is.
"""

import logging
import threading
import time
from typing import Optional

from flask import Flask, jsonify, request, send_from_directory

from tuya_client import TuyaClient, TuyaAPIError
from decision_engine import evaluate, Action
from state_store import StateStore
from audit_log import AuditLog
from app_state import AppState

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("server")

app = Flask(__name__, static_folder="public", static_url_path="")

state = AppState()
history = StateStore("irrigation_state.json")
audit = AuditLog("irrigation_log.jsonl")

# Allows tests to inject a fake Tuya client instead of hitting the real network.
_tuya_client_factory = None


def get_tuya_client() -> TuyaClient:
    if _tuya_client_factory is not None:
        return _tuya_client_factory()
    return TuyaClient(
        access_id=state.tuya_access_id,
        access_secret=state.tuya_access_secret,
        api_endpoint=state.tuya_api_endpoint,
    )


def set_tuya_client_factory(factory) -> None:
    """Test hook: server.set_tuya_client_factory(lambda: FakeClient())"""
    global _tuya_client_factory
    _tuya_client_factory = factory


def extract_dp_value(status_list: list[dict], code: Optional[str]):
    if not code:
        return None
    for item in status_list:
        if item.get("code") == code:
            return item.get("value")
    return None


# ===============================================================
# Static dashboard
# ===============================================================

@app.route("/")
def index():
    return send_from_directory(app.static_folder, "index.html")


# ===============================================================
# Tuya connection
# ===============================================================

@app.route("/api/tuya/connect", methods=["POST"])
def tuya_connect():
    data = request.get_json(force=True, silent=True) or {}
    access_id = (data.get("access_id") or "").strip()
    access_secret = (data.get("access_secret") or "").strip()
    api_endpoint = (data.get("api_endpoint") or "").strip()

    if not access_id or not access_secret or not api_endpoint:
        return jsonify(success=False, error="access_id, access_secret, and api_endpoint are all required."), 400

    client = TuyaClient(access_id, access_secret, api_endpoint) if _tuya_client_factory is None else _tuya_client_factory()

    try:
        client.test_connection()
    except TuyaAPIError as e:
        state.set_tuya_credentials(access_id, access_secret, api_endpoint, connected=False)
        return jsonify(success=False, error=f"Could not connect to Tuya Cloud: {e}"), 400

    state.set_tuya_credentials(access_id, access_secret, api_endpoint, connected=True)
    return jsonify(success=True)


# ===============================================================
# Device verification + DP mapping
# ===============================================================

@app.route("/api/devices/verify", methods=["POST"])
def devices_verify():
    if not state.tuya_connected:
        return jsonify(success=False, error="Connect to Tuya Cloud first."), 400

    data = request.get_json(force=True, silent=True) or {}
    soil_sensor_id = (data.get("soil_sensor_id") or "").strip()
    xpr3ss_id = (data.get("xpr3ss_id") or "").strip()

    if not soil_sensor_id or not xpr3ss_id:
        return jsonify(success=False, error="Both device IDs are required."), 400

    client = get_tuya_client()
    result = {}
    for label, device_id in (("soil_sensor", soil_sensor_id), ("xpr3ss", xpr3ss_id)):
        try:
            info = client.get_device_info(device_id)
            status = client.get_device_status(device_id)
            result[label] = {
                "device_id": device_id,
                "online": info.get("online"),
                "category": info.get("category"),
                "data_points": status,
            }
        except TuyaAPIError as e:
            return jsonify(success=False, error=f"Failed to verify {label} ({device_id}): {e}"), 400

    state.set_devices(soil_sensor_id, xpr3ss_id)
    return jsonify(success=True, devices=result)


@app.route("/api/devices/map", methods=["POST"])
def devices_map():
    if not state.devices_verified:
        return jsonify(success=False, error="Verify devices first."), 400

    data = request.get_json(force=True, silent=True) or {}
    moisture_code = (data.get("soil_moisture_dp_code") or "").strip()
    temperature_code = (data.get("soil_temperature_dp_code") or "").strip() or None
    switch_code = (data.get("valve_switch_dp_code") or "").strip()

    if not moisture_code or not switch_code:
        return jsonify(success=False, error="Moisture and valve switch data point codes are required."), 400

    state.set_dp_mapping(moisture_code, temperature_code, switch_code)
    return jsonify(success=True)


# ===============================================================
# Automation settings
# ===============================================================

@app.route("/api/automation/settings", methods=["POST"])
def automation_settings():
    data = request.get_json(force=True, silent=True) or {}
    allowed_numeric = [
        "moisture_threshold_percent", "cooldown_minutes",
        "max_irrigation_duration_minutes", "stale_data_minutes",
        "poll_interval_minutes",
    ]
    updates = {}
    for key in allowed_numeric:
        if key in data:
            try:
                updates[key] = float(data[key])
            except (TypeError, ValueError):
                return jsonify(success=False, error=f"Invalid numeric value for {key}."), 400
            if updates[key] <= 0:
                return jsonify(success=False, error=f"{key} must be greater than zero."), 400
    if "dry_run" in data:
        updates["dry_run"] = bool(data["dry_run"])

    state.update_automation_settings(**updates)
    return jsonify(success=True, automation_settings=state.automation_settings)


# ===============================================================
# One automation cycle (shared by background loop and tests)
# ===============================================================

def run_one_cycle() -> dict:
    """Runs exactly one decision cycle. Never raises - all errors are
    caught, logged, and reflected in the returned dict / audit log."""
    now_ts = time.time()

    if not state.devices_mapped:
        record = audit.write(cycle_result="ERROR", stage="precondition",
                              error="Devices not mapped; skipping cycle.")
        state.update_status(last_error="Devices not mapped.")
        return record

    client = get_tuya_client()

    try:
        soil_status = client.get_device_status(state.soil_sensor_id)
        soil_info = client.get_device_info(state.soil_sensor_id)
    except TuyaAPIError as e:
        logger.error(f"Failed to read soil sensor: {e}")
        record = audit.write(cycle_result="ERROR", stage="read_soil_sensor", error=str(e))
        state.update_status(last_error=str(e), last_cycle_ts=now_ts)
        return record

    try:
        valve_status = client.get_device_status(state.xpr3ss_id)
    except TuyaAPIError as e:
        logger.error(f"Failed to read XPR3SS status: {e}")
        record = audit.write(cycle_result="ERROR", stage="read_valve_status", error=str(e))
        state.update_status(last_error=str(e), last_cycle_ts=now_ts)
        return record

    moisture = extract_dp_value(soil_status, state.soil_moisture_dp_code)
    temperature = extract_dp_value(soil_status, state.soil_temperature_dp_code)
    valve_on = bool(extract_dp_value(valve_status, state.valve_switch_dp_code))

    sensor_last_report_ts = soil_info.get("update_time")
    if sensor_last_report_ts and sensor_last_report_ts > 10_000_000_000:
        sensor_last_report_ts = sensor_last_report_ts / 1000.0

    settings = state.automation_settings
    valve_on_duration_seconds = None
    valve_on_since_ts = None
    if valve_on:
        start_ts = history.last_watering_start_ts()
        if start_ts is not None:
            valve_on_duration_seconds = now_ts - start_ts
            valve_on_since_ts = start_ts
        else:
            valve_on_duration_seconds = settings["max_irrigation_duration_minutes"] * 60

    decision = evaluate(
        moisture_percent=moisture,
        sensor_last_report_ts=sensor_last_report_ts,
        valve_is_on_now=valve_on,
        valve_on_duration_seconds=valve_on_duration_seconds,
        last_watering_stop_ts=history.last_watering_stop_ts(),
        now_ts=now_ts,
        moisture_threshold_percent=settings["moisture_threshold_percent"],
        cooldown_seconds=settings["cooldown_minutes"] * 60,
        max_duration_seconds=settings["max_irrigation_duration_minutes"] * 60,
        stale_data_seconds=settings["stale_data_minutes"] * 60,
    )

    logger.info(f"Decision: {decision.action.value} - {decision.reason}")

    dry_run = settings.get("dry_run", True)
    command_error = None
    new_valve_on = valve_on
    new_valve_since = valve_on_since_ts

    try:
        if decision.action == Action.WATER_START:
            if not dry_run:
                client.send_commands(state.xpr3ss_id,
                                      [{"code": state.valve_switch_dp_code, "value": True}])
                history.record_watering_start()
            new_valve_on = True
            new_valve_since = now_ts

        elif decision.action == Action.WATCHDOG_FORCE_STOP:
            if not dry_run:
                client.send_commands(state.xpr3ss_id,
                                      [{"code": state.valve_switch_dp_code, "value": False}])
                history.record_watering_stop()
            new_valve_on = False
            new_valve_since = None

    except TuyaAPIError as e:
        logger.error(f"Failed to send command for {decision.action.value}: {e}")
        command_error = str(e)

    record = audit.write(
        cycle_result="OK" if command_error is None else "COMMAND_ERROR",
        action=decision.action.value,
        reason=decision.reason,
        moisture_percent=moisture,
        temperature=temperature,
        valve_on_before_cycle=valve_on,
        dry_run=dry_run,
        command_error=command_error,
    )

    state.update_status(
        moisture_percent=moisture,
        temperature=temperature,
        valve_on=new_valve_on,
        valve_on_since_ts=new_valve_since,
        last_cycle_ts=now_ts,
        last_cycle_action=decision.action.value,
        last_cycle_reason=decision.reason,
        last_error=command_error,
    )
    return record


# ===============================================================
# Background automation loop
# ===============================================================

def _background_loop():
    logger.info("Automation loop started.")
    while not state.stop_event.is_set():
        try:
            run_one_cycle()
        except Exception as e:  # belt-and-braces: a cycle must never kill the thread
            logger.exception(f"Unexpected error in automation cycle: {e}")
            audit.write(cycle_result="ERROR", stage="unexpected_exception", error=str(e))
            state.update_status(last_error=str(e))
        interval_seconds = state.automation_settings["poll_interval_minutes"] * 60
        state.stop_event.wait(timeout=interval_seconds)
    logger.info("Automation loop stopped.")


@app.route("/api/automation/start", methods=["POST"])
def automation_start():
    data = request.get_json(force=True, silent=True) or {}
    if not data.get("confirm"):
        return jsonify(success=False,
                        error="Explicit confirmation required to start automation."), 400

    ready, reason = state.is_ready_for_automation()
    if not ready:
        return jsonify(success=False, error=reason), 400

    started = state.try_start_automation()
    if not started:
        return jsonify(success=True, note="Automation already running.")

    thread = threading.Thread(target=_background_loop, daemon=True)
    state.set_worker_thread(thread)
    thread.start()

    return jsonify(success=True)


@app.route("/api/automation/stop", methods=["POST"])
def automation_stop():
    state.stop_automation()
    audit.write(cycle_result="OK", action="AUTOMATION_STOPPED",
                reason="User stopped automation via dashboard.")
    return jsonify(success=True)


@app.route("/api/automation/emergency-stop", methods=["POST"])
def emergency_stop():
    """Immediately attempts to force the valve OFF, regardless of
    current automation state, and halts the background loop."""
    state.stop_automation()

    command_error = None
    if state.devices_mapped and state.tuya_connected:
        try:
            client = get_tuya_client()
            client.send_commands(state.xpr3ss_id,
                                  [{"code": state.valve_switch_dp_code, "value": False}])
            history.record_watering_stop()
            state.update_status(valve_on=False, valve_on_since_ts=None)
        except TuyaAPIError as e:
            command_error = str(e)
            logger.error(f"Emergency stop command failed: {e}")

    audit.write(cycle_result="OK" if command_error is None else "COMMAND_ERROR",
                action="EMERGENCY_STOP",
                reason="User triggered emergency stop.",
                command_error=command_error)

    if command_error:
        return jsonify(success=False,
                        error=f"Automation halted, but OFF command failed: {command_error}. "
                              f"Check the valve manually."), 502
    return jsonify(success=True)


@app.route("/api/automation/manual", methods=["POST"])
def manual_control():
    if state.automation_running:
        return jsonify(success=False,
                        error="Stop automation before using manual control."), 400
    if not state.devices_mapped:
        return jsonify(success=False, error="Devices not mapped yet."), 400

    data = request.get_json(force=True, silent=True) or {}
    action = data.get("action")
    if action not in ("on", "off"):
        return jsonify(success=False, error="action must be 'on' or 'off'."), 400

    client = get_tuya_client()
    try:
        client.send_commands(state.xpr3ss_id,
                              [{"code": state.valve_switch_dp_code, "value": action == "on"}])
    except TuyaAPIError as e:
        return jsonify(success=False, error=str(e)), 502

    if action == "on":
        history.record_watering_start()
        state.update_status(valve_on=True, valve_on_since_ts=time.time())
    else:
        history.record_watering_stop()
        state.update_status(valve_on=False, valve_on_since_ts=None)

    audit.write(cycle_result="OK", action=f"MANUAL_{action.upper()}",
                reason="User manual control via dashboard.")
    return jsonify(success=True)


# ===============================================================
# Status + logs
# ===============================================================

@app.route("/api/state")
def api_state():
    return jsonify(state.get_status_snapshot())


@app.route("/api/logs")
def api_logs():
    limit = request.args.get("limit", default=50, type=int)
    limit = max(1, min(limit, 500))
    return jsonify(logs=audit.read_recent(limit))


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, threaded=True)
