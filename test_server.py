"""
End-to-end tests for server.py using Flask's test client and a fake
Tuya client (no real network calls). Proves the connect -> verify ->
map -> start -> cycle -> emergency-stop flow actually works wired
together, not just the decision engine in isolation.

Run: python3 test_server.py
"""

import os
import sys
import time
import tempfile
import shutil

PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, PROJECT_DIR)

# Each test gets its OWN fresh temp dir (see fresh_server_module), so a
# saved config/state from one test can never leak into or influence another
# test - including preventing a stale "automation_running" state from
# spawning a real background thread that hits the real network.
_ALL_TEST_DIRS = []

from tuya_client import TuyaAPIError  # noqa: E402

passed = 0
failed = 0


def check(name, condition, detail=""):
    global passed, failed
    if condition:
        passed += 1
        print(f"  PASS: {name}")
    else:
        failed += 1
        print(f"  FAIL: {name}  {detail}")


class FakeTuyaClient:
    """Stands in for TuyaClient. Lets tests control device state directly."""

    def __init__(self):
        self.should_fail_token = False
        self.soil_status = [
            {"code": "humidity_value", "value": 24},
            {"code": "temp_current", "value": 284},  # tenths of a degree, as some sensors report
        ]
        self.soil_online = True
        self.soil_update_time = time.time()  # seconds
        self.valve_status = [{"code": "switch", "value": False}]
        self.commands_sent = []

    def test_connection(self):
        if self.should_fail_token:
            raise TuyaAPIError("Simulated auth failure")
        return True

    def get_device_status(self, device_id):
        if device_id == "SOIL_ID":
            return self.soil_status
        elif device_id == "VALVE_ID":
            return self.valve_status
        raise TuyaAPIError(f"Unknown device_id in fake: {device_id}")

    def get_device_info(self, device_id):
        if device_id == "SOIL_ID":
            return {"online": self.soil_online, "category": "hps",
                     "update_time": self.soil_update_time}
        elif device_id == "VALVE_ID":
            return {"online": True, "category": "sfkzq", "update_time": time.time()}
        raise TuyaAPIError(f"Unknown device_id in fake: {device_id}")

    def send_commands(self, device_id, commands):
        self.commands_sent.append((device_id, commands))
        for cmd in commands:
            if device_id == "VALVE_ID" and cmd["code"] == "switch":
                self.valve_status = [{"code": "switch", "value": cmd["value"]}]
        return True


def fresh_server_module():
    """Reimport server.py fresh in a brand-new temp directory, so no
    config/state/log file from a previous test can leak into this one."""
    test_dir = tempfile.mkdtemp(prefix="irrigation_test_")
    _ALL_TEST_DIRS.append(test_dir)
    os.chdir(test_dir)

    for mod_name in list(sys.modules):
        if mod_name in ("server", "app_state"):
            del sys.modules[mod_name]
    import server as srv
    return srv


def test_connect_requires_all_fields():
    print("\nTest: /api/tuya/connect rejects missing fields")
    srv = fresh_server_module()
    client = srv.app.test_client()
    resp = client.post("/api/tuya/connect", json={"access_id": "x"})
    check("returns 400 on missing fields", resp.status_code == 400)


def test_connect_success_and_failure():
    print("\nTest: /api/tuya/connect success and failure paths")
    srv = fresh_server_module()
    fake = FakeTuyaClient()
    srv.set_tuya_client_factory(lambda: fake)
    client = srv.app.test_client()

    resp = client.post("/api/tuya/connect", json={
        "access_id": "id", "access_secret": "secret", "api_endpoint": "https://x"
    })
    check("success connect returns 200", resp.status_code == 200)
    check("state.tuya_connected is True", srv.state.tuya_connected is True)

    fake.should_fail_token = True
    resp2 = client.post("/api/tuya/connect", json={
        "access_id": "id", "access_secret": "wrong", "api_endpoint": "https://x"
    })
    check("failed connect returns 400", resp2.status_code == 400)
    check("state.tuya_connected is False after failure", srv.state.tuya_connected is False)


