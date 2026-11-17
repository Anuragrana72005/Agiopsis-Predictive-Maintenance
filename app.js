const TABS = [["overview", "Overview", "A calm, one-page view of every server: who is healthy, who is at risk, and what to do next."], ["forecast", "Forecast", "Two models predict the next few hours. Try the slider to test a busier or quieter future."], ["analysis", "Analysis", "Trends, unusual spikes, daily rhythm and the best time to do maintenance."],
  ["compare", "Compare", "Compare any measure across the whole fleet against its safe limit."], ["tickets", "Tickets", "Problems we expect before they happen, with a suggested fix for each."], ["guide", "Guide", "How the system works, the safe limits, and what the terms mean."]];
const ML = { memory_usage: "Memory", cpu_usage: "CPU", disk_latency_ms: "Disk delay", temp_celsius: "Temperature" };
const UNIT = { memory_usage: "%", cpu_usage: "%", disk_latency_ms: " ms", temp_celsius: " °C" };
const STATUS = { HEALTHY: "Healthy", WARNING: "Watch", CRITICAL: "Critical" };
const COLORS = { "SRV-WEB-01": "#5fd6a4", "SRV-DB-01": "#8ea8ff", "SRV-AI-01": "#c9a6ff", "SRV-CACHE-01": "#e8c26a" };
const INFO = { "SRV-WEB-01": ["Web front-end", "Serves the website. Traffic rises and falls with the day.", "Should stay healthy. A good baseline to compare against."],
  "SRV-DB-01": ["Database", "Has a slow memory leak. Memory creeps up toward 95%.", "Expect a memory warning and an automatic ticket."],
  "SRV-AI-01": ["AI compute", "Runs heavy jobs. CPU and temperature climb as it wears.", "Watch CPU and temperature, especially at the afternoon peak."],
  "SRV-CACHE-01": ["Cache", "Fast storage with a burst of disk delay every 6 hours.", "Expect periodic disk-delay spikes that grow over time."] };
