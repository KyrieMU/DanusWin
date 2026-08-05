"use strict";
const S = {
  projects: [], current: null, timer: null, installTimer: null,
  feedSeen: new Set(), factDots: {}, lastFacts: {},
};

const $ = (id) => document.getElementById(id);

function esc(s) {
  return String(s == null ? "" : s).replace(/[&<>"']/g, (c) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"
  }[c]));
}

function toast(msg, err) {
  const t = $("toast");
  t.textContent = msg;
  t.className = "show" + (err ? " err" : "");
  clearTimeout(t._h);
  t._h = setTimeout(() => (t.className = ""), 3600);
}

async function api(path, method = "GET", body) {
  const opts = { method, headers: {} };
  if (body !== undefined) {
    opts.headers["Content-Type"] = "application/json";
    opts.body = JSON.stringify(body);
  }
  const r = await fetch(path, opts);
  let data = null;
  try { data = await r.json(); } catch (e) { /* ignore */ }
  if (!r.ok) throw new Error((data && data.detail) || r.statusText || ("HTTP " + r.status));
  return data;
}

function fmtAge(s) {
  if (s == null) return "—";
  if (s < 60) return Math.round(s) + "s";
  if (s < 3600) return Math.floor(s / 60) + "m " + Math.round(s % 60) + "s";
  return Math.floor(s / 3600) + "h " + Math.floor((s % 3600) / 60) + "m";
}

const LABELS = {
  working: ["工作中", "working"], stuck: ["疑似卡住", "stuck"], dead: ["已停止", "idle"],
  stopped: ["已停止", "idle"], error: ["错误", "error"], created: ["已创建", "idle"],
  terminated: ["已终止", "idle"], deadline: ["到期停止", "idle"], max_rounds: ["达轮次上限", "idle"],
};
function labelPill(l) {
  const k = LABELS[l] || [l, "idle"];
  return `<span class="pill ${k[1] === "error" ? "bad" : k[1] === "stuck" ? "warn" : k[1] === "working" ? "blue" : ""}">${esc(k[0])}</span>`;
}
function workerCls(l) { return (LABELS[l] || [l, "idle"])[1]; }

// ------------------------------------------------------------------ tabs --
document.querySelectorAll(".tab-btn").forEach((b) => {
  b.addEventListener("click", () => {
    document.querySelectorAll(".tab-btn").forEach((x) => x.classList.remove("active"));
    document.querySelectorAll(".tab").forEach((x) => x.classList.remove("active"));
    b.classList.add("active");
    $("tab-" + b.dataset.tab).classList.add("active");
    if (b.dataset.tab === "overview") loadOverview();
    if (b.dataset.tab === "projects") loadProjects();
    if (b.dataset.tab === "facts") { fillFactsSelect(); loadFacts(); }
    if (b.dataset.tab === "settings") stLoad();
  });
});

// ------------------------------------------------------------ overview --
async function loadOverview() {
  try {
    const o = await api("/api/overview");
    $("ov-key").textContent = o.has_key ? "已配置" : "未配置";
    $("ov-key-sub").textContent = o.settings.provider === "opencode" ? "OpenCode Go" : "DeepSeek 直连";
    $("card-key").className = "card" + (o.has_key ? " good" : "");
    $("ov-codex").textContent = o.codex.found ? "已就绪" : "未安装";
    $("ov-codex-sub").textContent = o.codex.codex_js ? o.codex.codex_js.split("\\").pop() : "点「安装 Codex CLI」";
    $("card-codex").className = "card" + (o.codex.found ? " good" : "");
    $("ov-projects").textContent = String(o.projects.length);
    $("ov-projects-sub").textContent = o.projects.reduce((a, p) => a + p.live, 0) + " 个 worker 运行中";
    const v = o.verify;
    $("ov-verify").textContent = v.up ? "运行中" : "未运行";
    $("ov-verify-sub").textContent = v.up ? "端口 " + (v.url || "").replace("http://127.0.0.1:", "").replace("/health", "") : "点「启动验证服务」";
    $("card-verify").className = "card" + (v.up ? " good" : "");
    const badge = $("verify-badge");
    badge.className = "badge " + (v.up ? "ok" : "bad");
    $("verify-badge-text").textContent = "验证服务: " + (v.up ? "运行中" : "已停止");
    S.projects = o.projects;
  } catch (e) { console.error(e); }
}

