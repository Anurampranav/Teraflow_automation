(function () {
  "use strict";

  const API = {
    connect: (body) => post("/api/tuya/connect", body),
    verify: (body) => post("/api/devices/verify", body),
    map: (body) => post("/api/devices/map", body),
    settings: (body) => post("/api/automation/settings", body),
    start: (body) => post("/api/automation/start", body),
    stop: (body) => post("/api/automation/stop", body),
    emergencyStop: () => post("/api/automation/emergency-stop", {}),
    manual: (body) => post("/api/automation/manual", body),
    state: () => get("/api/state"),
    logs: (limit) => get(`/api/logs?limit=${limit || 50}`),
  };

  async function post(url, body) {
    const resp = await fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body || {}),
    });
    let data;
    try { data = await resp.json(); } catch (e) { data = {}; }
    return { ok: resp.ok, status: resp.status, data };
  }

  async function get(url) {
    const resp = await fetch(url);
    let data;
    try { data = await resp.json(); } catch (e) { data = {}; }
    return { ok: resp.ok, status: resp.status, data };
  }

  // ---------- Wizard navigation ----------
  let currentStep = 1;
  let deviceData = null; // holds live data points returned by verify

  function goToStep(n) {
    currentStep = n;
    document.querySelectorAll(".wpanel").forEach(p => p.classList.remove("active"));
    document.getElementById(`panel-${n}`).classList.add("active");
    document.querySelectorAll(".wstep").forEach(s => {
      const step = parseInt(s.dataset.step, 10);
      s.classList.toggle("active", step === n);
      s.classList.toggle("done", step < n);
    });
  }

  document.querySelectorAll("[data-back]").forEach(btn => {
    btn.addEventListener("click", () => goToStep(parseInt(btn.dataset.back, 10)));
  });

  function setError(step, message) {
    document.getElementById(`err-${step}`).textContent = message || "";
  }

  // ---------- Step 1: connect ----------
  document.getElementById("btn-connect").addEventListener("click", async () => {
    setError(1, "");
    const access_id = document.getElementById("accessId").value.trim();
    const access_secret = document.getElementById("accessSecret").value.trim();
    const api_endpoint = document.getElementById("apiEndpoint").value;

    if (!access_id || !access_secret) {
      setError(1, "Access ID and Secret are both required.");
      return;
    }

    const btn = document.getElementById("btn-connect");
    btn.disabled = true; btn.textContent = "Connecting…";
    const res = await API.connect({ access_id, access_secret, api_endpoint });
    btn.disabled = false; btn.textContent = "Connect";

    if (!res.ok) {
      setError(1, res.data.error || "Connection failed. Check your credentials and try again.");
      return;
    }
    goToStep(2);
  });

  // ---------- Step 2: verify devices ----------
  document.getElementById("btn-verify").addEventListener("click", async () => {
    setError(2, "");
    const soil_sensor_id = document.getElementById("soilSensorId").value.trim();
    const xpr3ss_id = document.getElementById("xpr3ssId").value.trim();

    if (!soil_sensor_id || !xpr3ss_id) {
      setError(2, "Both device IDs are required.");
      return;
    }

    const btn = document.getElementById("btn-verify");
    btn.disabled = true; btn.textContent = "Verifying…";
    const res = await API.verify({ soil_sensor_id, xpr3ss_id });
    btn.disabled = false; btn.textContent = "Verify devices";

    if (!res.ok) {
      setError(2, res.data.error || "Could not verify one or both devices.");
      return;
    }

    deviceData = res.data.devices;
    populateDpDropdowns();
    goToStep(3);
  });

  function populateDpDropdowns() {
    const soilPoints = deviceData.soil_sensor.data_points;
    const valvePoints = deviceData.xpr3ss.data_points;

    document.getElementById("soilDpPreview").textContent =
      "SOIL SENSOR data points:\n" +
      soilPoints.map(dp => `  ${dp.code} = ${JSON.stringify(dp.value)}`).join("\n");

    document.getElementById("valveDpPreview").textContent =
      "XPR3SS data points:\n" +
      valvePoints.map(dp => `  ${dp.code} = ${JSON.stringify(dp.value)}`).join("\n");

    fillSelect("moistureCode", soilPoints.map(dp => dp.code), guessCode(soilPoints, ["moisture", "humidity"]));
    fillSelect("temperatureCode", ["(none)", ...soilPoints.map(dp => dp.code)], guessCode(soilPoints, ["temp"]) || "(none)");
    fillSelect("switchCode", valvePoints.map(dp => dp.code), guessCode(valvePoints, ["switch"]));
  }

  function guessCode(points, keywords) {
    const match = points.find(dp => keywords.some(k => dp.code.toLowerCase().includes(k)));
    return match ? match.code : null;
  }

  function fillSelect(id, options, preferred) {
    const el = document.getElementById(id);
    el.innerHTML = options.map(o => `<option value="${o}">${o}</option>`).join("");
    if (preferred && options.includes(preferred)) el.value = preferred;
  }

  // ---------- Step 3: DP mapping ----------
  document.getElementById("btn-map").addEventListener("click", async () => {
    setError(3, "");
    const soil_moisture_dp_code = document.getElementById("moistureCode").value;
    const tempSel = document.getElementById("temperatureCode").value;
    const soil_temperature_dp_code = tempSel === "(none)" ? "" : tempSel;
    const valve_switch_dp_code = document.getElementById("switchCode").value;

    const btn = document.getElementById("btn-map");
    btn.disabled = true; btn.textContent = "Saving…";
    const res = await API.map({ soil_moisture_dp_code, soil_temperature_dp_code, valve_switch_dp_code });
    btn.disabled = false; btn.textContent = "Save mapping";

    if (!res.ok) {
      setError(3, res.data.error || "Could not save mapping.");
      return;
    }
    goToStep(4);
  });

  // ---------- Step 4: settings ----------
  document.getElementById("btn-save-settings").addEventListener("click", async () => {
    setError(4, "");
    const body = {
      moisture_threshold_percent: parseFloat(document.getElementById("setThreshold").value),
      poll_interval_minutes: parseFloat(document.getElementById("setPoll").value),
      cooldown_minutes: parseFloat(document.getElementById("setCooldown").value),
      max_irrigation_duration_minutes: parseFloat(document.getElementById("setMaxDuration").value),
      stale_data_minutes: parseFloat(document.getElementById("setStale").value),
      dry_run: document.getElementById("setDryRun").checked,
    };

    const btn = document.getElementById("btn-save-settings");
    btn.disabled = true; btn.textContent = "Saving…";
    const res = await API.settings(body);
    btn.disabled = false; btn.textContent = "Save settings";

    if (!res.ok) {
      setError(4, res.data.error || "Could not save settings.");
      return;
    }
    showDashboard();
  });

  document.getElementById("btn-edit-settings").addEventListener("click", () => {
    document.getElementById("dashboard").style.display = "none";
    document.getElementById("wizard").style.display = "block";
    goToStep(4);
  });

  // ---------- Show dashboard ----------
  function showDashboard() {
    document.getElementById("wizard").style.display = "none";
    document.getElementById("dashboard").style.display = "block";
    buildGaugeTicks();
    refreshState();
    refreshLogs();
    startPolling();
  }

  // ---------- Gauge ----------
  function buildGaugeTicks() {
    const ticksGroup = document.getElementById("ticks");
    if (ticksGroup.childElementCount > 0) return; // already built
    const tickCount = 24;
    for (let i = 0; i <= tickCount; i++) {
      const angle = (-215 + (250 * i / tickCount)) * Math.PI / 180;
      const cx = 90, cy = 90, rOuter = 84, rInner = i % 6 === 0 ? 78 : 80.5;
      const x1 = cx + rInner * Math.cos(angle), y1 = cy + rInner * Math.sin(angle);
      const x2 = cx + rOuter * Math.cos(angle), y2 = cy + rOuter * Math.sin(angle);
      const line = document.createElementNS("http://www.w3.org/2000/svg", "line");
      line.setAttribute("x1", x1); line.setAttribute("y1", y1);
      line.setAttribute("x2", x2); line.setAttribute("y2", y2);
      line.setAttribute("stroke", "#383c3f");
      line.setAttribute("stroke-width", i % 6 === 0 ? "2" : "1");
      ticksGroup.appendChild(line);
    }
  }

  const CIRCUMFERENCE = 339.3;
  function setGauge(percent) {
    const hasValue = percent !== null && percent !== undefined;
    const p = Math.max(0, Math.min(100, hasValue ? percent : 0));
    const fill = document.getElementById("gaugeFill");
    const offset = CIRCUMFERENCE - (CIRCUMFERENCE * p / 100);
    fill.style.strokeDasharray = CIRCUMFERENCE;
    fill.style.strokeDashoffset = hasValue ? offset : CIRCUMFERENCE;
    let color = "#c06a5c";
    if (p >= 50) color = "#7fa0bf";
    else if (p >= 30) color = "#cf9c54";
    fill.setAttribute("stroke", color);
    document.getElementById("gaugeValue").textContent = hasValue ? Math.round(percent) + "%" : "—";
  }

  // ---------- Formatting ----------
  function fmtDuration(seconds) {
    if (seconds === null || seconds === undefined) return "—";
    const s = Math.max(0, Math.floor(seconds));
    const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60), sec = s % 60;
    if (h > 0) return `${h}h ${m}m`;
    if (m > 0) return `${m}m ${sec}s`;
    return `${sec}s`;
  }

  function fmtAgo(ts, nowTs) {
    if (!ts) return "—";
    const diff = nowTs - ts;
    if (diff < 60) return "just now";
    const m = Math.floor(diff / 60);
    if (m < 60) return m + "m ago";
    const h = Math.floor(m / 60);
    return h + "h " + (m % 60) + "m ago";
  }

  function actionLabel(action) {
    const map = {
      WATER_START: "Watering started",
      WATER_SKIP_STALE_DATA: "Skipped — stale data",
      WATER_SKIP_ALREADY_ON: "Skipped — already on",
      WATER_SKIP_COOLDOWN: "Skipped — cooldown",
      WATER_SKIP_MOISTURE_OK: "Skipped — moisture OK",
      WATCHDOG_FORCE_STOP: "Watchdog force-stop",
      AUTOMATION_STOPPED: "Automation stopped",
      EMERGENCY_STOP: "Emergency stop",
      MANUAL_ON: "Manual ON",
      MANUAL_OFF: "Manual OFF",
      NO_ACTION: "No action",
    };
    return map[action] || action || "Unknown";
  }

  function markerClass(action, cycleResult) {
    if (cycleResult === "ERROR" || cycleResult === "COMMAND_ERROR") return "error";
    if (action === "WATER_START" || action === "MANUAL_ON") return "water";
    if (action === "WATCHDOG_FORCE_STOP" || action === "EMERGENCY_STOP" || action === "MANUAL_OFF") return "stop";
    return "skip";
  }

  // ---------- Live polling ----------
  let pollTimer = null;
  let latestState = null;

  function startPolling() {
    if (pollTimer) return;
    pollTimer = setInterval(() => {
      refreshState();
      refreshLogs();
    }, 4000);
    // Also tick the "on for" duration every second between polls for a live feel.
    setInterval(tickDurationDisplay, 1000);
  }

  async function refreshState() {
    const res = await API.state();
    if (!res.ok) {
      setStatusPill("error", "Connection lost");
      return;
    }
    latestState = res.data;
    renderState(latestState);
  }

  async function refreshLogs() {
    const res = await API.logs(50);
    if (!res.ok) return;
    renderLogs(res.data.logs || []);
  }

  function setStatusPill(kind, text) {
    const pill = document.getElementById("statusPill");
    pill.className = "status-pill " + kind;
    document.getElementById("statusText").textContent = text;
  }

  function renderState(s) {
    setGauge(s.moisture_percent);
    document.getElementById("tempValue").textContent =
      (s.temperature !== null && s.temperature !== undefined) ? s.temperature + "°" : "—";

    const valveStateEl = document.getElementById("valveState");
    const valveStateText = document.getElementById("valveStateText");
    const valveSub = document.getElementById("valveSub");
    if (s.valve_on) {
      valveStateEl.classList.add("on");
      valveStateText.textContent = "Valve on";
      valveSub.textContent = "XPR3SS · running";
    } else {
      valveStateEl.classList.remove("on");
      valveStateText.textContent = "Valve off";
      valveSub.textContent = "XPR3SS · idle";
    }

    document.getElementById("lastCycle").textContent = fmtAgo(s.last_cycle_ts, s.server_time);

    document.getElementById("thresholdValue").textContent =
      s.automation_settings.moisture_threshold_percent + "%";
    document.getElementById("pollValue").textContent =
      s.automation_settings.poll_interval_minutes + " min";

    const runningEl = document.getElementById("automationStateValue");
    const subEl = document.getElementById("automationStateSub");
    const toggleBtn = document.getElementById("btn-toggle-automation");
    if (s.automation_running) {
      runningEl.textContent = "Running";
      subEl.textContent = s.dry_run ? "Dry-run mode" : "Live — sending real commands";
      toggleBtn.textContent = "Stop Automation";
      toggleBtn.classList.remove("primary");
      setStatusPill(s.dry_run ? "warn" : "live", s.dry_run ? "Dry-run active" : "Automation live");
    } else {
      runningEl.textContent = "Stopped";
      subEl.textContent = "Not running";
      toggleBtn.textContent = "Start Automation";
      toggleBtn.classList.add("primary");
      setStatusPill("", "Connected · idle");
    }

    document.getElementById("dryRunBanner").style.display = s.dry_run ? "flex" : "none";

    document.getElementById("btn-manual-on").disabled = s.automation_running;
    document.getElementById("btn-manual-off").disabled = s.automation_running;

    tickDurationDisplay();
  }

  function tickDurationDisplay() {
    if (!latestState) return;
    const el = document.getElementById("onDuration");
    if (latestState.valve_on && latestState.valve_on_since_ts) {
      const elapsed = (Date.now() / 1000) - latestState.valve_on_since_ts;
      el.textContent = fmtDuration(elapsed);
    } else {
      el.textContent = "—";
    }
  }

  function renderLogs(logs) {
    const listEl = document.getElementById("logList");
    if (!logs.length) {
      listEl.innerHTML = '<div class="empty-state"><p>No activity yet</p><p>Once automation starts, every decision will appear here.</p></div>';
      document.getElementById("logCount").textContent = "0 entries";
      return;
    }
    listEl.innerHTML = logs.map(entry => {
      const time = new Date(entry.timestamp * 1000).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
      const moisture = (entry.moisture_percent !== null && entry.moisture_percent !== undefined)
        ? entry.moisture_percent.toFixed(1) + "%" : "";
      return `
        <div class="log-row">
          <span class="log-time">${time}</span>
          <span class="log-marker ${markerClass(entry.action, entry.cycle_result)}"></span>
          <span class="log-text">
            <div class="log-action">${actionLabel(entry.action)}</div>
            <div class="log-reason">${entry.reason || entry.error || ""}</div>
          </span>
          <span class="log-moisture">${moisture}</span>
        </div>`;
    }).join("");
    document.getElementById("logCount").textContent = `${logs.length} entries`;
  }

  // ---------- Controls ----------
  const modal = document.getElementById("confirmModal");

  document.getElementById("btn-toggle-automation").addEventListener("click", async () => {
    if (latestState && latestState.automation_running) {
      await API.stop();
      refreshState();
      return;
    }
    const dryRun = latestState ? latestState.dry_run : true;
    document.getElementById("confirmModalText").textContent = dryRun
      ? "This starts the automation loop in dry-run mode: it will log every decision but will NOT send real commands to your valve."
      : "This will let the system send REAL ON/OFF commands to your XPR3SS valve based on live sensor readings, without asking you each time.";
    modal.style.display = "flex";
  });

  document.getElementById("btn-confirm-cancel").addEventListener("click", () => {
    modal.style.display = "none";
  });

  document.getElementById("btn-confirm-yes").addEventListener("click", async () => {
    modal.style.display = "none";
    const res = await API.start({ confirm: true });
    if (!res.ok) {
      alert(res.data.error || "Could not start automation.");
      return;
    }
    refreshState();
  });

  document.getElementById("btn-emergency").addEventListener("click", async () => {
    if (!confirm("Force the valve OFF and stop automation immediately?")) return;
    const res = await API.emergencyStop();
    if (!res.ok) {
      alert(res.data.error || "Emergency stop command failed. Check the valve manually.");
    }
    refreshState();
    refreshLogs();
  });

  document.getElementById("btn-manual-on").addEventListener("click", async () => {
    const res = await API.manual({ action: "on" });
    if (!res.ok) alert(res.data.error || "Manual ON failed.");
    refreshState(); refreshLogs();
  });

  document.getElementById("btn-manual-off").addEventListener("click", async () => {
    const res = await API.manual({ action: "off" });
    if (!res.ok) alert(res.data.error || "Manual OFF failed.");
    refreshState(); refreshLogs();
  });

  // ---------- Initial load: check if already configured (server restart case) ----------
  (async function init() {
    const res = await API.state();
    if (res.ok && res.data.tuya_connected && res.data.devices_mapped) {
      showDashboard();
    }
  })();

})();