const S = { server: "SRV-DB-01", tab: "overview", fleet: [], tickets: [], filter: "open", req: 0, busy: false, log: [{ t: new Date(), m: "Dashboard started" }] };
const $ = (id) => document.getElementById(id);
const fmt = (n, d = 1) => (n == null ? "–" : Number(n).toFixed(d));
const esc = (s) => String(s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
const when = (t) => new Date(t).toLocaleString([], { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });
const metric = () => $("metric").value;
const cv = (n) => getComputedStyle(document.documentElement).getPropertyValue(n).trim();
const L = (x = {}) => ({ paper_bgcolor: "rgba(0,0,0,0)", plot_bgcolor: "rgba(0,0,0,0)", font: { color: cv("--text"), family: "Outfit, sans-serif", size: 12 },
  margin: { t: 10, r: 16, b: 40, l: 52 }, legend: { orientation: "h", y: -0.18 }, ...x, xaxis: { gridcolor: cv("--line"), ...(x.xaxis || {}) }, yaxis: { gridcolor: cv("--line"), ...(x.yaxis || {}) } });
const PC = { responsive: true, displaylogo: false };

async function api(path, opts) {
  const r = await fetch(path, opts);
  if (!r.ok) throw new Error((await r.json().catch(() => ({}))).detail || r.statusText);
  return r.json();
}
function toast(m) { S.log.unshift({ t: new Date(), m }); S.log.length = Math.min(S.log.length, 8); if (S.tab === "overview") drawActivity(); const d = document.createElement("div"); d.className = "toast"; d.textContent = m; $("toasts").append(d); setTimeout(() => d.remove(), 3600); }
function setLive(ok, t) { $("live-dot").classList.toggle("off", !ok); $("live-text").textContent = t; }

/* ---------- navigation ---------- */
function drawNav() {
  const open = S.tickets.filter((t) => t.status === "open").length;
  $("nav").innerHTML = TABS.map(([id, name]) => `<button class="nav-btn ${S.tab === id ? "active" : ""}" data-tab="${id}">${name}${id === "tickets" && open ? `<span class="count">${open}</span>` : ""}</button>`).join("");
  $("nav").querySelectorAll("button").forEach((b) => b.addEventListener("click", () => go(b.dataset.tab)));
}
function go(tab) {
  S.tab = tab;
  document.querySelectorAll("section[data-tab]").forEach((s) => s.classList.toggle("hidden", s.dataset.tab !== tab));
  const t = TABS.find((x) => x[0] === tab); $("page-title").textContent = t[1]; $("page-sub").textContent = t[2];
  document.querySelectorAll("[data-for]").forEach((e) => e.classList.toggle("hidden", !e.dataset.for.split(" ").includes(tab)));
  $("picker").classList.toggle("hidden", !["forecast", "analysis", "compare"].includes(tab));
  drawNav(); loadTab();
}
function loadTab() {
  drawProfile();
  ({ overview: drawOverview, forecast: loadForecast, analysis: loadAnalysis, compare: loadCompare, tickets: drawTickets, guide: () => {} })[S.tab]();
}
function drawPills() {
  $("pills").innerHTML = S.fleet.map((s) => `<button class="pill ${s.server_id === S.server ? "on" : ""}" data-id="${s.server_id}"><i style="background:${COLORS[s.server_id]}"></i>${s.server_id}</button>`).join("");
  $("pills").querySelectorAll("button").forEach((b) => b.addEventListener("click", () => { S.server = b.dataset.id; drawPills(); loadTab(); }));
}

/* ---------- overview ---------- */
const reduce = matchMedia("(prefers-reduced-motion: reduce)").matches;
function count() { document.querySelectorAll("[data-count]").forEach((el) => { const to = +el.dataset.count, d = +(el.dataset.dec || 0), t0 = performance.now();
  (function f(t) { const p = reduce ? 1 : Math.min(1, (t - t0) / 1000); el.textContent = (to * (1 - Math.pow(1 - p, 3))).toFixed(d); if (p < 1) requestAnimationFrame(f); })(t0); }); }
function ring(sc, st) { return `<div class="gauge ${st}"><svg viewBox="0 0 84 84"><circle class="bg" cx="42" cy="42" r="34"/><circle class="fg" cx="42" cy="42" r="34" style="--off:${(213.6 * (1 - sc / 100)).toFixed(1)}"/></svg><b>${sc}</b></div>`; }
function drawOverview() {
  const f = S.fleet, healthy = f.filter((s) => s.status === "HEALTHY").length, open = S.tickets.filter((t) => t.status === "open");
  const soon = f.filter((s) => s.ttf_hours != null).sort((a, b) => a.ttf_hours - b.ttf_hours)[0];
  const avg = f.length ? Math.round(f.reduce((a, s) => a + s.health_score, 0) / f.length) : 0;
  const k = (l, v, c, d) => `<div class="kpi"><div class="l">${l}</div><div class="v ${c}">${v}</div><div class="d">${d}</div></div>`;
  $("kpis").innerHTML = k("Healthy servers", `<span data-count="${healthy}">0</span><em> of ${f.length}</em>`, healthy === f.length ? "HEALTHY" : "WARNING", "No problem predicted") +
    k("Average health", `<span data-count="${avg}">0</span>`, avg > 79 ? "HEALTHY" : avg > 49 ? "WARNING" : "CRITICAL", "Fleet score out of 100") +
    k("Open tickets", `<span data-count="${open.length}">0</span>`, open.length ? "CRITICAL" : "HEALTHY", "Waiting for action") +
    k("Next expected problem", soon ? `<span data-count="${soon.ttf_hours}" data-dec="1">0</span><em> h · ${soon.server_id}</em>` : "None", soon ? "WARNING" : "HEALTHY", "Earliest predicted breach");
  count();
  $("fleet").innerHTML = f.map((s) => `<button class="card ${s.status}" data-id="${s.server_id}">
      <div class="row"><div><div class="name">${s.server_id}</div><div class="role">${INFO[s.server_id][0]}</div><span class="badge ${s.status}"><span>${STATUS[s.status]}</span></span></div>${ring(s.health_score, s.status)}</div>
      <div class="mini"><div><small>CPU</small><b>${fmt(s.current.cpu_usage)}%</b></div><div><small>Memory</small><b>${fmt(s.current.memory_usage)}%</b></div><div><small>Temp</small><b>${fmt(s.current.temp_celsius)}°C</b></div></div>
      <div class="${s.ttf_hours != null ? s.status : "dim"}">${s.ttf_hours != null ? `Problem expected in ${fmt(s.ttf_hours)} hours` : "No problem expected in 24 hours"}</div></button>`).join("");
  $("fleet").querySelectorAll(".card").forEach((c) => c.addEventListener("click", () => { S.server = c.dataset.id; drawPills(); go("forecast"); }));
  $("risk").innerHTML = [...f].sort((a, b) => a.health_score - b.health_score).map((s) => `<div class="risk-row"><span>${s.server_id}</span><div class="bar ${s.status}"><i style="width:${s.health_score}%"></i></div><b>${s.health_score}</b></div>`).join("");
  $("todo").innerHTML = open.length ? open.slice(0, 4).map((t) => `<div class="todo"><b class="${t.severity}">${t.server_id}: ${ML[t.metric]} in ${fmt(t.hours_until_breach)} h</b><span class="dim">${esc(t.recommended_action)}</span></div>`).join("") : `<p class="dim">Nothing to do right now. Forecasts show no problems.</p>`;
  drawActivity();
}
function drawActivity() { const el = $("activity"); if (el) el.innerHTML = S.log.map((l) => `<div class="log"><time>${l.t.toLocaleTimeString()}</time><span>${esc(l.m)}</span></div>`).join(""); }
function drawProfile() {
  const s = S.fleet.find((x) => x.server_id === S.server), i = INFO[S.server]; if (!s) return;
  $("profile").innerHTML = `<div><b class="pname">${S.server}</b> <span class="dim">· ${i[0]}</span></div><div class="dim">${i[1]}</div><div><span class="gold">What to expect:</span> ${i[2]}</div><div class="${s.status}">${STATUS[s.status]} · health ${s.health_score}</div>`;
  $("profile").classList.toggle("hidden", !["forecast", "analysis"].includes(S.tab));
}
function drawQuiet(q) { $("quiet").innerHTML = `${String(q.start_hour).padStart(2, "0")}:00 – ${String(q.end_hour).padStart(2, "0")}:00 <small>CPU about ${q.avg_cpu}%</small>`; }

/* ---------- forecast ---------- */
async function loadForecast() {
  const id = ++S.req; $("chart-busy").classList.remove("hidden");
  try { const f = await api(`/api/forecast/${S.server}?metric=${metric()}&hours=${$("hours").value}`); if (id !== S.req) return; S.fc = f; drawForecast(); }
  catch (e) { $("summary").textContent = "Could not load the forecast: " + e.message; }
  finally { if (id === S.req) $("chart-busy").classList.add("hidden"); }
}
function drawForecast() {
  const f = S.fc; if (!f) return; const w = +$("whatif").value, k = 1 + w / 100, m = f.metric, u = UNIT[m], fc = f.forecast, hs = f.history, xs = fc.timestamps, sc = (a) => a.map((v, i) => { const x = v * (1 + (k - 1) * ((i + 1) / a.length)); return m === "memory_usage" || m === "cpu_usage" ? Math.min(100, x) : x; });  // ramps in gradually, % metrics cap at 100
  $("whatif-val").textContent = (w > 0 ? "+" : "") + w + "%";
  const hw = sc(fc.holt_winters), ml = sc(fc.lag_regression), up = sc(fc.ci_upper), lo = sc(fc.ci_lower), best = fc.best_model === "holt_winters" ? hw : ml;
  const base = { hovertemplate: `%{y:.2f}${u}<extra>%{fullData.name}</extra>` }, start = new Date(new Date(xs[0]).getTime() - 24 * 3600e3).toISOString().slice(0, 19), gold = cv("--accent");
  Plotly.react("chart", [
    { x: xs.concat([...xs].reverse()), y: up.concat([...lo].reverse()), fill: "toself", fillcolor: gold + "22", line: { width: 0 }, name: "95% likely range", hoverinfo: "skip" },
    { x: hs.timestamps, y: hs.values, name: "Real readings", mode: "lines", line: { color: "#9db4ff", width: 1.6 }, ...base },
    { x: xs, y: hw, name: "Holt-Winters forecast", mode: "lines", line: { color: "#ff9f1c", dash: "dash", width: 2 }, ...base },
    { x: xs, y: ml, name: "ML forecast", mode: "lines", line: { color: "#d08cff", dash: "dash", width: 2.6 }, ...base },
    { x: [start, xs.at(-1)], y: [f.threshold, f.threshold], name: `Safe limit (${f.threshold}${u})`, mode: "lines", line: { color: "#ff6b81", dash: "dot", width: 2 }, hoverinfo: "skip" }],
    L({ xaxis: { range: [start, xs.at(-1)] }, yaxis: { title: ML[m] + u }, margin: { t: 10, r: 16, b: 50, l: 60 },
      shapes: [{ type: "line", x0: hs.timestamps.at(-1), x1: hs.timestamps.at(-1), yref: "paper", y0: 0, y1: 1, line: { color: cv("--dim"), width: 1, dash: "dot" } }] }), PC);
  const idx = best.findIndex((v) => v > f.threshold), hrs = idx < 0 ? null : ((idx + 1) * 5) / 60, el = $("summary"), note = w ? ` <span class="gold">(What-if: load ${w > 0 ? "+" : ""}${w}%)</span>` : "";
  el.classList.toggle("bad", idx >= 0);
  el.innerHTML = (idx >= 0 ? `${ML[m]} on <b>${S.server}</b> is likely to pass its safe limit of ${f.threshold}${u} in about <b>${fmt(hrs, 1)} hours</b> (around ${when(xs[idx])}). Act before then.`
    : `${ML[m]} on <b>${S.server}</b> should stay under its safe limit of ${f.threshold}${u} for the next ${f.hours} hours. It is ${fmt(hs.values.at(-1))}${u} now and about ${fmt(best.at(-1))}${u} at the end.`) + note;
  const e = f.evaluation, nm = { holt_winters: "Holt-Winters (daily seasonal smoothing)", lag_regression: "ML regression (learns from recent values)" };
  $("eval-body").innerHTML = ["holt_winters", "lag_regression"].map((q) => `<tr><td>${nm[q]}</td><td class="num">${e[q].mae}</td><td class="num">${e[q].rmse}</td><td class="num">${e[q].r2}</td><td class="num">${e[q].accuracy_pct}%</td>
    <td>${q === fc.best_model ? '<span class="pillx good">Most accurate</span>' : ""}${q === "holt_winters" && f.holt_winters_status !== "ok" ? ` <span class="pillx warn">${esc(f.holt_winters_status)}</span>` : ""}</td></tr>`).join("");
}

/* ---------- analysis ---------- */
async function loadAnalysis() {
  try {
    const a = await api(`/api/analysis/${S.server}`), m = metric(), d = a.metrics[m]; drawQuiet(a.quiet_window);
    $("insights").innerHTML = a.insights.map((i) => `<li class="${i.level}"><span>${esc(i.text)}</span></li>`).join("");
    $("stats-body").innerHTML = Object.entries(a.metrics).map(([k, x]) => `<tr><td><b>${x.label}</b></td><td class="num">${x.now}</td><td class="num">${x.average}</td><td class="num">${x.highest}</td><td class="num">${x.typical_peak}</td>
      <td class="num ${x.change_per_day > 0.3 ? "warn" : ""}">${x.change_per_day > 0 ? "+" : ""}${x.change_per_day}</td><td class="num ${x.days_to_limit != null && x.days_to_limit < 3 ? "bad" : ""}">${x.days_to_limit ?? "–"}</td>
      <td class="num">${x.spikes_48h}</td><td style="min-width:110px"><div class="bar ${x.percent_of_limit > 90 ? "CRITICAL" : x.percent_of_limit > 75 ? "WARNING" : "HEALTHY"}"><i style="width:${Math.min(100, x.percent_of_limit)}%"></i></div><small class="dim">${x.percent_of_limit}%</small></td></tr>`).join("");
    const r = d.recent;
    Plotly.react("spike-chart", [{ x: r.timestamps, y: r.values, name: ML[m], mode: "lines", line: { color: "#4c9aff", width: 1.4 } },
      { x: r.spikes.map((p) => p.timestamp), y: r.spikes.map((p) => p.value), name: "Unusual spike", mode: "markers", marker: { color: "#ff5c6c", size: 9, line: { color: "#fff", width: 1 } } },
      { x: [r.timestamps[0], r.timestamps.at(-1)], y: [d.threshold, d.threshold], name: "Safe limit", mode: "lines", line: { color: "#ff5c6c", dash: "dot" }, hoverinfo: "skip" }], L({ yaxis: { title: ML[m] + UNIT[m] } }), PC);
    Plotly.react("hour-chart", [{ x: [...Array(24).keys()].map((h) => `${h}:00`), y: d.hourly, type: "bar", marker: { color: d.hourly.map((v) => (v > d.typical_peak * 0.97 ? "#ffb020" : cv("--accent"))) }, name: ML[m] }],
      L({ yaxis: { title: "Average " + ML[m] + UNIT[m], range: [Math.min(...d.hourly) * 0.97, Math.max(...d.hourly) * 1.03] }, showlegend: false }), PC);
    const c = a.correlation;
    Plotly.react("corr-chart", [{ z: c.matrix, x: c.labels, y: c.labels, type: "heatmap", zmin: -1, zmax: 1, colorscale: [[0, "#ff5c6c"], [0.5, cv("--panel")], [1, cv("--accent")]], texttemplate: "%{z:.2f}", hovertemplate: "%{x} and %{y}: %{z}<extra></extra>" }],
      L({ margin: { t: 10, r: 10, b: 40, l: 90 } }), PC);
  } catch (e) { toast("Could not load analysis: " + e.message); }
}

/* ---------- compare ---------- */
async function loadCompare() {
  try {
    const c = await api(`/api/compare?metric=${metric()}`), m = metric();
    const traces = Object.entries(c.servers).map(([s, v]) => ({ x: v.timestamps, y: v.percent, name: s, mode: "lines", line: { color: COLORS[s], width: 2 }, hovertemplate: "%{y:.0f}% of limit<extra>%{fullData.name}</extra>" }));
    const xs = Object.values(c.servers)[0].timestamps;
    traces.push({ x: [xs[0], xs.at(-1)], y: [100, 100], name: "Safe limit", mode: "lines", line: { color: "#ff5c6c", dash: "dot", width: 2 }, hoverinfo: "skip" });
    Plotly.react("cmp-chart", traces, L({ yaxis: { title: `${ML[m]} (% of limit)`, rangemode: "tozero" } }), PC);
    $("cmp-cards").innerHTML = Object.entries(c.servers).map(([s, v]) => { const p = v.percent.at(-1), st = p > 100 ? "CRITICAL" : p > 80 ? "WARNING" : "HEALTHY";
      return `<div class="card ${st}" style="cursor:default"><div class="name">${s}</div><div class="score ${st}" style="margin:10px 0 4px">${v.now}${UNIT[m]}</div><div class="bar ${st}"><i style="width:${Math.min(100, p)}%"></i></div><small class="dim">${fmt(p, 0)}% of the safe limit</small></div>`; }).join("");
  } catch (e) { toast("Could not load comparison: " + e.message); }
}

/* ---------- tickets ---------- */
function drawTickets() {
  const T = S.tickets, cnt = (s) => (s === "all" ? T.length : T.filter((t) => t.status === s).length);
  $("chips").innerHTML = ["open", "acknowledged", "resolved", "all"].map((s) => `<button class="pill ${S.filter === s ? "on" : ""}" data-f="${s}">${s[0].toUpperCase() + s.slice(1)} (${cnt(s)})</button>`).join("");
  $("chips").querySelectorAll("button").forEach((b) => b.addEventListener("click", () => { S.filter = b.dataset.f; drawTickets(); }));
  const rows = T.filter((t) => S.filter === "all" || t.status === S.filter);
  $("tickets-body").innerHTML = rows.length ? rows.map((k) => `<tr class="${k.status === "resolved" ? "dim" : ""}"><td class="mono">${esc(k.server_id)}</td><td>${ML[k.metric] || esc(k.metric)}</td>
    <td><span class="pillx ${k.severity}">${k.severity}</span></td><td>${when(k.predicted_breach_time)}</td><td class="num">${fmt(k.hours_until_breach, 2)}</td><td style="max-width:380px">${esc(k.recommended_action)}</td><td>${k.status}</td>
    <td style="white-space:nowrap">${k.status === "resolved" ? "" : `${k.status === "open" ? `<button class="btn" data-ack="${k.id}">Acknowledge</button> ` : ""}<button class="btn" data-res="${k.id}">Resolve Ticket</button>`}</td></tr>`).join("")
    : `<tr><td colspan="8" class="dim">No tickets here. Nothing is predicted to go wrong.</td></tr>`;
  document.querySelectorAll("[data-res],[data-ack]").forEach((b) => b.addEventListener("click", async () => {
    const res = !!b.dataset.res; await api(`/api/tickets/${b.dataset.res || b.dataset.ack}/${res ? "resolve" : "acknowledge"}`, { method: "POST" });
    toast(res ? "Ticket resolved" : "Ticket acknowledged"); await loadTickets(); drawTickets();
  }));
}
$("btn-csv").addEventListener("click", () => {
  const h = ["id", "server_id", "metric", "predicted_breach_time", "hours_until_breach", "severity", "status", "recommended_action"];
  const csv = [h.join(","), ...S.tickets.map((t) => h.map((k) => `"${String(t[k]).replace(/"/g, '""')}"`).join(","))].join("\n");
  const a = document.createElement("a"); a.href = URL.createObjectURL(new Blob([csv], { type: "text/csv" })); a.download = "tickets.csv"; a.click();
});

/* ---------- data + actions ---------- */
async function loadTickets() { S.tickets = await api("/api/tickets"); drawNav(); }
async function refreshAll() {
  try {
    S.fleet = (await api("/api/servers")).servers; await loadTickets(); drawPills(); loadTab();
    setLive(true, "Live · updated " + new Date().toLocaleTimeString());
  } catch (e) { setLive(false, "Cannot reach the server"); }
}
async function act(path, msg) {
  if (S.busy) return; S.busy = true; $("btn-step").disabled = $("btn-reset").disabled = true;
  try { const before = S.tickets.filter((t) => t.status === "open").length; await api(path, { method: "POST" }); await refreshAll();
    const after = S.tickets.filter((t) => t.status === "open").length; toast(after > before ? `${msg}. ${after - before} new ticket(s) opened.` : msg); }
  catch (e) { toast("Something went wrong: " + e.message); } finally { S.busy = false; $("btn-step").disabled = $("btn-reset").disabled = false; }
}
$("btn-step").addEventListener("click", () => act(`/api/simulate/step?steps=3&live=${$("live-toggle").checked}`, "Moved forward 15 minutes"));
$("btn-reset").addEventListener("click", () => act("/api/simulate/reset", "Created fresh data"));
let timer = null;
$("auto").addEventListener("change", (e) => { clearInterval(timer); if (e.target.checked) timer = setInterval(() => act("/api/simulate/step?steps=3", "Auto-play: +15 minutes"), 8000); });
["metric", "hours"].forEach((id) => $(id).addEventListener("change", loadTab));
function setTheme(t) { document.documentElement.dataset.theme = t; try { localStorage.setItem("aegis-theme", t); } catch (e) {} document.querySelectorAll(".themes button").forEach((b) => b.classList.toggle("on", b.dataset.theme === t)); if (S.fleet.length) loadTab(); }
document.querySelectorAll(".themes button").forEach((b) => b.addEventListener("click", () => setTheme(b.dataset.theme)));
$("whatif").addEventListener("input", drawForecast);
document.addEventListener("keydown", (e) => { if (/INPUT|SELECT/.test(e.target.tagName)) return; const t = TABS[+e.key - 1]; if (t) go(t[0]); });
let saved = "royal"; try { saved = localStorage.getItem("aegis-theme") || "royal"; } catch (e) {}
setTheme(saved); go("overview"); refreshAll();