async function ovDetect() {
  try {
    const d = await api("/api/setup/detect", "POST");
    $("ov-result").textContent = "检测结果:\n  node: " + (d.node_bin || "未找到") +
      "\n  codex.js: " + (d.codex_js || "未找到（请先安装 Codex CLI）");
    toast("检测完成");
  } catch (e) { toast(e.message, true); }
}

async function ovInstall() {
  try {
    await api("/api/setup/install-codex", "POST");
    toast("开始安装 Codex CLI（需几分钟）");
    clearInterval(S.installTimer);
    S.installTimer = setInterval(async () => {
      try {
        const st = await api("/api/setup/install-status");
        $("ov-result").textContent = st.log;
        if (!st.running) { clearInterval(S.installTimer); toast("安装结束，点「检测环境」确认"); loadOverview(); }
      } catch (e) { clearInterval(S.installTimer); toast(e.message, true); }
    }, 1500);
  } catch (e) { toast(e.message, true); }
}

async function ovProvider() {
  try {
    const r = await api("/api/setup/write-provider", "POST");
    $("ov-result").textContent = "已写入模型配置:\n  " + r.config + "\n  " + r.models +
      "\n  base_url: " + r.base_url + "  model: " + r.model;
    toast("模型配置已写入");
  } catch (e) { toast(e.message, true); }
}

async function ovPing() {
  $("ov-result").textContent = "正在测试连接…";
  try {
    const r = await api("/api/setup/ping", "POST");
    $("ov-result").textContent = JSON.stringify(r, null, 2);
    toast(r.ok ? "连接成功" : "连接失败", !r.ok);
  } catch (e) { toast(e.message, true); }
}

async function ovVerifyStart() { try { toast((await api("/api/verify/start", "POST")).detail); loadOverview(); } catch (e) { toast(e.message, true); } }
async function ovVerifyStop() { try { await api("/api/verify/stop", "POST"); toast("验证服务已停止"); loadOverview(); } catch (e) { toast(e.message, true); } }

// ------------------------------------------------------------ projects --
async function loadProjects() {
  try {
    S.projects = await api("/api/projects");
    const list = $("project-list");
    if (!S.projects.length) {
      list.innerHTML = '<div class="empty">还没有项目，左边新建一个</div>';
      return;
    }
    list.innerHTML = S.projects.map((p) => `
      <div class="list-item ${S.current === p.name ? "active" : ""}" onclick="selectProject('${esc(p.name)}')">
        <div class="t">${esc(p.name)}</div>
        <div class="p">
          <span class="pill">worker ${p.live}/${p.workers}</span>
          <span class="pill blue">事实 ${p.facts}</span>
          <span class="pill">${esc(p.model)}</span>
        </div>
      </div>`).join("");
  } catch (e) { toast(e.message, true); }
}

async function npCreate() {
  const name = $("np-name").value.trim();
  const problem = $("np-problem").value.trim();
  const roles = $("np-roles").value;
  if (!name) return toast("请填项目名", true);
  if (!problem) return toast("请填问题描述", true);
  try {
    const r = await api("/api/projects", "POST", { name, problem, roles });
    toast("项目已创建: " + r.name);
    $("np-name").value = ""; $("np-problem").value = "";
    await loadProjects();
    selectProject(r.name);
  } catch (e) { toast(e.message, true); }
}

async function selectProject(name) {
  S.current = name;
  S.feedSeen = new Set();
  clearInterval(S.timer);
  clearInterval(S.activityTimer);
  await loadProjectDetail();
  S.timer = setInterval(loadProjectDetail, 4000);
  S.activityTimer = setInterval(refreshActivity, 2500);
  fillFactsSelect();
}

