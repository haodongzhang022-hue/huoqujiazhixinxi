/* 科技每日信息聚合 · 人类/AI 双信息流 前端逻辑 */
"use strict";

const API = "/api/v1";

async function getJSON(url) {
  const res = await fetch(url);
  if (!res.ok) throw new Error(`HTTP ${res.status}: ${url}`);
  return res.json();
}

function el(html) {
  const t = document.createElement("template");
  t.innerHTML = html.trim();
  return t.content.firstChild;
}

function esc(s) {
  return String(s == null ? "" : s).replace(/[&<>"']/g, c => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  }[c]));
}

function badge(decision) {
  return `<span class="badge ${esc(decision)}">${esc(decision || "none")}</span>`;
}

function gradeClass(grade) {
  return `grade-${esc(grade || "D")}`;
}

function typeBadge(type) {
  const map = { repo: "📦 项目", paper: "📄 论文", trend: "🔥 热点", news: "📰 新闻", "cnb-project": "🧩 CNB" };
  return `<span class="badge type-${esc(type)}">${esc(map[type] || type)}</span>`;
}

function itemCard(it) {
  const tags = (it.function_tags || []).map(t => `<span class="tag">${esc(t)}</span>`).join("");
  const stars = it.stars ? `<span class="stars">⭐ ${esc(it.stars)}${it.stars_delta_7d ? ` <span style="color:var(--green)">+${esc(it.stars_delta_7d)}/7d</span>` : ""}${it.stars_delta_24h ? ` <span style="color:var(--green)">+${esc(it.stars_delta_24h)}/24h</span>` : ""}</span>` : "";
  const newTag = it.is_new ? ' <span class="tag" style="color:var(--yellow)">NEW</span>' : "";
  const decision = it.category_decision ? badge(it.category_decision) : "";
  const review = it.review;
  const revHtml = review && (review.verdict || review.recommendation) ? `
    <div class="review-line">
      ${review.verdict ? `<span class="badge ${esc(review.verdict)}">${esc(review.verdict)}</span>` : ""}
      ${review.score != null ? `<span class="review-score">评分 ${esc(review.score)}</span>` : ""}
      ${review.recommendation ? `<span class="muted">${esc(review.recommendation)}</span>` : ""}
    </div>` : "";
  const content = it.content ? `<div class="item-content">${esc(it.content)}</div>` : "";
  return `
    <div class="item-card">
      <div class="item-head">
        <a href="${esc(it.url || "#")}" target="_blank" class="item-title">${esc(it.title)}</a>${newTag}
        ${typeBadge(it.type)}
      </div>
      <div class="item-meta">
        ${stars} ${it.language ? `<span class="lang">${esc(it.language)}</span>` : ""}
        ${it.category ? `<span class="category">${esc(it.category)}</span>` : ""}
        ${decision}
      </div>
      <div class="item-desc">${esc(it.summary_zh || it.description || "")}</div>
      ${content}
      ${tags ? `<div class="item-tags">${tags}</div>` : ""}
      ${it.use_case ? `<div class="use-case">💡 适用场景: ${esc(it.use_case)}</div>` : ""}
      ${revHtml}
      <div class="item-src muted">来源: ${esc(it.source_label || it.source)} · ${esc((it.published_at || "").slice(0, 10) || "-")}</div>
    </div>`;
}

function humanFeedHTML(data, limit) {
  const headline = data.headline || {};
  let html = "";
  if (headline.items && headline.items.length) {
    html += `<div class="panel"><h2>🏆 ${esc(headline.title || "今日最值得关注")}</h2><div class="item-grid">${headline.items.map(itemCard).join("")}</div></div>`;
  }
  html += (data.sections || []).map(sec => `
    <div class="panel">
      <h2>${esc(sec.title)} <span class="muted">(${esc(sec.description || sec.items.length + " 个项目")})</span></h2>
      <div class="item-grid">${(sec.items || []).map(itemCard).join("")}</div>
    </div>`).join("");
  if (!html) html = '<div class="empty">暂无数据, 先运行 python -m pipeline.fetch 采集</div>';
  return html;
}

/* ---------------- 总览 ---------------- */
async function renderOverview(container) {
  const data = await getJSON(`${API}/dashboard/overview`);
  const status = await getJSON(`${API}/status`);
  const s = data.stats;
  const q = data.quality;

  const cards = [
    ["储备仓库", s.total_repos],
    ["今日信息流", (status.feed_today || {}).total || 0],
    ["action 升级", s.decisions.action || 0],
    ["reserve 储备", s.decisions.reserve || 0],
    ["待满足需求", s.needs.open],
    ["待审核", s.review.pending],
    ["储备库质量", q.store_score != null ? q.store_score : "-"],
  ].map(([label, num]) => `<div class="stat-card"><div class="num">${esc(num)}</div><div class="label">${esc(label)}</div></div>`).join("");

  const decisions = Object.entries(s.decisions || {})
    .map(([k, v]) => `<tr><td>${badge(k)}</td><td>${esc(v)}</td></tr>`).join("");
  const cats = Object.entries(s.categories || {})
    .map(([k, v]) => `<tr><td>${esc(k)}</td><td>${esc(v)}</td></tr>`).join("");

  const trend = (q.trend || []);
  const maxScore = Math.max(100, ...trend.map(t => t.score || 0));
  const bars = trend.map(t => {
    const h = Math.max(4, ((t.score || 0) / maxScore) * 100);
    return `<div class="bar" style="height:${h}%"><span>${esc(t.date)}</span></div>`;
  }).join("");

  const snaps = (data.snapshots || []).map(sn => `
    <tr>
      <td>${esc(sn.date)}</td>
      <td>${esc(sn.score)} <span class="badge ${gradeClass(sn.grade)}">${esc(sn.grade)}</span></td>
      <td>${esc(sn.total)}</td>
      <td>${esc(sn.unique)}</td>
      <td>${esc(sn.new_this_week)}</td>
      <td>${esc(sn.action_candidates)}</td>
    </tr>`).join("");

  const srcRows = (status.sources || []).map(sr => `
    <tr>
      <td>${esc(sr.label)}</td>
      <td><span class="badge ${esc(sr.status)}">${esc(sr.status)}</span></td>
      <td>${sr.enabled ? "✅ 已接入" : "⏳ 预留接口"}</td>
      <td class="desc" title="${esc(sr.note)}">${esc(sr.note || "-")}</td>
    </tr>`).join("") || '<tr><td colspan="4" class="empty">暂无数据源</td></tr>';

  container.innerHTML = `
    <div class="stats-grid">${cards}</div>
    <div class="panel">
      <h2>质量趋势 (${trend.length ? "最近 " + trend.length + " 天" : "暂无快照"})</h2>
      ${trend.length ? `<div class="chart">${bars}</div>` : '<div class="empty">尚无快照数据, 先运行 python -m pipeline.fetch</div>'}
      <p style="margin-top:8px;font-size:13px;color:var(--muted)">趋势方向: ${esc(q.trend_direction || "-")} | 平均分: ${esc(q.trend_avg ?? "-")} | 储备库质量: <b>${esc(q.store_score ?? "-")}</b> (${esc(q.store_grade || "-")})</p>
      ${q.store_issues && q.store_issues.length ? `<ul class="issue-list">${q.store_issues.map(i => `<li>⚠️ ${esc(i)}</li>`).join("")}</ul>` : ""}
    </div>
    <div class="panel">
      <h2>数据源状态 (含预留扩展位)</h2>
      <table><thead><tr><th>数据源</th><th>状态</th><th>接入</th><th>说明</th></tr></thead><tbody>${srcRows}</tbody></table>
    </div>
    <div class="panel">
      <h2>储备库状态</h2>
      <div style="display:grid;grid-template-columns:1fr 1fr;gap:20px">
        <div>
          <h3>条件判断分布</h3>
          <table><thead><tr><th>决策</th><th>数量</th></tr></thead><tbody>${decisions}</tbody></table>
        </div>
        <div>
          <h3>生态分类分布</h3>
          <table><thead><tr><th>分类</th><th>数量</th></tr></thead><tbody>${cats}</tbody></table>
        </div>
      </div>
    </div>
    <div class="panel">
      <h2>每日快照</h2>
      <table>
        <thead><tr><th>日期</th><th>质量分</th><th>总数</th><th>唯一</th><th>新仓库</th><th>action候选</th></tr></thead>
        <tbody>${snaps || '<tr><td colspan="6" class="empty">暂无快照</td></tr>'}</tbody>
      </table>
    </div>`;
}

/* ---------------- 今日汇总 (每日聚合) ---------------- */
async function renderDigest(container) {
  const data = await getJSON(`${API}/digest`);
  const st = data.stats || {};
  const cards = [
    ["信息条目", st.total_items],
    ["当周新项目", st.new_this_week],
    ["action 候选", st.action_candidates],
    ["累计 Stars", st.total_stars],
  ].map(([label, num]) => `<div class="stat-card"><div class="num">${esc(num)}</div><div class="label">${esc(label)}</div></div>`).join("");

  const decisions = Object.entries(st.decisions || {})
    .map(([k, v]) => `<tr><td>${badge(k)}</td><td>${esc(v)}</td></tr>`).join("");
  const cats = Object.entries(st.categories || {})
    .map(([k, v]) => `<tr><td>${esc(k)}</td><td>${esc(v)}</td></tr>`).join("");

  container.innerHTML = `
    <div class="panel">
      <h2>📅 ${esc(data.date)} 每日信息聚合</h2>
      <p style="font-size:13px;color:var(--muted)">生成时间: ${esc(data.generated_at)}</p>
    </div>
    <div class="stats-grid">${cards}</div>
    <div class="panel">
      <h2>聚合统计</h2>
      <div style="display:grid;grid-template-columns:1fr 1fr;gap:20px">
        <div><h3>条件判断分布</h3><table><thead><tr><th>决策</th><th>数量</th></tr></thead><tbody>${decisions}</tbody></table></div>
        <div><h3>分类分布</h3><table><thead><tr><th>分类</th><th>数量</th></tr></thead><tbody>${cats}</tbody></table></div>
      </div>
    </div>
    ${humanFeedHTML(data, 200)}
    `;
}

/* ---------------- 信息流 (人类优先 / AI 优先) ---------------- */
let feedState = { mode: "human", date: "", category: "", decision: "", limit: 50, offset: 0 };

async function renderFeed(container) {
  const params = new URLSearchParams({ mode: feedState.mode, limit: feedState.limit, offset: feedState.offset });
  if (feedState.date) params.set("date", feedState.date);
  if (feedState.category) params.set("category", feedState.category);
  if (feedState.decision) params.set("decision", feedState.decision);

  const url = feedState.date ? `${API}/feed/${feedState.date}?${params}` : `${API}/feed?${params}`;
  const data = await getJSON(url);
  const meta = data.meta || {};
  const total = meta.total || 0;
  const totalPages = Math.max(1, Math.ceil(total / feedState.limit));
  const curPage = Math.floor((meta.offset || 0) / feedState.limit) + 1;

  let body;
  if (feedState.mode === "ai") {
    const items = data.items || [];
    body = `
      <div class="panel">
        <h2>🤖 AI 优先信息流 <span class="muted">(机器可直接消费, 搭自动化/喂 Agent)</span></h2>
        <pre class="ai-feed-pre" id="ai-feed-json">${esc(JSON.stringify({ meta, items }, null, 2))}</pre>
      </div>
      <div class="panel">
        <h2>👁 预览 (人类可读)</h2>
        <div class="item-grid">${items.map(itemCard).join("") || '<div class="empty">暂无条目</div>'}</div>
      </div>`;
  } else {
    body = humanFeedHTML(data, feedState.limit);
  }

  container.innerHTML = `
    <div class="toolbar">
      <div class="mode-switch">
        <button class="btn ${feedState.mode==='human'?'primary':'secondary'}" onclick="feedState.mode='human';feedState.offset=0;refresh('feed')">👤 人类优先</button>
        <button class="btn ${feedState.mode==='ai'?'primary':'secondary'}" onclick="feedState.mode='ai';feedState.offset=0;refresh('feed')">🤖 AI 优先</button>
      </div>
      <input id="feed-date" type="date" value="${esc(feedState.date)}" onchange="feedState.date=this.value;feedState.offset=0;refresh('feed')">
      <select id="feed-category" onchange="feedState.category=this.value;feedState.offset=0;refresh('feed')">
        <option value="">全部分类</option>
        <option value="mcp-servers">MCP 服务器</option>
        <option value="ai-agents">AI 代理框架</option>
        <option value="rag-kb">RAG 与知识库</option>
        <option value="agent-orchestration">Agent 编排</option>
        <option value="llm-prompts">LLM 提示词</option>
        <option value="ai-dev-tools">AI 开发工具</option>
        <option value="data-infra">数据基础设施</option>
        <option value="developer-tools">开发者工具</option>
      </select>
      <select id="feed-decision" onchange="feedState.decision=this.value;feedState.offset=0;refresh('feed')">
        <option value="">全部决策</option>
        <option value="action">action</option>
        <option value="reserve">reserve</option>
        <option value="partial">partial</option>
        <option value="ignore">ignore</option>
      </select>
      ${feedState.mode === "ai" ? `<button class="btn secondary" onclick="copyAiFeed()">📋 复制 JSON</button>` : ""}
    </div>
    <div class="feed-meta muted">
      模式: <b>${feedState.mode === "human" ? "人类优先 (按分类分组)" : "AI 优先 (扁平 JSON)"}</b>
      ${feedState.date ? ` · 日期: <b>${esc(feedState.date)}</b>` : " · 今日"}
      · 共 <b>${total}</b> 条
      ${feedState.mode === "ai" ? `<br><span style="font-size:12px">🔗 接口: GET /api/v1/feed${feedState.date ? "/" + feedState.date : ""}?mode=ai&limit=${feedState.limit}&offset=${feedState.offset}${feedState.category ? "&category=" + feedState.category : ""}${feedState.decision ? "&decision=" + feedState.decision : ""}</span>` : ""}
    </div>
    ${body}
    <div class="pagination">
      <button class="btn secondary" ${feedState.offset===0?'disabled':''} onclick="feedState.offset=0;refresh('feed')">首页</button>
      <button class="btn secondary" ${feedState.offset===0?'disabled':''} onclick="feedState.offset=Math.max(0,feedState.offset-feedState.limit);refresh('feed')">上一页</button>
      <span>第 ${curPage} / ${totalPages} 页</span>
      <button class="btn secondary" ${curPage>=totalPages?'disabled':''} onclick="feedState.offset+=feedState.limit;refresh('feed')">下一页</button>
    </div>`;
}

async function copyAiFeed() {
  const pre = document.getElementById("ai-feed-json");
  if (!pre) return;
  try {
    await navigator.clipboard.writeText(pre.textContent);
    alert("✅ JSON 已复制到剪贴板, 可直接用于自动化流程");
  } catch (e) {
    alert("复制失败: " + e.message + " (请手动全选复制)");
  }
}

/* ---------------- 仓库列表 ---------------- */
let repoState = { offset: 0, limit: 20, decision: "", category: "", q: "", sort: "stars" };

async function renderRepos(container) {
  const params = new URLSearchParams({
    limit: repoState.limit, offset: repoState.offset, sort: repoState.sort,
  });
  if (repoState.decision) params.set("decision", repoState.decision);
  if (repoState.category) params.set("category", repoState.category);
  if (repoState.q) params.set("q", repoState.q);

  const data = await getJSON(`${API}/dashboard/repos?${params}`);
  const items = data.items || [];
  const rows = items.map(r => `
    <tr>
      <td><a href="${esc(r.url)}" target="_blank">${esc(r.full_name)}</a>${r.is_new_this_week ? ' <span class="tag">NEW</span>' : ""}</td>
      <td>${esc(r.stars)}${r.stars_delta_7d ? ` <span style="color:var(--green)">+${esc(r.stars_delta_7d)}</span>` : ""}</td>
      <td>${esc(r.language || "-")}</td>
      <td>${badge(r.category_decision)}</td>
      <td>${esc(r.category || "-")}</td>
      <td class="desc" title="${esc(r.description || "")}">${esc(r.function_summary || r.description || "-")}</td>
      <td>${(r.function_tags || []).map(t => `<span class="tag">${esc(t)}</span>`).join("") || "-"}</td>
      <td>${r.index_source === "llm" ? '<span class="tag" style="color:var(--green)">LLM</span>' : ""}</td>
    </tr>`).join("") || `<tr><td colspan="8" class="empty">无匹配仓库</td></tr>`;

  const totalPages = Math.max(1, Math.ceil(data.total / repoState.limit));
  const curPage = Math.floor(repoState.offset / repoState.limit) + 1;

  container.innerHTML = `
    <div class="toolbar">
      <input id="repo-q" placeholder="搜索关键字..." value="${esc(repoState.q)}" onkeydown="if(event.key==='Enter'){repoState.q=this.value;repoState.offset=0;refresh('repos')}">
      <select id="repo-decision" onchange="repoState.decision=this.value;repoState.offset=0;refresh('repos')">
        <option value="">全部决策</option>
        <option value="action" ${repoState.decision==='action'?'selected':''}>action</option>
        <option value="reserve" ${repoState.decision==='reserve'?'selected':''}>reserve</option>
        <option value="partial" ${repoState.decision==='partial'?'selected':''}>partial</option>
        <option value="ignore" ${repoState.decision==='ignore'?'selected':''}>ignore</option>
      </select>
      <select id="repo-sort" onchange="repoState.sort=this.value;refresh('repos')">
        <option value="stars" ${repoState.sort==='stars'?'selected':''}>按 Star</option>
        <option value="delta7d" ${repoState.sort==='delta7d'?'selected':''}>按 7d 增量</option>
        <option value="newest" ${repoState.sort==='newest'?'selected':''}>按最新</option>
        <option value="score" ${repoState.sort==='score'?'selected':''}>按决策分</option>
      </select>
      <button class="btn secondary" onclick="repoState.q=document.getElementById('repo-q').value;repoState.offset=0;refresh('repos')">搜索</button>
    </div>
    <div class="panel">
      <table>
        <thead><tr><th>仓库</th><th>Star</th><th>语言</th><th>决策</th><th>分类</th><th>功能摘要</th><th>功能标签</th><th>索引</th></tr></thead>
        <tbody>${rows}</tbody>
      </table>
      <div class="pagination">
        <button class="btn secondary" ${repoState.offset===0?'disabled':''} onclick="repoState.offset=0;refresh('repos')">首页</button>
        <button class="btn secondary" ${repoState.offset===0?'disabled':''} onclick="repoState.offset=Math.max(0,repoState.offset-repoState.limit);refresh('repos')">上一页</button>
        <span>第 ${curPage} / ${totalPages} 页 (共 ${data.total} 条)</span>
        <button class="btn secondary" ${curPage>=totalPages?'disabled':''} onclick="repoState.offset+=repoState.limit;refresh('repos')">下一页</button>
      </div>
    </div>`;
}

/* ---------------- 能力簇 ---------------- */
async function renderClusters(container) {
  const data = await getJSON(`${API}/dashboard/clusters?mode=by-tags`);
  if (data.error) {
    container.innerHTML = `<div class="empty">❌ ${esc(data.error)}</div>`;
    return;
  }
  const summary = data.summary || {};
  const cards = (data.clusters || []).map(c => `
    <div class="cluster-card">
      <div class="title">${esc(c.tag)}</div>
      <div class="meta">${esc(c.count)} 个项目 · ${esc(c.total_stars)} stars</div>
      <ul>
        ${(c.repos || []).slice(0, 6).map(r => `
          <li><a href="${esc(r.url)}" target="_blank">${esc(r.full_name)}</a>
          ⭐${esc(r.stars)} ${badge(r.category_decision)}</li>`).join("")}
      </ul>
    </div>`).join("") || `<div class="empty">暂无能力簇 (先入库数据)</div>`;

  container.innerHTML = `
    <div class="stats-grid">
      <div class="stat-card"><div class="num">${esc(summary.total_repos || 0)}</div><div class="label">储备项目</div></div>
      <div class="stat-card"><div class="num">${esc(summary.unique_tags || 0)}</div><div class="label">能力簇</div></div>
    </div>
    <div class="cluster-grid">${cards}</div>`;
}

/* ---------------- 质量评估 ---------------- */
async function renderQuality(container) {
  const data = await getJSON(`${API}/quality`);
  const parts = [];

  for (const [key, label] of [["snapshot", "今日快照"], ["store", "储备库"], ["trend", "质量趋势"]]) {
    const p = data[key] || {};
    if (p.error) {
      parts.push(`<div class="panel"><h2>${label}</h2><div class="empty">${esc(p.error)}</div></div>`);
      continue;
    }
    let inner = "";
    if (key === "snapshot" || key === "store") {
      const dims = Object.entries(p.dimensions || {})
        .map(([k, v]) => `
          <div style="margin-bottom:8px">
            <div style="font-size:13px;color:var(--muted)">${esc(k)}: ${esc(v)}</div>
            <div class="grade-bar ${gradeClass(p.grade?.grade)}"><div class="fill" style="width:${Math.max(0, Math.min(100, v))}%"></div></div>
          </div>`).join("");
      const issues = (p.issues || []).map(i => `<li>⚠️ ${esc(i)}</li>`).join("");
      inner = `
        <div class="status-line">
          <span class="status-pill">总分 <b>${esc(p.score)}</b></span>
          <span class="status-pill ${p.score >= 75 ? "ok" : p.score >= 60 ? "warn" : "err"}">${esc(p.grade?.grade || "-")} 级</span>
        </div>
        ${dims}
        ${issues ? `<ul class="issue-list">${issues}</ul>` : '<p style="color:var(--green);font-size:13px">✅ 无质量缺项</p>'}
        ${p.recommendation ? `<p style="margin-top:10px;font-size:13px;color:var(--accent)">💡 ${esc(p.recommendation)}</p>` : ""}`;
    } else {
      const points = p.points || [];
      const maxScore = Math.max(100, ...points.map(t => t.score || 0));
      const bars = points.map(t =>
        `<div class="bar" style="height:${Math.max(4, ((t.score || 0) / maxScore) * 100)}%"><span>${esc(t.date)}</span></div>`).join("");
      inner = `
        <div class="status-line">
          <span class="status-pill">平均分 <b>${esc(p.avg_score ?? "-")}</b></span>
          <span class="status-pill ${p.direction === "up" ? "ok" : p.direction === "down" ? "err" : ""}">趋势: ${esc(p.direction || "-")}</span>
        </div>
        <div class="chart">${bars || '<div class="empty">暂无趋势数据</div>'}</div>
        ${p.recommendation ? `<p style="margin-top:10px;font-size:13px;color:var(--accent)">💡 ${esc(p.recommendation)}</p>` : ""}`;
    }
    parts.push(`<div class="panel"><h2>${label}${p.score != null ? ` · ${esc(p.score)} 分` : ""}</h2>${inner}</div>`);
  }

  container.innerHTML = parts.join("");
}

/* ---------------- 每日快照 ---------------- */
async function renderSnapshots(container) {
  const data = await getJSON(`${API}/dashboard/snapshots?days=30`);
  const rows = (data.items || []).map(s => `
    <tr>
      <td>${esc(s.date)}</td>
      <td>${esc(s.score)} <span class="badge ${gradeClass(s.grade)}">${esc(s.grade)}</span></td>
      <td>${esc(s.total)}</td>
      <td>${esc(s.unique)}</td>
      <td>${esc(s.new_this_week)}</td>
      <td>${esc(s.action_candidates)}</td>
      <td class="desc" title="${esc((s.issues || []).join("; "))}">${esc((s.issues || []).slice(0, 2).join("; ") || "-")}</td>
    </tr>`).join("") || `<tr><td colspan="7" class="empty">暂无快照数据</td></tr>`;

  container.innerHTML = `
    <div class="panel">
      <h2>每日采集快照 (最近 30 天)</h2>
      <table>
        <thead><tr><th>日期</th><th>质量分</th><th>总数</th><th>唯一仓库</th><th>新仓库</th><th>action候选</th><th>问题</th></tr></thead>
        <tbody>${rows}</tbody>
      </table>
    </div>`;
}

/* ---------------- 需求 ---------------- */
async function renderNeeds(container) {
  const data = await getJSON(`${API}/dashboard/needs`);
  const rows = (data.items || []).map(n => `
    <tr>
      <td>${esc(n.text)}</td>
      <td><span class="badge ${esc(n.status)}">${esc(n.status)}</span></td>
      <td><span class="badge ${esc(n.decision)}">${esc(n.decision)}</span></td>
      <td>${esc((n.matched_repos || []).length)}</td>
      <td>${esc((n.matched_repos || []).slice(0, 3).map(m => m.full_name).join(", ") || "-")}</td>
      <td style="font-size:12px;color:var(--muted)">${esc((n.created_at || "").slice(0, 16))}</td>
    </tr>`).join("") || `<tr><td colspan="6" class="empty">暂无需求记录</td></tr>`;

  container.innerHTML = `
    <div class="stats-grid">
      <div class="stat-card"><div class="num">${esc(data.total || 0)}</div><div class="label">总需求</div></div>
      <div class="stat-card"><div class="num">${esc((data.items || []).filter(n => n.status !== "matched").length)}</div><div class="label">待满足</div></div>
    </div>
    <div class="panel">
      <h2>条件触发引擎 · pending_needs</h2>
      <table>
        <thead><tr><th>需求</th><th>状态</th><th>决策</th><th>匹配数</th><th>匹配仓库</th><th>创建时间</th></tr></thead>
        <tbody>${rows}</tbody>
      </table>
      <p style="margin-top:10px;font-size:13px;color:var(--muted)">新项目入库后自动重匹配待满足需求 (双向生长回路), 可 <a href="javascript:void(0)" onclick="rematchNeeds()">立即重匹配</a></p>
    </div>`;
}

async function rematchNeeds() {
  try {
    const res = await fetch(`${API}/needs/rematch`, { method: "POST" });
    const data = await res.json();
    alert(`重匹配完成: ${data.matched || 0} 条需求被满足`);
    refresh("needs");
  } catch (e) {
    alert("重匹配失败: " + e.message);
  }
}

/* ---------------- 审核队列 ---------------- */
async function renderReview(container) {
  const data = await getJSON(`${API}/dashboard/review`);
  const rows = (data.items || []).map(r => {
    const rev = r.review || {};
    return `
    <tr>
      <td><a href="${esc(r.url)}" target="_blank">${esc(r.full_name)}</a></td>
      <td>${badge(r.category_decision)}</td>
      <td><span class="badge ${esc(r.status)}">${esc(r.status)}</span></td>
      <td>${esc(rev.verdict || "-")}</td>
      <td>${esc(rev.score ?? "-")}</td>
      <td class="desc" title="${esc((rev.risks || []).join("; "))}">${esc(rev.recommendation || "-")}</td>
      <td>
        ${r.status === "pending" ? `
          <button class="btn secondary" onclick="reviewApprove('${esc(r.full_name)}')">✅ 通过</button>
          <button class="btn danger" onclick="reviewReject('${esc(r.full_name)}')">❌ 拒绝</button>` : "-"}
      </td>
    </tr>`;
  }).join("") || `<tr><td colspan="7" class="empty">暂无审核队列</td></tr>`;

  container.innerHTML = `
    <div class="stats-grid">
      <div class="stat-card"><div class="num">${esc(data.pending || 0)}</div><div class="label">待审核</div></div>
      <div class="stat-card"><div class="num">${esc(data.approved || 0)}</div><div class="label">已通过</div></div>
      <div class="stat-card"><div class="num">${esc(data.rejected || 0)}</div><div class="label">已拒绝</div></div>
    </div>
    <div class="panel">
      <h2>生态升级审核队列 (LLM 审核 + 人工确认)</h2>
      <table>
        <thead><tr><th>仓库</th><th>决策</th><th>状态</th><th>LLM判定</th><th>评分</th><th>建议</th><th>操作</th></tr></thead>
        <tbody>${rows}</tbody>
      </table>
    </div>`;
}

async function reviewApprove(fn) {
  await fetch(`${API}/review/queue?name=${encodeURIComponent(fn)}&status=approved`, { method: "PUT" });
  refresh("review");
}
async function reviewReject(fn) {
  await fetch(`${API}/review/queue?name=${encodeURIComponent(fn)}&status=rejected`, { method: "PUT" });
  refresh("review");
}

/* ---------------- 数据源 (含预留扩展位) ---------------- */
async function renderSources(container) {
  const data = await getJSON(`${API}/sources`);
  const rows = (data || []).map(s => `
    <tr>
      <td><b>${esc(s.label)}</b><br><span class="muted">${esc(s.id)}</span></td>
      <td><span class="badge ${esc(s.status)}">${esc(s.status)}</span></td>
      <td>${s.enabled ? '<span style="color:var(--green)">✅ 已接入</span>' : '<span style="color:var(--yellow)">⏳ 预留扩展</span>'}</td>
      <td>${typeBadge(s.item_type)}</td>
      <td class="desc">${esc(s.description)}</td>
      <td class="desc">${esc(s.note || "-")}</td>
      <td class="desc">${esc((s.last_sync_at || "").slice(0, 19) || "-")}${s.last_items ? ` · ${esc(s.last_items)} 条` : ""}</td>
      <td>
        ${s.enabled ? `<button class="btn secondary" onclick="syncSource('${esc(s.id)}')">🔄 同步</button>` : `<span class="muted" style="font-size:12px">待开发</span>`}
      </td>
    </tr>`).join("") || '<tr><td colspan="8" class="empty">暂无数据源</td></tr>';

  container.innerHTML = `
    <div class="panel">
      <h2>数据源注册表</h2>
      <p style="font-size:13px;color:var(--muted);margin-bottom:12px">
        设计哲学: 一次获取、多人共享。当前已接入 GitHub 开源项目；
        <b style="color:var(--accent)">CNB 新项目 / 论文 / 热点 / 科技新闻</b> 已预留接口，
        将在后续 ISSUE 中接入并自动汇入每日信息流。
      </p>
      <table>
        <thead><tr><th>数据源</th><th>状态</th><th>接入</th><th>类型</th><th>说明</th><th>备注</th><th>最近同步</th><th>操作</th></tr></thead>
        <tbody>${rows}</tbody>
      </table>
    </div>
    <div class="panel">
      <h2>预留接口说明 (后续 ISSUE 开发)</h2>
      <ul class="issue-list">
        <li>🧩 <b>CNB 新项目</b>: 纳入 CNB 平台每日新增项目 (数据源 id: cnb-projects)</li>
        <li>📄 <b>论文</b>: arXiv 等每日新论文 (数据源 id: papers, 类型 paper)</li>
        <li>🔥 <b>热点信息</b>: 科技热点/趋势 (数据源 id: tech-trends, 类型 trend)</li>
        <li>📰 <b>科技进展/新闻</b>: 行业要闻 (数据源 id: news, 类型 news)</li>
      </ul>
      <p style="font-size:13px;color:var(--muted)">接入方式: 实现对应 fetch 并归一化为 Item (统一契约 schema_version=1.0), 即可自动汇入 <code>/api/v1/feed</code> 信息流与每日聚合。</p>
    </div>`;
}

async function syncSource(id) {
  if (!confirm(`确认手动同步数据源 ${id} ? (GitHub 源会重跑 fetch, 消耗 API 配额)`)) return;
  try {
    const res = await fetch(`${API}/sync/${id}`, { method: "POST" });
    const data = await res.json();
    alert(`同步结果: [${data.status}] ${data.message || ""} 条目数: ${data.items}`);
    refresh("sources");
  } catch (e) {
    alert("同步失败: " + e.message);
  }
}

/* ---------------- 自愈中心 ---------------- */
async function renderHeal(container) {
  let health = null;
  try { health = await getJSON(`${API}/health`); } catch (e) { health = { error: e.message }; }

  let logs = [];
  try { logs = (await getJSON(`${API}/heal/log?limit=20`)).incidents || []; } catch (e) { logs = []; }

  let healthHtml = "";
  if (health.error) {
    healthHtml = `<div class="empty">❌ ${esc(health.error)}</div>`;
  } else {
    const checks = Object.entries(health.checks || {}).map(([k, v]) => `
      <tr>
        <td>${esc(k)}</td>
        <td>${v.ok ? '<span style="color:var(--green)">✅ 正常</span>' : `<span style="color:var(--red)">❌ ${esc(v.severity || "")}</span>`}</td>
        <td class="desc" title="${esc(v.detail || "")}">${esc(v.detail || "")}</td>
      </tr>`).join("");
    healthHtml = `
      <div class="status-line">
        <span class="status-pill ${health.ok ? "ok" : "err"}">${health.ok ? "✅ 管道健康" : "⚠️ 存在待修复问题"}</span>
        <span class="status-pill">high: ${esc(health.summary?.high || 0)}</span>
        <span class="status-pill">medium: ${esc(health.summary?.medium || 0)}</span>
        <span class="status-pill">low: ${esc(health.summary?.low || 0)}</span>
      </div>
      <table>
        <thead><tr><th>检查项</th><th>状态</th><th>详情</th></tr></thead>
        <tbody>${checks || '<tr><td colspan="3" class="empty">无检查项</td></tr>'}</tbody>
      </table>
      <div style="margin-top:16px;display:flex;gap:8px">
        <button class="btn" onclick="runHeal(false)">🛠 执行自动修复</button>
        <button class="btn secondary" onclick="runHeal(true)">🔍 仅检查</button>
      </div>`;
  }

  const logRows = logs.map(l => `
    <tr>
      <td style="font-size:12px;color:var(--muted)">${esc((l.ts || "").slice(0, 19))}</td>
      <td>${l.ok ? '<span style="color:var(--green)">✅</span>' : '<span style="color:var(--red)">❌</span>'}</td>
      <td>${esc(l.event || "")}</td>
      <td class="desc">${esc(l.detail || "")}</td>
    </tr>`).join("") || `<tr><td colspan="4" class="empty">暂无愈合记录</td></tr>`;

  container.innerHTML = `
    <div class="panel">
      <h2>管道健康检查</h2>
      ${healthHtml}
    </div>
    <div class="panel">
      <h2>自愈日志 (最近 20 条)</h2>
      <table>
        <thead><tr><th>时间</th><th>结果</th><th>事件</th><th>详情</th></tr></thead>
        <tbody>${logRows}</tbody>
      </table>
    </div>`;
}

async function runHeal(checkOnly) {
  try {
    const res = await fetch(`${API}/heal`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ check_only: checkOnly }),
    });
    const data = await res.json();
    const actions = data.actions || [];
    const probs = data.problems || [];
    let msg = `健康: ${data.ok ? "✅" : "❌"}\n`;
    if (probs.length) msg += `发现 ${probs.length} 个问题:\n` + probs.map(p => ` - ${p.title}`).join("\n");
    if (actions.length) msg += `\n执行修复:\n` + actions.map(a => ` - ${a.ok ? "✅" : "❌"} ${a.action}: ${a.detail}`).join("\n");
    alert(msg);
    refresh("heal");
  } catch (e) {
    alert("自愈执行失败: " + e.message);
  }
}