def test_devices_verify_and_map():
    print("\nTest: device verify returns live data points, map stores selection")
    srv = fresh_server_module()
    fake = FakeTuyaClient()
    srv.set_tuya_client_factory(lambda: fake)
    client = srv.app.test_client()
    client.post("/api/tuya/connect", json={
        "access_id": "id", "access_secret": "secret", "api_endpoint": "https://x"
    })

    resp = client.post("/api/devices/verify", json={
        "soil_sensor_id": "SOIL_ID", "xpr3ss_id": "VALVE_ID"
    })
    check("verify returns 200", resp.status_code == 200)
    body = resp.get_json()
    check("soil data points present", "humidity_value" in
          [dp["code"] for dp in body["devices"]["soil_sensor"]["data_points"]])
    check("state.devices_verified True", srv.state.devices_verified is True)

    resp2 = client.post("/api/devices/map", json={
        "soil_moisture_dp_code": "humidity_value",
        "soil_temperature_dp_code": "temp_current",
        "valve_switch_dp_code": "switch",
    })
    check("map returns 200", resp2.status_code == 200)
    check("state.devices_mapped True", srv.state.devices_mapped is True)


def test_automation_start_requires_confirm_and_readiness():
    print("\nTest: automation start blocked without confirm / readiness")
    srv = fresh_server_module()
    client = srv.app.test_client()

    resp = client.post("/api/automation/start", json={})
    check("missing confirm -> 400", resp.status_code == 400)

    resp2 = client.post("/api/automation/start", json={"confirm": True})
    check("not ready (no devices) -> 400", resp2.status_code == 400)


def test_full_cycle_dry_run_waters_when_dry():
    print("\nTest: full cycle in dry-run correctly decides WATER_START but sends no real command")
    srv = fresh_server_module()
    fake = FakeTuyaClient()
    fake.soil_status = [{"code": "humidity_value", "value": 15}]  # dry
    srv.set_tuya_client_factory(lambda: fake)
    client = srv.app.test_client()

    client.post("/api/tuya/connect", json={"access_id": "i", "access_secret": "s", "api_endpoint": "https://x"})
    client.post("/api/devices/verify", json={"soil_sensor_id": "SOIL_ID", "xpr3ss_id": "VALVE_ID"})
    client.post("/api/devices/map", json={
        "soil_moisture_dp_code": "humidity_value",
        "valve_switch_dp_code": "switch",
    })
    client.post("/api/automation/settings", json={"dry_run": True, "moisture_threshold_percent": 30})

    record = srv.run_one_cycle()
    check("decision is WATER_START", record["action"] == "WATER_START")
    check("dry_run flag recorded True", record["dry_run"] is True)
    check("no real command sent to fake client", len(fake.commands_sent) == 0)

    snapshot = srv.state.get_status_snapshot()
    check("dashboard status shows moisture 15", snapshot["moisture_percent"] == 15)


def test_full_cycle_live_run_sends_real_command():
    print("\nTest: full cycle in LIVE mode sends a real ON command")
    srv = fresh_server_module()
    fake = FakeTuyaClient()
    fake.soil_status = [{"code": "humidity_value", "value": 10}]  # very dry
    srv.set_tuya_client_factory(lambda: fake)
    client = srv.app.test_client()

    client.post("/api/tuya/connect", json={"access_id": "i", "access_secret": "s", "api_endpoint": "https://x"})
    client.post("/api/devices/verify", json={"soil_sensor_id": "SOIL_ID", "xpr3ss_id": "VALVE_ID"})
    client.post("/api/devices/map", json={
        "soil_moisture_dp_code": "humidity_value",
        "valve_switch_dp_code": "switch",
    })
    client.post("/api/automation/settings", json={"dry_run": False, "moisture_threshold_percent": 30})

    record = srv.run_one_cycle()
    check("decision is WATER_START", record["action"] == "WATER_START")
    check("real command WAS sent", len(fake.commands_sent) == 1)
    check("command turns switch True",
          fake.commands_sent[0][1] == [{"code": "switch", "value": True}])
    check("fake device now reports valve on", fake.valve_status[0]["value"] is True)


def test_watchdog_force_stop_end_to_end():
    print("\nTest: watchdog force-stops an overrunning valve via a real cycle")
    srv = fresh_server_module()
    fake = FakeTuyaClient()
    fake.soil_status = [{"code": "humidity_value", "value": 10}]
    fake.valve_status = [{"code": "switch", "value": True}]  # already on
    srv.set_tuya_client_factory(lambda: fake)
    client = srv.app.test_client()

    client.post("/api/tuya/connect", json={"access_id": "i", "access_secret": "s", "api_endpoint": "https://x"})
    client.post("/api/devices/verify", json={"soil_sensor_id": "SOIL_ID", "xpr3ss_id": "VALVE_ID"})
    client.post("/api/devices/map", json={
        "soil_moisture_dp_code": "humidity_value",
        "valve_switch_dp_code": "switch",
    })
    client.post("/api/automation/settings", json={
        "dry_run": False, "max_irrigation_duration_minutes": 0.001  # ~60ms, so it's already "expired"
    })

    # Simulate that watering started a while ago
    srv.history.record_watering_start()
    time.sleep(0.1)

    record = srv.run_one_cycle()
    check("decision is WATCHDOG_FORCE_STOP", record["action"] == "WATCHDOG_FORCE_STOP")
    check("real OFF command sent", fake.commands_sent[-1][1] == [{"code": "switch", "value": False}])
    check("fake device now reports valve off", fake.valve_status[0]["value"] is False)


