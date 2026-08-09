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