/* ---------------- 二次整理层: 关联分析 (ISSUE #7) ---------------- */

const REL_MODELS = ["correlation", "lead_lag", "vol_spillover", "linear", "momentum", "exp_decay", "var", "rolling_corr", "regime_shift", "event_study", "self_corr"];

function verdictBadge(v) {
  const map = { strong: "强", good: "良好", weak: "弱", insufficient: "不足" };
  return `<span class="badge verdict-${esc(v)}">${esc(map[v] || v)}</span>`;
}

function dimShort(d) {
  if (!d) return "*";
  const parts = [];
  if (d.symbol && d.symbol !== "*") parts.push(d.symbol);
  if (d.market && d.market !== "*") parts.push(d.market);
  if (d.country && d.country !== "*") parts.push(d.country);
  if (d.exchange && d.exchange !== "*") parts.push(d.exchange);
  if (d.asset && d.asset !== "*") parts.push(d.asset);
  if (d.timeframe && d.timeframe !== "*") parts.push(d.timeframe);
  return parts.join(".") || "*";
}

function dimKey(d) {
  if (!d) return "";
  return [d.market, d.country, d.exchange, d.symbol, d.asset, d.timeframe]
    .map(x => (x == null || x === "") ? "*" : x).join(".");
}

function edgeRow(e) {
  const m = e.metrics || {};
  const verdict = (e.comparison && e.comparison.verdict) || "";
  const hit = e.comparison && e.comparison.metrics ? e.comparison.metrics.hit_rate : "";
  const r2 = e.comparison && e.comparison.metrics ? e.comparison.metrics.r2 : "";
  const bar = `<div class="rel-bar"><div class="rel-bar-fill" style="width:${Math.round((e.strength || 0) * 100)}%"></div></div>`;
  const modelTag = e.model === "rolling_corr" ? "时变相关" : e.model === "regime_shift" ? "结构突变" : e.model === "event_study" ? "事件研究" : e.model === "self_corr" ? "自相关" : e.model;
  const layerBadge = e.inter_layer
    ? `<span class="badge" style="background:#fb923c22;color:#fb923c">层间·跨域</span>`
    : e.intra_layer
      ? `<span class="badge" style="background:#34d39922;color:#34d399">层内·同域</span>` : "";
  return `
    <tr>
      <td class="rel-edge">${esc(dimShort(e.from))} <span class="arrow">→</span> ${esc(dimShort(e.to))}</td>
      <td class="center">${layerBadge}</td>
      <td>${bar}<span class="rel-strength">${(e.strength || 0).toFixed(3)}</span></td>
      <td class="center">${e.sign > 0 ? "<span class='pos'>+</span>" : e.sign < 0 ? "<span class='neg'>−</span>" : "0"}</td>
      <td class="center">${esc(e.lag)}</td>
      <td class="center">${(e.stability || 0).toFixed(2)}</td>
      <td><span class="badge">${esc(modelTag)}</span></td>
      <td class="center">${r2 !== "" ? esc(r2) : "-"}${hit !== "" ? ` <span class="muted">hit ${esc(hit)}</span>` : ""}</td>
      <td>${verdict ? verdictBadge(verdict) : "-"}</td>
      <td><a href="#" class="link" data-edge="${esc(e.edge)}" data-dim="${esc(JSON.stringify({from: e.from, to: e.to}))}">对比曲线</a></td>
    </tr>`;
}