async function loadProjectDetail() {
  if (!S.current) return;
  try {
    const p = await api("/api/projects/" + encodeURIComponent(S.current));
    renderDetail(p);
    refreshFeed(p);
  } catch (e) { toast(e.message, true); }
}

function renderDetail(p) {
  const d = $("project-detail");
  // 保留用户正在输入的任务草稿（重新渲染时不被清空）
  const drafts = {};
  document.querySelectorAll('[id^="task-"]').forEach((el) => { drafts[el.id.slice(5)] = el.value; });
  const workers = p.workers.map((w) => {
    const cls = workerCls(w.label);
    const err = w.error ? `<div class="row"><span>错误</span><b style="color:var(--red)">${esc(w.error)}</b></div>` : "";
    return `
    <div class="worker ${cls}">
      <div class="whead">
        <span class="pulse"><span class="ring"></span><span class="ring2"></span></span>
        <span class="wname">${esc(w.worker)}</span>${labelPill(w.label)}
      </div>
      <div class="row"><span>状态</span><b>${esc(w.state)}</b></div>
      <div class="row"><span>轮次</span><b>${w.round}</b></div>
      <div class="row"><span>本轮回话</span><b class="age-tick" data-secs="${w.age_s}">${fmtAge(w.age_s)}</b></div>
      <div class="row"><span>最近事实</span><b style="font-family:var(--mono);font-size:11px">${esc(w.last_fact_id || "—")}</b></div>
      <div class="row act"><span>正在做什么</span><b class="act-line" data-activity="${esc(w.worker)}" title="">…</b></div>
      ${err}
      <textarea id="task-${esc(w.worker)}" placeholder="本轮任务（保存后 worker 下一轮读取）">${esc(drafts[w.worker] || "")}</textarea>
      <div class="btns">
        <button class="btn small" onclick="saveTask('${esc(w.worker)}')">保存任务</button>
        <button class="btn small primary" onclick="workerAction('${esc(w.worker)}','start')">启动</button>
        <button class="btn small" onclick="workerAction('${esc(w.worker)}','stop')">停止</button>
        <button class="btn small danger" onclick="workerAction('${esc(w.worker)}','force')">强停</button>
        <button class="btn small" onclick="showLog('${esc(w.worker)}')">日志</button>
      </div>
    </div>`;
  }).join("");

  d.innerHTML = `
    <div class="panel">
      <div style="display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:8px">
        <h2 style="margin:0">${esc(p.name)}</h2>
        <span class="pill blue">${p.facts_count} 个事实</span>
      </div>
      <label>问题描述（可编辑）</label>
      <textarea id="pd-problem" rows="6">${esc(p.problem)}</textarea>
      <button class="btn small" onclick="saveProblem()">保存问题</button>
    </div>

    <div class="panel">
      <h3>事实图成长</h3>
      <div class="fg-wrap">
        <div>
          <div class="fg-num" id="fg-num">${p.facts_count}</div>
          <div class="fg-label">已验证事实</div>
        </div>
        <svg id="fg-visual" width="170" height="150" viewBox="0 0 170 150"></svg>
      </div>
    </div>

    <div class="panel">
      <h3>策略循环（DeepSeek 主代理）</h3>
      <div class="btn-row">
        <button class="btn primary" onclick="consult()">① 生成策略指引（咨询 DeepSeek）</button>
        <button class="btn" onclick="assignFromGuidance()">② 按条目分配到 Worker</button>
        <button class="btn" onclick="loadGuidance()">查看当前指引</button>
      </div>
      <textarea id="guidance-box" rows="9" placeholder="策略指引会显示在这里…（通常需要 1-3 分钟）" readonly style="margin-top:10px"></textarea>
    </div>    <div class="panel">
      <h3>Worker 群（${p.workers.length} 个）</h3>
      <div class="btn-row">
        <button class="btn primary" onclick="allWorkers('start')">全部启动</button>
        <button class="btn" onclick="allWorkers('stop')">全部停止</button>
        <button class="btn danger" onclick="allWorkers('force')">全部强停</button>
        <span class="dim" style="align-self:center">默认无期限；</span>
        <input id="dl-hours" type="number" style="width:86px" placeholder="小时">
        <button class="btn small" onclick="setDeadline()">设截止</button>
        <button class="btn small" onclick="setDeadline(0)">取消截止</button>
      </div>
      <div class="worker-grid">${workers}</div>
    </div>

    <div class="panel">
      <h3>最近活动</h3>
      <div id="act-feed" class="feed"><div class="dim" style="padding:8px 4px">等待 worker 提交验证…</div></div>
    </div>

    <div class="panel">
      <h3>结题与报告</h3>
      ${p.target && p.target.fact_id
        ? `<div class="row" style="display:flex;justify-content:space-between;font-size:13px"><span class="dim">答案事实</span><b style="font-family:var(--mono)">${p.target.fact_id}</b></div>
           <div class="btn-row"><button class="btn primary" onclick="exportTargetReport()">导出 MD 报告</button></div>`
        : `<div class="dim">尚未结题：到「事实图」打开目标事实，点「结题（设为答案）」。</div>`}
    </div>

`;

  renderFactDots(p);
}

