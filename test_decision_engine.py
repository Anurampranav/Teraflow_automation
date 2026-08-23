"""Unit tests for decision_engine.evaluate() - pure logic, no I/O."""
import time
from decision_engine import evaluate, Action

DEFAULTS = dict(moisture_threshold_percent=30, cooldown_seconds=3600,
                 max_duration_seconds=600, stale_data_seconds=1800)
passed = failed = 0

def check(name, cond):
    global passed, failed
    if cond: passed += 1; print(f"  PASS: {name}")
    else: failed += 1; print(f"  FAIL: {name}")

def t1():
    now = time.time()
    d = evaluate(moisture_percent=24, sensor_last_report_ts=now-60, valve_is_on_now=False,
                 valve_on_duration_seconds=None, last_watering_stop_ts=now-12*3600, now_ts=now, **DEFAULTS)
    check("Scenario1 WATER_START", d.action == Action.WATER_START)

def t2():
    now = time.time()
    d = evaluate(moisture_percent=65, sensor_last_report_ts=now-60, valve_is_on_now=False,
                 valve_on_duration_seconds=None, last_watering_stop_ts=None, now_ts=now, **DEFAULTS)
    check("Scenario2 SKIP_MOISTURE_OK", d.action == Action.WATER_SKIP_MOISTURE_OK)

def t3():
    now = time.time()
    d = evaluate(moisture_percent=27, sensor_last_report_ts=now-60, valve_is_on_now=False,
                 valve_on_duration_seconds=None, last_watering_stop_ts=now-15*60, now_ts=now, **DEFAULTS)
    check("Scenario3 SKIP_COOLDOWN", d.action == Action.WATER_SKIP_COOLDOWN)

def t4():
    now = time.time()
    d = evaluate(moisture_percent=10, sensor_last_report_ts=now-2*3600, valve_is_on_now=False,
                 valve_on_duration_seconds=None, last_watering_stop_ts=None, now_ts=now, **DEFAULTS)
    check("Stale data blocks even dry soil", d.action == Action.WATER_SKIP_STALE_DATA)

def t5():
    now = time.time()
    d = evaluate(moisture_percent=10, sensor_last_report_ts=now-60, valve_is_on_now=True,
                 valve_on_duration_seconds=900, last_watering_stop_ts=None, now_ts=now, **DEFAULTS)
    check("Watchdog overrides dry soil", d.action == Action.WATCHDOG_FORCE_STOP)

for f in (t1,t2,t3,t4,t5): f()
print(f"\n{passed} passed, {failed} failed")
if failed: exit(1)