def test_emergency_stop_forces_off_even_if_not_running():
    print("\nTest: emergency stop sends OFF and halts automation regardless of prior state")
    srv = fresh_server_module()
    fake = FakeTuyaClient()
    fake.valve_status = [{"code": "switch", "value": True}]
    srv.set_tuya_client_factory(lambda: fake)
    client = srv.app.test_client()

    client.post("/api/tuya/connect", json={"access_id": "i", "access_secret": "s", "api_endpoint": "https://x"})
    client.post("/api/devices/verify", json={"soil_sensor_id": "SOIL_ID", "xpr3ss_id": "VALVE_ID"})
    client.post("/api/devices/map", json={
        "soil_moisture_dp_code": "humidity_value",
        "valve_switch_dp_code": "switch",
    })

    resp = client.post("/api/automation/emergency-stop", json={})
    check("emergency stop returns 200", resp.status_code == 200)
    check("OFF command was sent", fake.commands_sent[-1][1] == [{"code": "switch", "value": False}])
    check("automation_running is False", srv.state.automation_running is False)


def test_manual_control_blocked_while_automation_running():
    print("\nTest: manual control refused while automation is active")
    srv = fresh_server_module()
    fake = FakeTuyaClient()
    srv.set_tuya_client_factory(lambda: fake)
    client = srv.app.test_client()
    client.post("/api/tuya/connect", json={"access_id": "i", "access_secret": "s", "api_endpoint": "https://x"})
    client.post("/api/devices/verify", json={"soil_sensor_id": "SOIL_ID", "xpr3ss_id": "VALVE_ID"})
    client.post("/api/devices/map", json={
        "soil_moisture_dp_code": "humidity_value",
        "valve_switch_dp_code": "switch",
    })

    srv.state.try_start_automation()  # simulate running without spawning real thread
    resp = client.post("/api/automation/manual", json={"action": "on"})
    check("manual control blocked with 400", resp.status_code == 400)


def test_config_persists_across_restart():
    print("\nTest: config persists to disk and reloads on fresh AppState")
    srv = fresh_server_module()
    fake = FakeTuyaClient()
    srv.set_tuya_client_factory(lambda: fake)
    client = srv.app.test_client()
    client.post("/api/tuya/connect", json={"access_id": "abc", "access_secret": "s", "api_endpoint": "https://x"})
    client.post("/api/devices/verify", json={"soil_sensor_id": "SOIL_ID", "xpr3ss_id": "VALVE_ID"})
    client.post("/api/devices/map", json={
        "soil_moisture_dp_code": "humidity_value",
        "valve_switch_dp_code": "switch",
    })

    from app_state import AppState
    reloaded = AppState()
    check("reloaded tuya_access_id matches", reloaded.tuya_access_id == "abc")
    check("reloaded devices_mapped True", reloaded.devices_mapped is True)
    check("reloaded soil_moisture_dp_code matches", reloaded.soil_moisture_dp_code == "humidity_value")


if __name__ == "__main__":
    test_connect_requires_all_fields()
    test_connect_success_and_failure()
    test_devices_verify_and_map()
    test_automation_start_requires_confirm_and_readiness()
    test_full_cycle_dry_run_waters_when_dry()
    test_full_cycle_live_run_sends_real_command()
    test_watchdog_force_stop_end_to_end()
    test_emergency_stop_forces_off_even_if_not_running()
    test_manual_control_blocked_while_automation_running()
    test_config_persists_across_restart()

    print(f"\n{'='*50}\n{passed} passed, {failed} failed\n{'='*50}")

    os.chdir(PROJECT_DIR)
    for d in _ALL_TEST_DIRS:
        shutil.rmtree(d, ignore_errors=True)

    if failed:
        sys.exit(1)