function renderFactDots(p) {
  const svg = $("fg-visual");
  if (!svg) return;
  const n = Math.min(p.facts_count, 96);
  const prev = S.factDots[S.current] || 0;
  S.factDots[S.current] = p.facts_count;
  svg.innerHTML = "";
  const cols = 12;
  for (let i = 0; i < n; i++) {
    const c = document.createElementNS("http://www.w3.org/2000/svg", "circle");
    c.setAttribute("cx", 8 + (i % cols) * 13.5);
    c.setAttribute("cy", 8 + Math.floor(i / cols) * 13.5);
    c.setAttribute("r", "2.8");
    c.classList.add("fdot");
    if (i >= prev) { c.classList.add("new"); c.classList.add("pop"); }
    else if (p.facts_count > 0) c.classList.add("live");
    svg.appendChild(c);
  }
}

async function refreshFeed(p) {
  const feed = $("act-feed");
  if (!feed) return;
  // 新事实入库的提示
  const before = S.lastFacts[S.current] || 0;
  S.lastFacts[S.current] = p.facts_count;
  if (p.facts_count > before && before > 0) {
    addFeed(feed, "ok", "", `事实图新增 ${p.facts_count - before} 条已验证事实`);
  }
  // 验证记录流
  try {
    const r = await api(`/api/projects/${encodeURIComponent(S.current)}/memory?kind=verification&limit=20`);
    const entries = (r.verification || []).slice().reverse();
    entries.forEach((e) => {
      const key = e.id || (e.timestamp_utc + e.claim);
      if (S.feedSeen.has(key)) return;
      S.feedSeen.add(key);
      const ok = !!e.fact_id;
      const verdict = ok ? "✓ " + e.fact_id : (e.verdict ? e.verdict : (e.status || "已记录"));
      addFeed(feed, ok ? "ok" : "warn", e.timestamp_utc || "",
        (e.claim || "").slice(0, 110), verdict, !ok);
    });
  } catch (e) { /* feed 失败不打断页面 */ }
}

function addFeed(feed, cls, time, text, verdict, no) {
  if (feed.querySelector(".dim")) feed.innerHTML = "";
  const item = document.createElement("div");
  item.className = "feed-item";
  item.innerHTML =
    `<span class="feed-dot ${cls}"></span>` +
    `<span class="feed-t">${esc((time || "刚刚").replace("T", " ").slice(5, 19))}</span>` +
    `<span class="feed-s">${esc(text)}</span>` +
    (verdict ? `<span class="feed-v ${no ? "no" : ""}">${esc(verdict)}</span>` : "");
  feed.prepend(item);
  requestAnimationFrame(() => item.classList.add("in"));
  while (feed.children.length > 40) feed.removeChild(feed.lastChild);
}

async function saveProblem() {
  try {
    await api("/api/projects/" + encodeURIComponent(S.current) + "/problem", "PUT",
      { problem: $("pd-problem").value });
    toast("问题已保存");
  } catch (e) { toast(e.message, true); }
}