function drawCurve(canvas, curve, title) {
  const dates = curve.dates || [];
  const actual = curve.actual || [];
  const predicted = curve.predicted || [];
  if (!dates.length || !canvas) return;
  const ctx = canvas.getContext("2d");
  const W = canvas.width, H = canvas.height;
  ctx.clearRect(0, 0, W, H);
  const pad = { l: 46, r: 12, t: 12, b: 22 };
  const all = actual.concat(predicted);
  let min = Math.min(...all), max = Math.max(...all);
  if (min === max) { min -= 1; max += 1; }
  const x = i => pad.l + (i / Math.max(1, dates.length - 1)) * (W - pad.l - pad.r);
  const y = v => pad.t + (1 - (v - min) / (max - min)) * (H - pad.t - pad.b);
  // grid
  ctx.strokeStyle = "#2a2f3a"; ctx.lineWidth = 1;
  for (let g = 0; g <= 4; g++) {
    const gy = pad.t + (g / 4) * (H - pad.t - pad.b);
    ctx.beginPath(); ctx.moveTo(pad.l, gy); ctx.lineTo(W - pad.r, gy); ctx.stroke();
    const val = max - (g / 4) * (max - min);
    ctx.fillStyle = "#8b93a7"; ctx.font = "10px sans-serif"; ctx.textAlign = "right";
    ctx.fillText(val.toFixed(3), pad.l - 4, gy + 3);
  }
  // actual
  ctx.strokeStyle = "#4fc3f7"; ctx.lineWidth = 1.6; ctx.beginPath();
  actual.forEach((v, i) => { const px = x(i), py = y(v); i ? ctx.lineTo(px, py) : ctx.moveTo(px, py); });
  ctx.stroke();
  // predicted
  ctx.strokeStyle = "#ffb74d"; ctx.lineWidth = 1.6; ctx.setLineDash([4, 3]); ctx.beginPath();
  predicted.forEach((v, i) => { const px = x(i), py = y(v); i ? ctx.lineTo(px, py) : ctx.moveTo(px, py); });
  ctx.stroke(); ctx.setLineDash([]);
  ctx.fillStyle = "#8b93a7"; ctx.font = "10px sans-serif";
  ctx.fillText(title || "", pad.l, H - 2);
}

