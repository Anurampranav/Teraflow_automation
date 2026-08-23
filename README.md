# TerraFlow — Smart Irrigation Dashboard

A self-hosted web dashboard that connects to Tuya Cloud, verifies your soil
sensor and XPR3SS irrigation valve live, and automates watering with a
tested, fail-safe decision engine — all through one browser page, on both
desktop and phone.

## What it does

1. **Connect** — enter your Tuya Cloud credentials once.
2. **Verify devices** — paste your two device IDs; the dashboard fetches
   their *live* data points from the real API so you can see exactly what
   your hardware reports.
3. **Map sensors** — pick which live field is moisture, temperature, and
   the valve switch from dropdowns built from real data, not guesses.
4. **Set thresholds** — moisture threshold, cooldown, max duration,
   stale-data window, poll interval, and a dry-run toggle.
5. **Start automation** — with an explicit confirmation step. From then on
   it runs in the background, polling Tuya Cloud on your configured
   interval and applying the same tested decision logic every cycle.
6. **Watch it live** — moisture gauge, valve on/off state and running
   duration, last cycle time, and a full timestamped activity log, all
   updating automatically in your browser.

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

**To use it from your phone**, make sure your phone is on the same Wi-Fi as
the computer running this, then find the computer's LAN IP (e.g.
`192.168.1.42`) and open `http://192.168.1.42:5000` on your phone.

## 3. Walk through the setup wizard

- **Step 1**: your Tuya IoT Platform Access ID/Secret and region endpoint
  (from your Cloud Project's Overview page).
- **Step 2**: your soil sensor's and XPR3SS's Device IDs (from the Devices
  tab in that same project).
- **Step 3**: the dashboard shows you the *actual* data points your devices
  reported — pick the correct moisture/temperature/switch fields from the
  dropdowns. This is the step most likely to need attention: cheap soil
  sensors often label moisture as generic `humidity_value` rather than
  `soil_moisture`, and some don't report temperature at all (map it to
  "(none)" if so — the automation will simply not use it).
- **Step 4**: set your thresholds. **Leave "Dry-run mode" checked** the
  first time. This makes the automation log every decision it would make
  without ever sending a real command to the valve.

## 4. Test in dry-run before going live

Once on the live dashboard, click **Start Automation** — with dry-run
checked, this is completely safe. Watch the activity log for at least a
full day/night cycle. Every decision (water, skip, why) is shown with full
reasoning. Only once you're confident in what it's deciding should you go
back to Settings, uncheck dry-run, and start automation again.

## 5. Safety features built in

- **Ordered, fail-safe decision logic**: stale sensor data, an
  already-running valve, and cooldown are all checked before moisture —
  and any of them can block watering even if the soil is genuinely dry.
- **Non-skippable watchdog**: force-stops the valve if it's been on longer
  than your configured max duration, independent of every other rule.
- **Emergency Stop button**: always visible, sends a real OFF command and
  halts automation immediately, regardless of current state.
- **Manual ON/OFF controls**: only enabled while automation is stopped, to
  avoid the automation and a manual click fighting each other.
- **Confirmation required** before automation can ever send real commands.
- **Every cycle is logged** — decision, reasoning, sensor values, whether a
  real command was sent — to `irrigation_log.jsonl`, viewable in the
  dashboard's Activity Log panel.

## Important limitations — please read

- **This is a local, single-user tool with no login.** `runtime_config.json`
  stores your Tuya Access ID and Secret in **plain text** on disk. Do not
  port-forward this server to the public internet or deploy it anywhere
  shared/multi-user as-is. It's built to run on your own trusted machine
  or home network.
- **The dashboard polls its own local `/api/state` every 4 seconds** (cheap,
  no Tuya calls) — but the *actual* Tuya Cloud API is only called once per
  your configured `poll_interval_minutes`, to protect your API quota. The
  gauge/log won't show a genuinely new sensor reading faster than that
  interval, by design.
- **If the server process stops** (crash, reboot, closed terminal),
  automation stops with it — there's no separate always-on service/daemon
  here. For a persistent setup, run it under a process manager service on the
  machine (e.g. `systemd` on Linux) rather than a bare terminal window, if
  you're comfortable with that setup — see your OS's documentation.
- **Tuya's free "Trial Edition" API quota** applies (roughly 26,000 calls/
  month for personal projects) — plenty for 2 devices polled every 10
  minutes, but be aware if you set the poll interval very short.

## Verifying it yourself

Two independent test suites are included:

```bash
python3 test_decision_engine.py   # pure decision logic, 5 core scenarios
python3 test_server.py            # full connect→verify→map→start→cycle
                                   # flow, using a fake Tuya client (no
                                   # real network calls), 30 assertions
```

Both should print `0 failed`. Run them any time you modify a threshold,
the decision logic, or a server endpoint.

## Files

| File | Purpose |
|---|---|
| `server.py` | Flask app: all API endpoints + background automation thread |
| `app_state.py` | Thread-safe shared state + config persistence |
| `decision_engine.py` | Pure, unit-tested decision logic |
| `tuya_client.py` | Signs and sends Tuya Cloud API requests |
| `state_store.py` | Persists last-watering timestamps across restarts |
| `audit_log.py` | Append-only JSON-lines decision log |
| `public/index.html` | Dashboard markup (wizard + live view) |
| `public/style.css` | Grey premium theme, responsive |
| `public/app.js` | Wizard flow, live polling, controls |
| `test_decision_engine.py` | Unit tests for decision logic |
| `test_server.py` | End-to-end API tests with a fake Tuya client |
| `runtime_config.json` | Generated on first setup — your credentials (gitignored) |
| `irrigation_log.jsonl` | Generated — full decision history (gitignored) |
| `irrigation_state.json` | Generated — watering timestamps (gitignored) |