async function saveTask(worker) {
  try {
    await api(`/api/projects/${encodeURIComponent(S.current)}/workers/${encodeURIComponent(worker)}/task`,
      "PUT", { task: $("task-" + worker).value });
    toast(worker + " 任务已保存");
  } catch (e) { toast(e.message, true); }
}

async function workerAction(worker, act) {
  try {
    if (act === "start") {
      await api(`/api/projects/${encodeURIComponent(S.current)}/workers/start`, "POST");
    } else {
      await api(`/api/projects/${encodeURIComponent(S.current)}/workers/stop`, "POST",
        { force: act === "force" });
    }
    toast(worker + " → " + (act === "force" ? "强停" : act));
    loadProjectDetail();
  } catch (e) { toast(e.message, true); }
}

async function allWorkers(act) {
  try {
    const r = act === "start"
      ? await api(`/api/projects/${encodeURIComponent(S.current)}/workers/start`, "POST")
      : await api(`/api/projects/${encodeURIComponent(S.current)}/workers/stop`, "POST",
          { force: act === "force" });
    toast(JSON.stringify(r.results));
    loadProjectDetail();
  } catch (e) { toast(e.message, true); }
}

async function setDeadline(v) {
  const hours = v === undefined ? parseFloat($("dl-hours").value) : v;
  try {
    await api(`/api/projects/${encodeURIComponent(S.current)}/deadline`, "POST", { hours: hours || 0 });
    toast(hours > 0 ? "已设置截止时间" : "已取消截止时间");
  } catch (e) { toast(e.message, true); }
}

async function consult() {
  const box = $("guidance-box");
  box.value = "正在咨询 DeepSeek…（可能需 1-3 分钟）";
  try {
    const r = await api(`/api/projects/${encodeURIComponent(S.current)}/strategy/consult`, "POST");
    box.value = r.reply;
    toast("策略指引已生成并记录为 master_guidance");
    loadProjectDetail();
  } catch (e) { box.value = "咨询失败：" + e.message; toast(e.message, true); }
}

async function assignFromGuidance() {
  try {
    const r = await api(`/api/projects/${encodeURIComponent(S.current)}/strategy/assign`, "POST",
      { split: true });
    toast("已分配到 " + Object.keys(r.results).length + " 个 worker");
    loadProjectDetail();
  } catch (e) { toast(e.message, true); }
}

async function loadGuidance() {
  try {
    const r = await api(`/api/projects/${encodeURIComponent(S.current)}/strategy/guidance`);
    const entries = (r.entries || []).filter((e) => {
      const txt = (e.evidence || e.claim || "").trim();
      return txt && txt !== "(empty reply)";
    });
    $("guidance-box").value = entries.length
      ? entries.map((e, i) => "=== " + (e.timestamp_utc || "") + " (" + (e.author || "") + ") ===\n" + (e.evidence || e.claim || "")).join("\n\n")
      : "(还没有 master_guidance，先点「生成策略指引」)";
  } catch (e) { toast(e.message, true); }
}

function showLog(worker) {
  const mask = document.createElement("div");
  mask.className = "modal-mask";
  mask.innerHTML = `<div class="modal">
    <div style="display:flex;justify-content:space-between;align-items:center">
      <h3 style="margin:0">${esc(worker)} 日志</h3>
      <button class="btn small" onclick="document.body.removeChild(this.closest('.modal-mask'))">关闭</button>
    </div>
    <div id="log-body"><pre>加载中…</pre></div>
  </div>`;
  document.body.appendChild(mask);
  api(`/api/projects/${encodeURIComponent(S.current)}/workers/${encodeURIComponent(worker)}/log`)
    .then((r) => {
      const parts = [];
      if (r.loop) parts.push("── loop.log ──\n" + r.loop);
      if (r.round) parts.push("── " + (r.round_name || "round") + " ──\n" + r.round);
      mask.querySelector("#log-body").innerHTML =
        "<pre>" + esc(parts.join("\n\n") || "(无日志)") + "</pre>";
    })
    .catch((e) => { mask.querySelector("#log-body").innerHTML = "<pre>" + esc(e.message) + "</pre>"; });
}