/* 时变关联曲线 (rolling_corr) */
function drawRollingCorr(canvas, curve, title) {
  const pts = curve || [];
  if (!pts.length || !canvas) return;
  const ctx = canvas.getContext("2d");
  const W = canvas.width, H = canvas.height;
  ctx.clearRect(0, 0, W, H);
  const pad = { l: 46, r: 12, t: 12, b: 22 };
  let min = Math.min(...pts.map(p => p.corr)), max = Math.max(...pts.map(p => p.corr));
  const lim = Math.max(Math.abs(min), Math.abs(max), 0.2);
  min = -lim; max = lim;
  const x = i => pad.l + (i / Math.max(1, pts.length - 1)) * (W - pad.l - pad.r);
  const y = v => pad.t + (1 - (v - min) / (max - min)) * (H - pad.t - pad.b);
  // zero line
  ctx.strokeStyle = "#3a4150"; ctx.lineWidth = 1; ctx.setLineDash([3, 3]);
  ctx.beginPath(); ctx.moveTo(pad.l, y(0)); ctx.lineTo(W - pad.r, y(0)); ctx.stroke(); ctx.setLineDash([]);
  // grid + labels
  for (let g = 0; g <= 4; g++) {
    const gy = pad.t + (g / 4) * (H - pad.t - pad.b);
    ctx.strokeStyle = "#2a2f3a"; ctx.beginPath(); ctx.moveTo(pad.l, gy); ctx.lineTo(W - pad.r, gy); ctx.stroke();
    const val = max - (g / 4) * (max - min);
    ctx.fillStyle = "#8b93a7"; ctx.font = "10px sans-serif"; ctx.textAlign = "right";
    ctx.fillText(val.toFixed(2), pad.l - 4, gy + 3);
  }
  // corr line (红=负, 绿=正)
  pts.forEach((p, i) => {
    const px = x(i), py = y(p.corr);
    ctx.strokeStyle = p.corr >= 0 ? "#34d399" : "#f87171";
    ctx.lineWidth = 1.6;
    if (i === 0) ctx.beginPath();
    ctx.lineTo(px, py);
    if (i === pts.length - 1) ctx.stroke();
  });
  ctx.fillStyle = "#8b93a7"; ctx.font = "10px sans-serif";
  ctx.fillText(title || "时变关联强度", pad.l, H - 2);
}

