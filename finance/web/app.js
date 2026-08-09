/* 全球金融数据超索引框架 - 管理台前端逻辑 (原生 JS, 零依赖) */
const API = "/api/v1/finance";

async function getJSON(url) {
  const r = await fetch(url);
  if (!r.ok) throw new Error(`${r.status} ${await r.text()}`);
  return r.json();
}
async function postJSON(url, body) {
  const r = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body || {}),
  });
  if (!r.ok) throw new Error(`${r.status} ${await r.text()}`);
  return r.json();
}
async function del(url) {
  const r = await fetch(url, { method: "DELETE" });
  if (!r.ok) throw new Error(`${r.status} ${await r.text()}`);
  return r.json();
}
function esc(s) {
  return String(s ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

/* ---------- tabs ---------- */
document.querySelectorAll(".tabs button").forEach(btn => {
  btn.addEventListener("click", () => {
    document.querySelectorAll(".tabs button").forEach(b => b.classList.remove("active"));
    btn.classList.add("active");
    document.querySelectorAll(".view").forEach(v => v.classList.remove("active"));
    document.getElementById(`view-${btn.dataset.view}`).classList.add("active");
    refresh(btn.dataset.view);
  });
});

/* ---------- 总览 ---------- */
async function renderOverview() {
  const h = await getJSON(`${API}/health`);
  const cards = document.getElementById("overview-cards");
  const t = h.taxonomy, c = h.catalog;
  cards.innerHTML = [
    ["数据类别", t.data_classes], ["国家/地区", t.regions], ["交易所/市场", t.exchanges],
    ["时间级别", t.time_levels], ["交易类型", t.trade_types], ["品种", t.instruments],
    ["数据源", c.sources], ["缓存文件", (await getJSON(`${API}/cache`)).files.length],
  ].map(([lbl, num]) => `<div class="card"><div class="num">${num}</div><div class="lbl">${lbl}</div></div>`).join("");

  const bars = document.getElementById("class-bars");
  const max = Math.max(...Object.values(t.instruments_by_class || {}), 1);
  bars.innerHTML = Object.entries(t.instruments_by_class || {}).map(([k, v]) =>
    `<div class="bar-row"><span class="name">${esc(k)}</span><div class="bar" style="width:${v / max * 80}%"></div><span class="val">${v}</span></div>`
  ).join("");

  const src = document.getElementById("source-list");
  const sources = await getJSON(`${API}/catalog`);
  src.innerHTML = `<table><tr><th>ID</th><th>名称</th><th>类型</th><th>状态</th><th>脚本</th></tr>` +
    sources.sources.map(s =>
      `<tr><td class="mono">${esc(s.id)}</td><td>${esc(s.name)}</td><td>${esc(s.type)}</td>
       <td><span class="badge ${s.status === "demo" ? "demo" : "ok"}">${esc(s.status)}</span></td>
       <td class="mono">${esc(s.script)}</td></tr>`).join("") + `</table>`;
}

/* ---------- 六维筛选 ---------- */
async function loadSelects() {
  const h = await getJSON(`${API}/health`);
  const dc = document.getElementById("f-data-class");
  dc.innerHTML = `<option value="">数据类别(全部)</option>` +
    Object.entries(h.taxonomy.instruments_by_class || {}).map(([k]) => `<option value="${esc(k)}">${esc(k)}</option>`).join("");
  const ex = document.getElementById("f-exchange");
  const r = await getJSON(`${API}/exchanges`);
  ex.innerHTML = `<option value="">交易所(全部)</option>` +
    r.exchanges.map(x => `<option value="${esc(x.id)}">${esc(x.name)}</option>`).join("");
  const rg = document.getElementById("f-region");
  rg.innerHTML = `<option value="">国家/地区(全部)</option>` +
    Object.entries(h.taxonomy.regions || {}).map(([k, v]) => `<option value="${esc(k)}">${esc(v.name)}</option>`).join("");
  const tt = document.getElementById("f-trade-type");
  tt.innerHTML = `<option value="">交易类型(全部)</option>` +
    Object.entries(h.taxonomy.trade_types || {}).map(([k, v]) => `<option value="${esc(k)}">${esc(v.name)}</option>`).join("");
  const tl = document.getElementById("f-time-level");
  tl.innerHTML = `<option value="">时间级别(全部)</option>` +
    Object.entries(h.taxonomy.time_levels || {}).map(([k, v]) => `<option value="${esc(k)}">${esc(v.name)}</option>`).join("");
}

function searchParams() {
  const p = new URLSearchParams();
  for (const id of ["f-data-class", "f-region", "f-exchange", "f-trade-type", "f-time-level"]) {
    const v = document.getElementById(id).value;
    if (v) p.set(id.replace("f-", ""), v);
  }
  const inst = document.getElementById("f-instrument").value.trim();
  if (inst) p.set("instrument", inst);
  return p;
}

async function renderSearch(mode = "detail") {
  const box = document.getElementById("search-result");
  try {
    if (mode === "summary") {
      const p = searchParams(); p.set("mode", "summary");
      const s = await getJSON(`${API}/search?${p}`);
      box.innerHTML = `<pre>${esc(JSON.stringify(s, null, 2))}</pre>`;
      return;
    }
    const r = await getJSON(`${API}/search?${searchParams()}`);
    if (!r.items.length) { box.innerHTML = `<p class="muted">未匹配到品种, 试试放宽条件</p>`; return; }
    box.innerHTML = `<p class="muted">匹配 ${r.items.length} 个品种</p>` + r.items.map(it => {
      const inst = it.instrument || {};
      const d = inst.data_class || {}, rg = inst.region || {}, ex = inst.exchange || {};
      const iid = (inst.instrument || {}).id || inst.id;
      const name = (inst.instrument || {}).name || inst.name;
      const chips = it.sources.map(s =>
        `<span class="src-chip" title="${esc(s.script)}\n${esc(s.command || "")}" onclick="fetchNow('${esc(s.id)}','${esc(iid)}')">${esc(s.id)}</span>`).join(" ");
      return `<div class="instrument-block"><h3>${esc(iid)} ${esc(name)}</h3>
        <div class="muted">${esc((d.name || "") + " | " + (rg.name || "") + " | " + (ex.name || ""))}</div>
        <div style="margin:6px 0">${chips}</div>
        <table><tr><th>数据源</th><th>类型</th><th>脚本</th><th>调度</th><th>命令</th></tr>` +
        it.sources.map(s => `<tr><td>${esc(s.name)}</td><td>${esc(s.type)}</td>
          <td class="mono">${esc(s.script)}</td><td>${esc(JSON.stringify(s.schedule || {}))}</td>
          <td class="mono">${esc(s.command || "")}</td></tr>`).join("") + `</table>
        <div id="fetch-${esc(iid)}-${esc(iid)}" class="muted"></div></div>`;
    }).join("");
  } catch (e) {
    box.innerHTML = `<p class="err" style="color:var(--err)">${esc(e.message)}</p>`;
  }
}

async function fetchNow(source, iid) {
  const box = document.getElementById(`fetch-${iid}-${iid}`);
  if (!box) return;
  box.innerHTML = `<span class="muted">正在触发 ${source} 获取 ${iid} ...</span>`;
  try {
    const r = await postJSON(`${API}/fetch`, { instrument: iid, source });
    const rows = (r.data?.rows || []).length;
    box.innerHTML = `<span class="badge ok">✓ ${esc(r.source)}${r.demo ? " (demo)" : ""} 获取成功</span> ` +
      `<span class="muted">${rows} 行 · ${esc(r.fetched_at || "")}</span>`;
  } catch (e) {
    box.innerHTML = `<span style="color:var(--err)">✗ ${esc(e.message)}</span>`;
  }
}

/* ---------- 数据源目录 ---------- */
async function renderCatalog() {
  const box = document.getElementById("catalog-list");
  const r = await getJSON(`${API}/catalog`);
  box.innerHTML = `<table><tr><th>ID</th><th>名称</th><th>类型</th><th>状态</th><th>覆盖</th><th>脚本</th></tr>` +
    r.sources.map(s => `<tr><td class="mono">${esc(s.id)}</td><td>${esc(s.name)}</td><td>${esc(s.type)}</td>
      <td><span class="badge ${s.status === "demo" ? "demo" : "ok"}">${esc(s.status)}</span></td>
      <td>${esc(Object.keys(s.coverage || {}).join(", "))}</td>
      <td class="mono">${esc(s.script)}</td></tr>`).join("") + `</table>`;
}

/* ---------- 调度中心 ---------- */
async function renderSchedule() {
  const box = document.getElementById("task-list");
  const r = await getJSON(`${API}/schedule`);
  if (!r.tasks.length) { box.innerHTML = `<p class="muted">暂无调度任务</p>`; return; }
  box.innerHTML = r.tasks.map(t =>
    `<div class="task-row"><div class="info">
       <strong class="mono">${esc(t.instrument_id)}</strong> ← <strong>${esc(t.source)}</strong>
       <div class="muted">every=${esc(t.every || "-")} at=${esc(t.at || "-")} · 下次: ${esc(t.next_run || "manual")} · 状态: ${esc(t.status || "pending")}${t.last_error ? " · 错误: " + esc(t.last_error) : ""}</div>
     </div>
     <button onclick="delTask('${esc(t.id)}')">删除</button></div>`).join("");
}
async function delTask(id) {
  await del(`${API}/schedule/${id}`);
  renderSchedule();
}
async function addTask() {
  const body = {
    instrument: document.getElementById("s-instrument").value.trim(),
    source: document.getElementById("s-source").value.trim(),
    every: document.getElementById("s-every").value.trim() || undefined,
    at: document.getElementById("s-at").value.trim() || undefined,
  };
  if (!body.instrument || !body.source) { alert("品种与数据源必填"); return; }
  const r = await postJSON(`${API}/schedule`, body);
  alert(`已添加任务 ${r.task.id}: ${body.instrument} ← ${body.source}`);
  renderSchedule();
}
async function runOnce() {
  const r = await postJSON(`${API}/schedule/run-once`, {});
  alert(`触发 ${r.triggered} 个到期任务`);
  renderSchedule();
}

/* ---------- 缓存 ---------- */
async function renderCache() {
  const box = document.getElementById("cache-list");
  const r = await getJSON(`${API}/cache`);
  if (!r.files.length) { box.innerHTML = `<p class="muted">暂无缓存数据 (可通过筛选->点击数据源触发获取)</p>`; return; }
  box.innerHTML = `<table><tr><th>文件</th><th>大小</th><th>修改时间</th></tr>` +
    r.files.map(f => `<tr><td class="mono">${esc(f.path)}</td><td>${f.size}</td><td>${esc(f.modified)}</td></tr>`).join("") + `</table>`;
}

/* ---------- 分发 ---------- */
const views = {
  overview: renderOverview,
  search: () => { loadSelects(); renderSearch("detail"); },
  catalog: renderCatalog,
  schedule: renderSchedule,
  cache: renderCache,
};
function refresh(name) { views[name] && views[name]().catch(e => console.error(e)); }

document.getElementById("btn-search").addEventListener("click", () => renderSearch("detail"));
document.getElementById("btn-search-summary").addEventListener("click", () => renderSearch("summary"));
document.getElementById("btn-add-task").addEventListener("click", addTask);
document.getElementById("btn-run-once").addEventListener("click", runOnce);

refresh("overview");
