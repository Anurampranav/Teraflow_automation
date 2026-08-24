# TerraFlow — Smart Irrigation Dashboard

A self-hosted, ultra-premium web dashboard that connects to Tuya Cloud, verifies your soil sensor and XPR3SS irrigation valve live, and automates watering with a tested, fail-safe decision engine — featuring a left sidebar navigation layout and a responsive glassmorphism UI theme on both desktop and mobile.

## What it does

1. **Left Sidebar Navigation** — Access all core modules (**Dashboard**, **Setup & Devices**, **Automation Rules**, and **Activity Log**) directly from an accessible left navigation sidebar.
2. **Glassmorphism UI Theme** — Frosted translucent panels, ambient glow highlights, dynamic gauge animations, and crisp dark typography.
3. **Tuya Cloud Connect** — Enter your Tuya Cloud credentials once securely.
4. **Device Verification** — Paste your device IDs; the dashboard fetches their *live* data points from the real API so you can inspect hardware reports directly.
5. **Sensor Field Mapping** — Interactively map live moisture, temperature, and valve switch fields from device data points.
6. **Fail-Safe Automation Rules** — Set moisture thresholds, poll interval, cooldown between waterings, max irrigation duration, stale data cutoff, and dry-run safety mode.
7. **Live Dashboard & Audit Log** — Real-time moisture gauge, valve on/off state, cycle timers, manual controls, and a complete historical activity log.

## 1. Install !!

```bash
pip install -r requirements.txt
```

(If you get a "break-system-packages" error: `pip install -r requirements.txt --break-system-packages`)

## 2. Run

```bash
python3 server.py
```

Open **http://localhost:5000** in your browser.

**To use it from your phone**, make sure your phone is on the same Wi-Fi as the computer running this, then find the computer's LAN IP (e.g. `192.168.1.42`) and open `http://192.168.1.42:5000` on your phone.

## 3. Navigation & Modules

- **Dashboard**: Live moisture gauge, valve status, temperature readout, quick actions (Manual ON/OFF, Emergency Stop), and recent activity summary.
- **Setup & Devices**: 4-step wizard to connect Tuya Cloud, verify device IDs, map data points, and configure initial thresholds.
- **Automation Rules**: Fine-tune watering thresholds, poll frequency, safety timers, and dry-run execution preferences.
- **Activity Log**: Complete timestamped audit history of all sensor checks, automation decisions, and valve operations.

## 4. Test in dry-run before going live

Once on the dashboard, start automation with **Dry-run mode** enabled. This allows the decision engine to run every cycle, log its reasoning, and simulate watering without sending real commands to your hardware. Once verified, turn off dry-run in Automation Rules to go live.

## 5. Safety features built in

- **Ordered, fail-safe decision logic**: stale sensor data, an already-running valve, and cooldown are all checked before moisture — and any of them can block watering even if the soil is genuinely dry.
- **Non-skippable watchdog**: force-stops the valve if it's been on longer than your configured max duration, independent of every other rule.
- **Emergency Stop button**: always visible, sends a real OFF command and halts automation immediately, regardless of current state.
- **Manual ON/OFF controls**: only enabled while automation is stopped, to avoid conflict with the automated loop.
- **Confirmation required** before automation can ever send real commands.
- **Every cycle is logged** — decision, reasoning, sensor values, whether a real command was sent — to `irrigation_log.jsonl`, viewable in the Activity Log module.

## Files

| File | Purpose |
|---|---|
| `server.py` | Flask app: all API endpoints + background automation thread |
| `app_state.py` | Thread-safe shared state + config persistence |
| `decision_engine.py` | Pure, unit-tested decision logic |
| `tuya_client.py` | Signs and sends Tuya Cloud API requests |
| `state_store.py` | Persists last-watering timestamps across restarts |
| `audit_log.py` | Append-only JSON-lines decision log |
| `public/index.html` | Left sidebar markup + module view panels |
| `public/style.css` | Glassmorphism design system & responsive layout |
| `public/app.js` | Module navigation, live polling, wizard flow & controls |
| `test_decision_engine.py` | Unit tests for decision logic |
| `test_server.py` | End-to-end API tests with a fake Tuya client |
| `runtime_config.json` | Generated on first setup — credentials (gitignored) |
| `irrigation_log.jsonl` | Generated — full decision history (gitignored) |
| `irrigation_state.json` | Generated — watering timestamps (gitignored) |