/* 网络力导向简易图 (Canvas, 无外部依赖) */
/* 分层漏斗拓扑图 (Canvas, 无外部依赖)
 * 把「功能域分层」的节点按层归组渲染成自上而下的漏斗：
 *   资产大类 → 地区 → 交易所 → 品种 → 交易类型 → 时间级别
 * - 每一层一条横向带 (漏斗层)
 * - 层内边 (intra_layer, 同功能域分支内联动) 用绿色短弧/点
 * - 层间边 (inter_layer, 跨功能域传导) 用橙色长线
 * - 节点颜色表示 hub 强度, 尺寸表示影响强度
 */
const FUNNEL_LAYER_IDS = ["data_class", "region", "exchange", "instrument", "trade_type", "time_level"];

function nodeLayerId(n) {
  // 节点归属：取 active_layers 里**最顶层(漏斗口)**作为该节点的功能域归属
  const act = n.active_layers || [];
  if (!act.length) return "*";
  const top = act[0];
  return top.id || "*";
}

function drawFunnel(canvas, net, labels) {
  const nodes = net.nodes || [];
  const edges = net.edges || [];
  if (!nodes.length || !canvas) return;
  const ctx = canvas.getContext("2d");
  const W = canvas.width, H = canvas.height;
  ctx.clearRect(0, 0, W, H);

  // 按漏斗层分组节点
  const groups = {};
  nodes.forEach(n => {
    const g = nodeLayerId(n);
    (groups[g] = groups[g] || []).push(n);
  });
  const present = Object.keys(groups).filter(g => g !== "*");
  const rows = present.length || 1;
  const topPad = 34, bottomPad = 16, rowGap = 6;
  const rowH = (H - topPad - bottomPad - rowGap * (rows - 1)) / rows;

  const layerName = {};
  const LABELS = { data_class: "资产大类/功能域", region: "地区/国家", exchange: "交易所/市场",
                   instrument: "品种/标的", trade_type: "交易类型", time_level: "时间级别" };
  FUNNEL_LAYER_IDS.forEach(id => { layerName[id] = LABELS[id] || id; });

  const rowInfo = [];
  present.forEach((g, i) => {
    const y0 = topPad + i * (rowH + rowGap);
    rowInfo.push({ g, y: y0 + rowH / 2, y0, y1: y0 + rowH, nodes: groups[g] });
  });

  const byKey = {};
  const pos = {};
  rowInfo.forEach(row => {
    const g = row.g;
    // 横向布局：按 total_strength 降序排布
    const ns = row.nodes.slice().sort((a, b) => (b.total_strength || 0) - (a.total_strength || 0));
    const n = ns.length;
    const lpad = 118;  // 左侧留漏斗层标签
    const rpad = 18;
    ns.forEach((node, i) => {
      const x = lpad + (i + 0.5) * (W - lpad - rpad) / n;
      byKey[node.key] = node;
      pos[node.key] = { x, y: row.y };
    });
  });

  // 漏斗层带背景 + 标签
  ctx.font = "11px sans-serif";
  FUNNEL_LAYER_IDS.forEach((id, li) => {
    const row = rowInfo.find(r => r.g === id);
    if (!row) return;
    ctx.fillStyle = "rgba(148,163,184,0.06)";
    ctx.fillRect(8, row.y0, W - 16, rowH);
    ctx.fillStyle = "rgba(148,163,184,0.5)";
    ctx.textAlign = "left";
    ctx.fillText(`${layerName[id]}  (L${li})`, 14, row.y0 + rowH / 2 + 4);
  });

  // 边：先画层间(长线), 再画层内(短线/弧)，避免遮挡
  const drawEdge = (e, color, dash, width) => {
    const a = byKey[e.from], b = byKey[e.to];
    if (!a || !b) return;
    ctx.strokeStyle = color;
    ctx.lineWidth = width;
    ctx.setLineDash(dash || []);
    ctx.beginPath();
    ctx.moveTo(pos[a.key].x, pos[a.key].y);
    ctx.lineTo(pos[b.key].x, pos[b.key].y);
    ctx.stroke();
    ctx.setLineDash([]);
  };
  // 层间边: 跨功能域传导 (橙/红)
  edges.filter(e => e.inter_layer).forEach(e => {
    drawEdge(e, e.sign >= 0 ? "rgba(251,146,60,0.55)" : "rgba(248,113,113,0.55)", [4, 3], Math.max(0.5, (e.strength || 0) * 2.4));
  });
  // 层内边: 同功能域分支内联动 (绿)
  edges.filter(e => e.intra_layer).forEach(e => {
    drawEdge(e, "rgba(52,211,153,0.5)", [], Math.max(0.5, (e.strength || 0) * 2.4));
  });

  // 节点
  nodes.forEach(n => {
    const r = 7 + (n.hub_score || 0) * 12;
    ctx.beginPath(); ctx.arc(pos[n.key].x, pos[n.key].y, r, 0, Math.PI * 2);
    ctx.fillStyle = n.hub_score >= 0.7 ? "#fbbf24" : n.hub_score >= 0.4 ? "#4fc3f7" : "#334155";
    ctx.fill();
    ctx.strokeStyle = "#0b1220"; ctx.lineWidth = 1.5; ctx.stroke();
    const label = (labels && labels[n.key]) || n.key.split(".").filter(s => s !== "*").join(".") || n.key;
    ctx.fillStyle = "#cbd5e1"; ctx.font = "9px sans-serif"; ctx.textAlign = "center";
    ctx.fillText(label.length > 12 ? label.slice(0, 11) + "…" : label, pos[n.key].x, pos[n.key].y + r + 9);
  });

  // 漏斗方向标注
  ctx.fillStyle = "rgba(148,163,184,0.6)"; ctx.font = "10px sans-serif"; ctx.textAlign = "right";
  ctx.fillText("▼ 漏斗方向: 粗(顶层) → 细(底层)", W - 12, 14);
}