// ------------------------------------------------------------------ facts --
async function fillFactsSelect() {
  try {
    if (!S.projects.length) S.projects = await api("/api/projects");
    const sel = $("facts-project");
    const prev = sel.value;
    sel.innerHTML = S.projects.map((p) => `<option value="${esc(p.name)}">${esc(p.name)}</option>`).join("");
    if (prev && S.projects.some((p) => p.name === prev)) sel.value = prev;
  } catch (e) { /* ignore */ }
}

async function loadFacts() {
  const project = $("facts-project").value;
  const q = $("facts-q").value.trim();
  if (!project) return;
  try {
    const list = await api(`/api/projects/${encodeURIComponent(project)}/facts?q=${encodeURIComponent(q)}&limit=300`);
    $("facts-badge").textContent = "· " + list.length + " 条";
    const box = $("facts-list");
    if (!list.length) { box.innerHTML = '<div class="empty">没有事实（worker 还没产出，或换个关键词）</div>'; return; }
    box.innerHTML = list.map((f) => `
      <div class="list-item" onclick="showFact('${f.fact_id}')">
        <div class="t">${f.fact_id}</div>
        <div class="s">${esc(f.statement || "")}</div>
      </div>`).join("");
  } catch (e) { toast(e.message, true); }
}

async function showFact(fid) {
  const project = $("facts-project").value;
  try {
    const f = await api(`/api/projects/${encodeURIComponent(project)}/facts/${fid}`);
    $("fact-detail").innerHTML = `
      <div class="fact-view">
        <div style="display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:8px">
          <h2 style="margin:0;font-size:18px">事实 ${f.fact_id}</h2>
          <div class="btn-row" style="margin:0">
            <button class="btn primary small" onclick="finalizeFact('${f.fact_id}')">结题（设为答案）</button>
            <button class="btn small" onclick="exportReport('${f.fact_id}')">导出 MD 报告</button>
            <button class="btn danger small" onclick="revokeFact('${f.fact_id}')">撤销（级联）</button>
          </div>
        </div>
        <h3>依赖的前驱</h3><pre>${esc((f.predecessors || []).join(", ") || "（无，基础事实）")}</pre>
        <h3>依赖它的后继</h3><pre>${esc((f.descendants || []).join(", ") || "（无）")}</pre>
        <h3>statement</h3><pre>${esc(f.statement)}</pre>
        <h3>proof</h3><pre>${esc(f.proof)}</pre>
        <h3>intuition</h3><pre>${esc(f.intuition || "（无）")}</pre>
      </div>`;
  } catch (e) { toast(e.message, true); }
}

async function finalizeFact(fid) {
  try {
    const r = await api(`/api/projects/${encodeURIComponent($("facts-project").value)}/finalize`,
      "POST", { fact_id: fid });
    toast("已结题：" + r.fact_id);
    showFact(fid);
  } catch (e) { toast(e.message, true); }
}

async function exportReport(fid) {
  const project = $("facts-project").value;
  try {
    const r = await api(`/api/projects/${encodeURIComponent(project)}/report`,
      "POST", { fact_id: fid });
    toast("报告已生成（" + r.facts + " 条事实）");
    downloadReport(project);
  } catch (e) { toast(e.message, true); }
}

async function exportTargetReport() {
  const project = S.current;
  try {
    const r = await api(`/api/projects/${encodeURIComponent(project)}/report`, "POST", {});
    toast("报告已生成（" + r.facts + " 条事实）");
    downloadReport(project);
  } catch (e) { toast(e.message, true); }
}

function downloadReport(project) {
  const a = document.createElement("a");
  a.href = `/api/projects/${encodeURIComponent(project)}/report/download`;
  document.body.appendChild(a); a.click(); a.remove();
}

