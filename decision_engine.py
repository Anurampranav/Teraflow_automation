"""
Decision engine for the irrigation automation.

Design principle: every path either returns an explicit, logged
decision or raises — there is no silent fallthrough. When in doubt,
the answer is always "do not water."
"""

from dataclasses import dataclass
from enum import Enum
from typing import Optional


class Action(str, Enum):
    WATER_START = "WATER_START"
    WATER_SKIP_STALE_DATA = "WATER_SKIP_STALE_DATA"
    WATER_SKIP_ALREADY_ON = "WATER_SKIP_ALREADY_ON"
    WATER_SKIP_COOLDOWN = "WATER_SKIP_COOLDOWN"
    WATER_SKIP_MOISTURE_OK = "WATER_SKIP_MOISTURE_OK"
    WATCHDOG_FORCE_STOP = "WATCHDOG_FORCE_STOP"
    NO_ACTION = "NO_ACTION"


@dataclass
class Decision:
    action: Action
    reason: str
    moisture_percent: Optional[float] = None
    temperature: Optional[float] = None


def evaluate(
    *,
    moisture_percent: Optional[float],
    sensor_last_report_ts: Optional[float],
    valve_is_on_now: bool,
    valve_on_duration_seconds: Optional[float],
    last_watering_stop_ts: Optional[float],
    now_ts: float,
    moisture_threshold_percent: float,
    cooldown_seconds: float,
    max_duration_seconds: float,
    stale_data_seconds: float,
) -> Decision:
    """
    Pure function: given the current world state, decide exactly one
    action. Called once per poll cycle. No side effects, no I/O -
    makes this trivially unit-testable.

    Order of checks (intentional):
      1. Watchdog: valve stuck on too long -> force stop, overrides everything
      2. Stale sensor data -> never water
      3. Valve already on -> do nothing further this cycle
      4. Cooldown -> don't re-water too soon
      5. Moisture at/above threshold -> no watering needed
      6. Otherwise -> water
    """

    # --- 1. Non-negotiable safety watchdog runs first, always ---
    if valve_is_on_now and valve_on_duration_seconds is not None:
        if valve_on_duration_seconds >= max_duration_seconds:
            return Decision(
                action=Action.WATCHDOG_FORCE_STOP,
                reason=(
                    f"Valve has been ON for {valve_on_duration_seconds:.0f}s, "
                    f"exceeding max allowed {max_duration_seconds:.0f}s. Forcing OFF."
                ),
                moisture_percent=moisture_percent,
            )

    # --- 2. Stale sensor data check ---
    if sensor_last_report_ts is None:
        return Decision(
            action=Action.WATER_SKIP_STALE_DATA,
            reason="No sensor report timestamp available at all. Refusing to water.",
        )
    data_age_seconds = now_ts - sensor_last_report_ts
    if data_age_seconds > stale_data_seconds:
        return Decision(
            action=Action.WATER_SKIP_STALE_DATA,
            reason=(
                f"Sensor data is {data_age_seconds:.0f}s old, exceeding stale "
                f"threshold of {stale_data_seconds:.0f}s. Refusing to water."
            ),
            moisture_percent=moisture_percent,
        )

    # --- 3. Already watering -> nothing else to decide this cycle ---
    if valve_is_on_now:
        return Decision(
            action=Action.WATER_SKIP_ALREADY_ON,
            reason="Valve is already ON; watchdog already checked duration above.",
            moisture_percent=moisture_percent,
        )

    # --- 4. Cooldown check ---
    if last_watering_stop_ts is not None:
        since_last_water = now_ts - last_watering_stop_ts
        if since_last_water < cooldown_seconds:
            return Decision(
                action=Action.WATER_SKIP_COOLDOWN,
                reason=(
                    f"Last watering ended {since_last_water:.0f}s ago, "
                    f"still within {cooldown_seconds:.0f}s cooldown."
                ),
                moisture_percent=moisture_percent,
            )

    # --- 5. Moisture check ---
    if moisture_percent is None:
        return Decision(
            action=Action.WATER_SKIP_STALE_DATA,
            reason="Moisture value missing/unparseable from sensor payload. Refusing to water.",
        )
    if moisture_percent >= moisture_threshold_percent:
        return Decision(
            action=Action.WATER_SKIP_MOISTURE_OK,
            reason=(
                f"Moisture {moisture_percent:.1f}% is at/above threshold "
                f"{moisture_threshold_percent:.1f}%. No watering needed."
            ),
            moisture_percent=moisture_percent,
        )

    # --- 6. All checks passed -> water ---
    return Decision(
        action=Action.WATER_START,
        reason=(
            f"Moisture {moisture_percent:.1f}% below threshold "
            f"{moisture_threshold_percent:.1f}%, no cooldown/staleness/duration "
            f"issue. Starting irrigation."
        ),
        moisture_percent=moisture_percent,
    )