function drawNetwork(canvas, net, labels) {
  drawFunnel(canvas, net, labels);
}

async function renderRelations(container) {
  const [matrix, edgesData, netData] = await Promise.all([
    getJSON(`${API}/relations/matrix`),
    getJSON(`${API}/relations/edges?limit=500`),
    getJSON(`${API}/relations/network?min_strength=0.03`),
  ]);
  const edges = edgesData.items || [];
  const dims = (matrix.dimensions || []).map(d => dimShort(d));
  const counts = { strong: 0, good: 0, weak: 0, insufficient: 0 };
  edges.forEach(e => { if (e.comparison && counts[e.comparison.verdict] != null) counts[e.comparison.verdict]++; });
  const net = netData || { nodes: [], edges: [], clusters: [], summary: {} };
  const ns = net.summary || {};
  const labels = {};
  (matrix.dimensions || []).forEach(d => { labels[dimShort(d)] = dimShort(d); });
  net.nodes.forEach(n => { if (n.dim) labels[n.key] = dimShort(n.dim); });

  let html = `
  <div class="panel">
    <h2>🔗 二次整理层 · 金融各市场两两关联</h2>
    <p class="muted">跨市场 / 跨国家 / 跨品种 / 跨交易类型 / 跨时间级别的<b>两两双向</b>影响评估与量化；每条边 A→B 独立建模、独立验证预测能力。</p>
    <div class="rel-toolbar">
      <button class="btn" id="rel-run-demo">▶ 运行演示数据</button>
      <select id="rel-model-filter" class="select">
        <option value="">全部模型</option>
        ${REL_MODELS.map(m => `<option value="${m}">${esc(m)}</option>`).join("")}
      </select>
      <select id="rel-layer-filter" class="select">
        <option value="">全部层级关系</option>
        <option value="intra_layer">层内(同功能域)</option>
        <option value="inter_layer">层间(跨功能域)</option>
      </select>
      <span class="muted">矩阵 ${esc(dims.length)} 维 · ${esc(edgesData.count)} 条有向边</span>
    </div>
    <div class="stat-row">
      ${Object.entries(counts).map(([k, v]) => `<div class="stat-card"><div class="num">${esc(v)}</div><div class="label">${verdictBadge(k)}</div></div>`).join("")}
    </div>
    <div class="rel-dims muted">维度: ${dims.map(esc).join(" &nbsp;·&nbsp; ")}</div>
  </div>
  <div class="panel">
    <h2>🕸️ 分层漏斗 · 传导网络（按功能域分层）</h2>
    <p class="muted">多级条件筛选的<b>分层漏斗</b>：资产大类 → 地区 → 交易所 → 品种 → 交易类型 → 时间级别。
      每个节点归属到其最深一层功能域；<b style="color:#34d399">绿色=层内边</b>（同功能域分支内联动）
      <b style="color:#fb923c">橙色/红色=层间边</b>（跨功能域传导）。后续模型按此分层分别学习<b>层内</b>与<b>层间</b>关系。</p>
    <div class="stat-row">
      <div class="stat-card"><div class="num">${esc(ns.node_count ?? 0)}</div><div class="label">网络节点</div></div>
      <div class="stat-card"><div class="num">${esc(ns.edge_count ?? 0)}</div><div class="label">有效边</div></div>
      <div class="stat-card"><div class="num">${esc(ns.intra_layer_edges ?? 0)}</div><div class="label">层内边(同域)</div></div>
      <div class="stat-card"><div class="num">${esc(ns.inter_layer_edges ?? 0)}</div><div class="label">层间边(跨域)</div></div>
      <div class="stat-card"><div class="num">${esc(ns.density ?? 0)}</div><div class="label">网络密度</div></div>
      <div class="stat-card"><div class="num">${esc(ns.cluster_count ?? 0)}</div><div class="label">联动簇</div></div>
    </div>
    <div class="rel-network-wrap">
      <canvas id="rel-network-canvas" width="900" height="360"></canvas>
    </div>
    <div class="rel-dims muted">🧭 功能域分层: ${FUNNEL_LAYER_IDS.map(id => esc(id)).join(" → ")}</div>
    <div class="rel-dims muted">📌 节点归属层: ${(net.layer_groups || []).map(g => esc(g.label)).join(" &nbsp;·&nbsp; ") || "-"}</div>
    <div class="rel-dims muted">
      🧭 最强枢纽: ${(ns.top_hubs || []).slice(0, 3).map(h => esc(h.key)).join(" &nbsp;·&nbsp; ") || "-"}
      &nbsp;&nbsp;|&nbsp;&nbsp;
      🎯 最强被影响: ${(ns.top_authorities || []).slice(0, 3).map(a => esc(a.key)).join(" &nbsp;·&nbsp; ") || "-"}
    </div>
    <div class="rel-dims muted">💠 联动簇: ${(net.clusters || []).map(c => esc(c.label)).join(" &nbsp;·&nbsp; ") || "-"}</div>
  </div>
  <div class="panel">
    <h2>📊 两两关联边（按强度排序）</h2>
    <table class="rel-table">
      <thead><tr><th>关联 (A → B)</th><th>层级</th><th>强度</th><th>方向</th><th>领先</th><th>稳定</th><th>模型</th><th>预测能力</th><th>评价</th><th></th></tr></thead>
      <tbody id="rel-edges-body">${edges.map(edgeRow).join("") || '<tr><td colspan="10" class="empty">暂无数据, 点击「运行演示数据」或等待数据获取层接入</td></tr>'}</tbody>
    </table>
  </div>
  <div class="panel" id="rel-detail">
    <h2>📈 预测 vs 实际 曲线对比</h2>
    <p class="muted" id="rel-detail-tip">点击任意一条关联的「对比曲线」查看模型预测影响曲线 vs 实际影响曲线。</p>
    <div id="rel-detail-body"></div>
  </div>`;
  container.innerHTML = html;

  container.querySelector("#rel-run-demo").addEventListener("click", async () => {
    try {
      await fetch(`${API}/relations/run-demo`, { method: "POST" });
      alert("✅ 演示数据已生成并落盘 (56 条两两双向边), 正在刷新…");
      renderRelations(container);
    } catch (e) { alert("运行失败: " + e.message); }
  });

  async function applyRelFilter() {
    const m = container.querySelector("#rel-model-filter").value;
    const rel = container.querySelector("#rel-layer-filter").value;
    const params = new URLSearchParams({ limit: "500" });
    if (m) params.set("model", m);
    if (rel) params.set("rel", rel);
    const url = `${API}/relations/edges?${params.toString()}`;
    try {
      const data = await getJSON(url);
      const body = document.getElementById("rel-edges-body");
      const tip = rel === "intra_layer" ? "层内(同功能域分支内联动)"
                : rel === "inter_layer" ? "层间(跨功能域传导)" : "该筛选暂无数据";
      body.innerHTML = (data.items || []).map(edgeRow).join("") || `<tr><td colspan="10" class="empty">${tip}</td></tr>`;
      bindEdgeLinks(container);
    } catch (e) { alert("筛选失败: " + e.message); }
  }

  container.querySelector("#rel-model-filter").addEventListener("change", applyRelFilter);
  container.querySelector("#rel-layer-filter").addEventListener("change", applyRelFilter);

  bindEdgeLinks(container);
  drawNetwork(document.getElementById("rel-network-canvas"), net, labels);
}