async function revokeFact(fid) {
  const reason = prompt("撤销原因（会级联撤销依赖它的事实）:");
  if (!reason) return;
  try {
    const r = await api(`/api/projects/${encodeURIComponent($("facts-project").value)}/facts/${fid}/revoke`,
      "POST", { reason });
    toast("已撤销 " + r.revoked.length + " 个事实（含级联）");
    loadFacts();
  } catch (e) { toast(e.message, true); }
}

// ---------------------------------------------------------------- settings --
function renderProviderHint() {
  const prov = $("st-provider").value;
  $("st-provider-hint").textContent = prov === "opencode"
    ? "OpenCode Go 套餐：在 opencode.ai 的 Zen 控制台订阅 Go 并复制 API Key。DeepSeek V4 Flash / Pro 均可用于 worker、验证器和策略咨询（走 Chat 接口，配套的 codex CLI 已固定为 0.93.0）。"
    : "直连 DeepSeek：worker/验证器走 Responses 接口（v4-flash），策略咨询走 Chat 接口。";
}

function onProviderChange() {
  $("st-base").value = $("st-provider").value === "opencode"
    ? "https://opencode.ai/zen/go/v1"
    : "https://api.deepseek.com";
  renderProviderHint();
}

async function stLoad() {
  try {
    const s = await api("/api/settings");
    $("st-provider").value = s.provider || "deepseek";
    $("st-key").value = s.api_key || "";
    $("st-base").value = s.base_url || "";
    $("st-worker-model").value = s.worker_model || "deepseek-v4-flash";
    $("st-verify-model").value = s.verify_model || "deepseek-v4-flash";
    $("st-consult-model").value = s.consult_model || "deepseek-v4-pro";
    $("st-effort").value = s.worker_effort || "xhigh";
    $("st-port").value = s.verify_port || "8091";
    $("st-codex").value = s.codex_js || "";
    $("st-node").value = s.node_bin || "";
    renderProviderHint();
  } catch (e) { toast(e.message, true); }
}

async function stSave() {
  const body = {
    provider: $("st-provider").value,
    api_key: $("st-key").value.trim(),
    base_url: $("st-base").value.trim(),
    worker_model: $("st-worker-model").value.trim(),
    worker_effort: $("st-effort").value,
    verify_model: $("st-verify-model").value.trim(),
    verify_effort: $("st-effort").value,
    consult_model: $("st-consult-model").value.trim(),
    verify_port: $("st-port").value.trim(),
    codex_js: $("st-codex").value.trim(),
    node_bin: $("st-node").value.trim(),
  };
  try {
    await api("/api/settings", "PUT", body);
    toast("设置已保存");
    loadOverview();
  } catch (e) { toast(e.message, true); }
}

async function stDetect() {
  try {
    const d = await api("/api/setup/detect", "POST");
    $("st-codex").value = d.codex_js || "";
    $("st-node").value = d.node_bin || "";
    $("st-result").textContent = "检测到:\n  node: " + (d.node_bin || "未找到") +
      "\n  codex.js: " + (d.codex_js || "未找到（可在总览页点「安装 Codex CLI」）");
    toast("检测完成");
  } catch (e) { toast(e.message, true); }
}

async function refreshActivity() {
  if (!S.current) return;
  try {
    const r = await api(`/api/projects/${encodeURIComponent(S.current)}/activity`);
    document.querySelectorAll(".act-line").forEach((el) => {
      const a = r[el.dataset.activity];
      if (!a) return;
      const latest = (a.actions && a.actions[0])
        ? a.actions[0]
        : (a.alive ? "正在思考/搜索…" : "已停止");
      el.textContent = latest;
      el.title = (a.actions || []).join("\n");
    });
  } catch (e) { /* 活动刷新失败不打断页面 */ }
}

// ------------------------------------------------------------------ boot --
loadOverview();
setInterval(loadOverview, 8000);
setInterval(() => {
  document.querySelectorAll(".age-tick").forEach((el) => {
    const s = parseFloat(el.dataset.secs || "0");
    if (!isNaN(s)) el.dataset.secs = String(s + 1);
    el.textContent = fmtAge(parseFloat(el.dataset.secs || "0"));
  });
}, 1000);