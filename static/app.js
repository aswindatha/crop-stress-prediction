(function () {
  const POLL_MS = 2000;

  const el = (id) => document.getElementById(id);

  function setConnection(connected) {
    const wrap = el("connectionWrap");
    const dot = el("connectionDot");
    const label = el("serialStatus");
    if (!wrap) return;
    wrap.className = "connection " + (connected ? "connected" : "disconnected");
    label.textContent = connected ? "Hardware connected" : "Waiting for ESP32";
  }

  function setMotorState(on) {
    const stateEl = el("motorState");
    const tile = document.querySelector(".relay-motor");
    const onBtn = el("motorOn");
    const offBtn = el("motorOff");
    stateEl.textContent = on ? "ON" : "OFF";
    stateEl.className = "relay-state " + (on ? "state-on" : "state-off");
    if (tile) {
      tile.classList.remove("motor-on", "motor-off");
      tile.classList.add(on ? "motor-on" : "motor-off");
    }
    if (onBtn) onBtn.setAttribute("aria-pressed", on ? "true" : "false");
    if (offBtn) offBtn.setAttribute("aria-pressed", !on ? "true" : "false");
  }

  function setLightState(on) {
    const stateEl = el("lightState");
    const tile = document.querySelector(".relay-light");
    const onBtn = el("lightOn");
    const offBtn = el("lightOff");
    stateEl.textContent = on ? "ON" : "OFF";
    stateEl.className = "relay-state " + (on ? "state-on" : "state-off");
    if (tile) {
      tile.classList.remove("light-on", "light-off");
      tile.classList.add(on ? "light-on" : "light-off");
    }
    if (onBtn) onBtn.setAttribute("aria-pressed", on ? "true" : "false");
    if (offBtn) offBtn.setAttribute("aria-pressed", !on ? "true" : "false");
  }

  function setMoistureRing(percent) {
    const ring = document.getElementById("moistureRing");
    if (!ring) return;
    const p = Math.min(100, Math.max(0, percent));
    const dash = (p / 100) * 100;
    ring.style.strokeDasharray = dash + " 100";
  }

  function showToast(message) {
    const toast = el("toast");
    if (!toast) return;
    toast.textContent = message;
    toast.classList.add("visible");
    clearTimeout(toast._tid);
    toast._tid = setTimeout(() => {
      toast.classList.remove("visible");
    }, 2500);
  }

  function applyStatus(data) {
    setConnection(data.serial_connected === true);

    if (data.relay) {
      setMotorState(data.relay.motor);
      setLightState(data.relay.light);
    }

    el("motorName").value = data.motor_name || "";
    el("lightName").value = data.light_name || "";

    if (data.virtual) {
      const moisturePct = data.virtual.soil_moisture != null
        ? data.virtual.soil_moisture * 100
        : null;
      const moistureEl = el("soilMoisture");
      if (moistureEl) {
        moistureEl.textContent = moisturePct != null ? moisturePct.toFixed(1) + "%" : "—";
        moistureEl.classList.remove("skeleton");
      }
      setMoistureRing(moisturePct != null ? moisturePct : 0);

      const csiEl = el("csi");
      if (csiEl) {
        csiEl.textContent = data.virtual.csi != null ? data.virtual.csi : "—";
        csiEl.classList.remove("skeleton");
      }

      const waterEl = el("waterUsed");
      if (waterEl) {
        waterEl.textContent = data.virtual.water_liters_24h != null
          ? data.virtual.water_liters_24h + " L"
          : "—";
        waterEl.classList.remove("skeleton");
      }

      const powerEl = el("powerUsed");
      if (powerEl) {
        powerEl.textContent = data.virtual.power_kwh_24h != null
          ? data.virtual.power_kwh_24h + " kWh"
          : "—";
        powerEl.classList.remove("skeleton");
      }
    }

    if (data.predictions) {
      const predWater = el("predWater");
      const predPower = el("predPower");
      if (predWater) {
        predWater.textContent = data.predictions.water_liters != null
          ? data.predictions.water_liters + " L"
          : "—";
        predWater.classList.remove("skeleton");
      }
      if (predPower) {
        predPower.textContent = data.predictions.power_kwh != null
          ? data.predictions.power_kwh + " kWh"
          : "—";
        predPower.classList.remove("skeleton");
      }
    }

    const cropInfo = el("cropInfo");
    if (cropInfo) cropInfo.textContent = [data.crop, data.stage].filter(Boolean).join(" · ") || "";

    const lastUpdate = el("lastUpdate");
    if (lastUpdate) lastUpdate.textContent = "Updated " + new Date().toLocaleTimeString();
  }

  function setLoading(loading) {
    const ids = ["soilMoisture", "csi", "waterUsed", "powerUsed", "predWater", "predPower"];
    ids.forEach((id) => {
      const e = el(id);
      if (e) e.classList.toggle("skeleton", loading);
    });
    const moistureVal = el("soilMoisture");
    if (moistureVal && loading) moistureVal.textContent = "—";
    if (loading) setMoistureRing(0);
  }

  function fetchStatus() {
    fetch("/api/status")
      .then((r) => r.json())
      .then((d) => {
        setLoading(false);
        applyStatus(d);
      })
      .catch(() => {
        setLoading(false);
        setConnection(false);
      });
  }

  function toggle(device, state) {
    fetch("/api/toggle", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ device, state }),
    })
      .then((r) => r.json())
      .then((d) => {
        if (d.ok && d.relay) {
          setMotorState(d.relay.motor);
          setLightState(d.relay.light);
        }
      })
      .catch(() => {});
  }

  function saveNames() {
    const motor_name = (el("motorName") && el("motorName").value) ? el("motorName").value.trim() : "";
    const light_name = (el("lightName") && el("lightName").value) ? el("lightName").value.trim() : "";
    fetch("/api/rename", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ motor_name, light_name }),
    })
      .then((r) => r.json())
      .then((d) => {
        if (d.ok) {
          showToast("Names saved");
          fetchStatus();
        }
      })
      .catch(() => showToast("Save failed"));
  }

  el("motorOn").addEventListener("click", () => toggle("motor", true));
  el("motorOff").addEventListener("click", () => toggle("motor", false));
  el("lightOn").addEventListener("click", () => toggle("light", true));
  el("lightOff").addEventListener("click", () => toggle("light", false));
  if (el("saveNames")) el("saveNames").addEventListener("click", saveNames);

  setLoading(true);
  setConnection(false);
  fetchStatus();
  setInterval(fetchStatus, POLL_MS);
})();