function bindEdgeLinks(container) {
  container.querySelectorAll("a[data-edge]").forEach(a => {
    a.addEventListener("click", async ev => {
      ev.preventDefault();
      const edge = a.dataset.edge;
      const dim = JSON.parse(a.dataset.dim || "{}");
      try {
        const data = await getJSON(`${API}/relations/edge/${encodeURIComponent(edge)}`);
        const cmp = data.comparison;
        const body = document.getElementById("rel-detail-body");
        const tip = document.getElementById("rel-detail-tip");
        tip.textContent = `${data.edge} · 模型 ${data.model} · 强度 ${(data.strength || 0).toFixed(3)} · 领先 ${data.lag} 期 · 方向 ${data.sign > 0 ? "+" : data.sign < 0 ? "−" : "0"}`;

        // 多模型自动择优 (对比曲线旁)
        let bestHtml = "";
        try {
          const mr = await fetch(`${API}/relations/compare-models`, {
            method: "POST", headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
              label_a: dimShort(dim.from), label_b: dimShort(dim.to),
              from_key: dimKey(dim.from),
              to_key: dimKey(dim.to),
            }),
          });
          if (mr.ok) {
            const mj = await mr.json();
            const rank = mj.ranking || [];
            if (rank.length) {
              const best = mj.best || {};
              const bestMetrics = best.metrics || {};
              bestHtml = `
                <div class="panel" style="margin-top:10px">
                  <h3>🧪 多模型自动择优（换模型迭代）</h3>
                  <div class="rel-metrics">
                    <div class="stat-card"><div class="num">${esc(best.model || "-")}</div><div class="label">最优模型</div></div>
                    <div class="stat-card"><div class="num">${esc(bestMetrics.r2 ?? "-")}</div><div class="label">最优 R²</div></div>
                    <div class="stat-card"><div class="num">${esc(bestMetrics.hit_rate ?? "-")}</div><div class="label">最优命中率</div></div>
                    <div class="stat-card"><div class="num">${best.verdict ? verdictBadge(best.verdict) : "-"}</div><div class="label">最优评价</div></div>
                  </div>
                  <table class="rel-table"><thead><tr><th>模型</th><th>综合得分</th><th>R²</th><th>命中率</th><th>评价</th></tr></thead><tbody>
                    ${rank.map(r => `<tr><td class="rel-edge">${esc(r.model)}</td><td>${esc(r.score)}</td><td>${esc(r.r2 ?? "-")}</td><td>${esc(r.hit_rate ?? "-")}</td><td>${r.verdict ? verdictBadge(r.verdict) : "-"}</td></tr>`).join("")}
                  </tbody></table>
                </div>`;
            }
          }
        } catch (e) { /* 无数据时跳过 */ }

        if (!cmp || !cmp.curve || !cmp.curve.dates.length) {
          body.innerHTML = '<div class="empty">该边无测试段对比数据 (样本不足)</div>' + bestHtml;
          return;
        }
        const m = cmp.metrics || {};
        body.innerHTML = `
          <canvas id="rel-canvas" width="900" height="260"></canvas>
          <div class="rel-metrics">
            <div class="stat-card"><div class="num">${esc(m.r2 ?? "-")}</div><div class="label">测试段 R²</div></div>
            <div class="stat-card"><div class="num">${esc(m.hit_rate ?? "-")}</div><div class="label">方向命中率</div></div>
            <div class="stat-card"><div class="num">${esc(m.rmse ?? "-")}</div><div class="label">RMSE</div></div>
            <div class="stat-card"><div class="num">${esc(m.mae ?? "-")}</div><div class="label">MAE</div></div>
            <div class="stat-card"><div class="num">${verdictBadge(cmp.verdict)}</div><div class="label">预测能力</div></div>
          </div>
          ${data.curve && data.curve.length ? `
          <h3>📉 时变关联强度（变量型关联）</h3>
          <canvas id="rel-rolling-canvas" width="900" height="200"></canvas>
          <p class="muted">关联强度随时间波动 (均值 ${esc((data.params && data.params.mean_corr) ?? "-")} · 波动 ${esc((data.params && data.params.std) ?? "-")} · 趋势 ${esc((data.params && data.params.trend) ?? "-")})</p>` : ""}
          <div class="rel-iter">${(cmp.iterations || []).map(i => `<div>💡 ${esc(i)}</div>`).join("")}</div>` + bestHtml;
        drawCurve(document.getElementById("rel-canvas"), cmp.curve,
          `蓝=实际影响曲线  橙(虚线)=模型预测影响曲线 (${dimShort(data.from)} → ${dimShort(data.to)})`);
        if (data.curve && data.curve.length) {
          drawRollingCorr(document.getElementById("rel-rolling-canvas"), data.curve,
            `时变关联强度 (${dimShort(data.from)} → ${dimShort(data.to)})`);
        }
      } catch (e) {
        document.getElementById("rel-detail-body").innerHTML = `<div class="empty">加载失败: ${esc(e.message)}</div>`;
      }
    });
  });
}

/* ---------------- 视图切换 ---------------- */
const VIEWS = {
  overview: renderOverview,
  digest: renderDigest,
  feed: renderFeed,
  repos: renderRepos,
  clusters: renderClusters,
  quality: renderQuality,
  snapshots: renderSnapshots,
  needs: renderNeeds,
  review: renderReview,
  sources: renderSources,
  relations: renderRelations,
  heal: renderHeal,
};

async function refresh(view) {
  const container = document.getElementById(`view-${view}`);
  if (!container) return;
  container.innerHTML = '<div class="loading">加载中...</div>';
  try {
    await VIEWS[view](container);
  } catch (e) {
    container.innerHTML = `<div class="empty">❌ 加载失败: ${esc(e.message)}</div>`;
  }
}

document.addEventListener("DOMContentLoaded", () => {
  document.querySelectorAll(".tab").forEach(btn => {
    btn.addEventListener("click", () => {
      document.querySelectorAll(".tab").forEach(b => b.classList.remove("active"));
      btn.classList.add("active");
      const view = btn.dataset.view;
      document.querySelectorAll(".view").forEach(v => v.classList.remove("active"));
      document.getElementById(`view-${view}`).classList.add("active");
      refresh(view);
    });
  });
  refresh("overview");
});
