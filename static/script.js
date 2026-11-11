const $ = s => document.querySelector(s);
const C = {g: "#22c55e", c: "#22d3ee", a: "#f59e0b", r: "#ef4444"};
let timer = null, busy = false, charts = {};

async function api(url, body) {
  const opt = body === undefined ? {} : {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify(body)};
  const r = await fetch(url, opt), j = await r.json();
  if (!r.ok) throw new Error((j.errors || ["Request failed"]).join("; "));
  return j;
}
function chart(id, type, labels, sets, yMax) {
  if (charts[id]) charts[id].destroy();
  charts[id] = new Chart($("#" + id), {
    type, data: {labels, datasets: sets.map(s => ({...s, borderWidth: 2, pointRadius: 0, tension: .3, backgroundColor: s.backgroundColor || s.borderColor}))},
    options: {animation: false, responsive: true, plugins: {legend: {labels: {color: "#8fa3c4"}}},
      scales: {x: {ticks: {color: "#8fa3c4", maxTicksLimit: 8}, grid: {color: "#1e3358"}}, y: {max: yMax, beginAtZero: true, ticks: {color: "#8fa3c4"}, grid: {color: "#1e3358"}}}}});
}
function render(d) {
  const s = d.state, c = d.chart;
  $("#time").textContent = s.time; $("#wind").textContent = s.wind + " m/s";
  $("#gen").textContent = s.gen_w.toFixed(2) + " W"; $("#energy").textContent = s.energy_j.toFixed(1) + " J";
  $("#volt").textContent = s.voltage.toFixed(2) + " V"; $("#cons").textContent = (s.cons_w * 1000).toFixed(1) + " mW";
  $("#up").textContent = s.uptime_pct + " %"; $("#tx").textContent = s.tx_rate + " % (" + s.tx_ok + "/" + s.tx_attempts + ")";
  $("#th").textContent = s.temp + " °C / " + s.hum + " %"; $("#pct").textContent = s.charge_pct + " %";
  $("#pbar").style.width = s.charge_pct + "%"; $("#lasttx").textContent = "Last packet: " + s.last_tx;
  $("#bal").textContent = `harvested ${s.harvested_j} − consumed ${s.consumed_j} − spilled ${s.curtailed_j} = stored change; error ${s.balance_error_j.toExponential(1)} J`;
  const m = $("#mode"); m.textContent = s.mode; m.className = "badge " + s.mode.split(" ")[0];
  chart("c1", "line", c.labels, [{label: "Generated (W)", data: c.gen, borderColor: C.g}, {label: "Consumed (W)", data: c.cons, borderColor: C.a}]);
  chart("c2", "line", c.labels, [{label: "Charge %", data: c.pct, borderColor: C.c, fill: true, backgroundColor: "rgba(34,211,238,.15)"}], 100);
  chart("c3", "line", c.labels, [{label: "Wind (m/s)", data: c.wind, borderColor: C.g}]);
}
async function tick() {
  if (busy) return; busy = true;
  try { render(await api("/api/step", {steps: +$("#speed").value})); $("#err").textContent = ""; }
  catch (e) { $("#err").textContent = e.message; stop(); }
  busy = false;
}
function start() { if (!timer) timer = setInterval(tick, 1000); tick(); }
function stop() { clearInterval(timer); timer = null; }
async function act(fn) { try { render(await fn()); $("#err").textContent = ""; } catch (e) { $("#err").textContent = e.message; } }
async function setWind() {
  $("#wval").textContent = (+$("#wslider").value).toFixed(1) + " m/s";
  await act(() => api("/api/wind", {manual: $("#manual").checked, speed: $("#wslider").value}));
}
$("#start").onclick = start; $("#pause").onclick = stop;
$("#reset").onclick = () => { stop(); act(() => api("/api/reset", {})); };
$("#newwind").onclick = () => act(() => api("/api/new_wind", {}));
$("#manual").onchange = setWind; $("#wslider").oninput = setWind;

document.querySelectorAll("nav a").forEach(a => a.onclick = () => {
  document.querySelectorAll("nav a,.view").forEach(e => e.classList.remove("on"));
  a.classList.add("on"); $("#" + a.dataset.v).classList.add("on");
  if (a.dataset.v === "set") loadSettings();
});

async function loadSettings() {
  const d = await api("/api/config");
  $("#form").innerHTML = d.schema.map(f => `<label>${f.label}${f.unit ? " (" + f.unit + ")" : ""}
    <input type="number" step="any" name="${f.key}" min="${f.min}" max="${f.max}" value="${d.values[f.key]}"></label>`).join("");
}
$("#apply").onclick = async () => {
  const data = {};
  new FormData($("#form")).forEach((v, k) => data[k] = v);
  try { stop(); render(await api("/api/config", data)); $("#seterr").textContent = ""; alert("Settings applied. Simulation restarted."); }
  catch (e) { $("#seterr").textContent = e.message; }
};

$("#run14").onclick = async () => {
  $("#anastat").textContent = "Simulating 20,160 minutes..."; $("#anaerr").textContent = "";
  try {
    const d = await api("/api/analytics", {}), h = d.hourly, days = d.daily;
    const lab = h.map((_, i) => `D${Math.floor(i / 24) + 1} ${i % 24}h`);
    chart("a1", "line", lab, [{label: "Generated (W)", data: h.map(x => x.gen), borderColor: C.g}, {label: "Consumed (W)", data: h.map(x => x.cons), borderColor: C.a}]);
    chart("a2", "line", lab, [{label: "Charge %", data: h.map(x => x.pct), borderColor: C.c}], 100);
    chart("a3", "line", lab, [{label: "Wind (m/s)", data: h.map(x => x.wind), borderColor: C.g}]);
    chart("a4", "bar", days.map(x => "Day " + x.day), [{label: "Uptime %", data: days.map(x => x.uptime), borderColor: C.g, backgroundColor: C.g}, {label: "Tx success %", data: days.map(x => x.tx_rate), borderColor: C.c, backgroundColor: C.c}], 100);
    const s = d.summary;
    $("#sumcards").innerHTML = [["14-day uptime", s.uptime_pct + " %"], ["Tx success", s.tx_rate + " % (" + s.tx_ok + "/" + s.tx_attempts + ")"],
      ["Harvested", (s.harvested_j / 1000).toFixed(1) + " kJ"], ["Consumed", (s.consumed_j / 1000).toFixed(1) + " kJ"],
      ["Spilled (storage full)", (s.curtailed_j / 1000).toFixed(1) + " kJ"], ["Conservation error", s.balance_error_j.toExponential(1) + " J"]]
      .map(x => `<div class="card"><span>${x[0]}</span><b>${x[1]}</b></div>`).join("");
    $("#daytbl tbody").innerHTML = days.map(x => `<tr><td>${x.day}</td><td>${x.avg_wind}</td><td>${x.harvested_j}</td><td>${x.consumed_j}</td><td>${x.curtailed_j}</td><td>${x.active_pct}</td><td>${x.low_pct}</td><td>${x.sleep_pct}</td><td>${x.uptime}</td><td>${x.ok}/${x.attempts}</td><td>${x.tx_rate}</td></tr>`).join("");
    $("#anastat").textContent = "Done.";
  } catch (e) { $("#anaerr").textContent = e.message; $("#anastat").textContent = ""; }
};
api("/api/state").then(render);
