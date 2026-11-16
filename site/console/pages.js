/* 大衍 DAYAN 页面切换 + AI 助手抽屉 */
"use strict";

/* ---- 页面切换 ---- */
const pageIds = ["pageOverview", "pageData", "pageScenarios", "pageModels", "pageReplay"];

function switchPage(name) {
  pageIds.forEach(id => {
    const el = document.getElementById(id);
    if (el) el.style.display = id === "page" + name.charAt(0).toUpperCase() + name.slice(1) ? "" : "none";
  });
  // scenario-strip 只在 overview 显示
  const strip = document.querySelector(".scenario-strip");
  if (strip) strip.style.display = name === "overview" ? "" : "none";
  const kpi = document.querySelector(".kpi-row");
  if (kpi) kpi.style.display = name === "overview" ? "" : "none";
  // 切页即加载内容（任何路径都能触发）
  if (typeof loadPageContent === "function") loadPageContent(name);
}

/* ---- AI 助手抽屉 ---- */
let aiChatHistory = [];

function toggleAIDrawer() {
  const d = document.getElementById("aiDrawer");
  if (d) d.classList.toggle("open");
}

function createAIDrawer() {
  const drawer = document.createElement("div");
  drawer.id = "aiDrawer";
  drawer.innerHTML = `
  <div class="ai-head">
    <b>◈ 大衍 AI 助手</b>
    <span>自然语言构建仿真</span>
    <button class="ai-close" onclick="toggleAIDrawer()">×</button>
  </div>
  <div class="ai-chat" id="aiChatBody">
    <div class="ai-msg ai-bot">你好！我是大衍 AI 助手。告诉我你想做什么仿真，我帮你选模型、设参数、跑结果。<br><br>
    试试：<br>• "运行 NET106"（交通 CA）<br>• "扫参 NET106 density 0.1 0.3 0.5"<br>• "比较 ECO110 和 ECO111"<br>• "找 gini 相关的模型"</div>
  </div>
  <div class="ai-quick">
    <button onclick="aiQuick('运行 NET106')">🚗 交通CA</button>
    <button onclick="aiQuick('运行 NET052')">🦠 SIS疫情</button>
    <button onclick="aiQuick('扫参 ECO016 k0 0.5 1.0 2.0')">📈 Ramsey扫参</button>
    <button onclick="aiQuick('找 opinion 相关模型')">💡 搜模型</button>
  </div>
  <div class="ai-input-row">
    <textarea id="aiInput" rows="3" aria-label="给大衍AI发送消息" placeholder="描述你的仿真需求…"></textarea>
    <button id="aiSend" onclick="aiSend()">→</button>
  </div>`;
  document.body.appendChild(drawer);
  document.getElementById("aiInput").addEventListener("keydown", e => {
    if (e.key === "Enter" && !e.shiftKey && !e.isComposing) {e.preventDefault();aiSend();}
  });
  // C5: planner 状态披露徽标（LLM 在线 / 规则兜底）
  fetch("/api/agent/planner_status").then(r => r.json()).then(d => {
    const head = drawer.querySelector(".ai-head b");
    if (!head) return;
    const badge = document.createElement("span");
    const isLlm = d.planner && !["rule", "unreachable"].includes(d.planner) && !String(d.planner).startsWith("error");
    badge.textContent = isLlm ? "LLM 规划已配置" : "规则模式";
    badge.style.cssText = "margin-left:8px;font-size:8px;padding:2px 6px;border-radius:3px;" +
      (isLlm ? "color:#00ffa3;border:1px solid rgba(0,255,163,.4);background:rgba(0,255,163,.08)"
             : "color:#8fa2c2;border:1px solid rgba(143,162,194,.3);background:rgba(143,162,194,.08)");
    head.appendChild(badge);
  }).catch(() => {});
}

function aiQuick(text) {
  document.getElementById("aiInput").value = text;
  aiSend();
}

/* 供恢复快照使用：从快照 obs 直接重建侧栏 */
function updateObsPanelFromData(d) {
  const modelEl = document.getElementById("obsModel");
  if (modelEl) modelEl.textContent = "快照恢复 · " + (d.names || []).join("/") ;
  const legend = document.getElementById("obsLegend");
  if (legend) legend.innerHTML = (d.names || []).slice(0, 6).map((nm, i) =>
    `<span><i style="background:${OBS_COLORS[i % 6]}"></i>${nm}</span>`).join("");
  window._obsData = d;
}

/* 记录最近一次模型运行（供干预对照/回放/追踪使用） */
function rememberRun(mid, obs, params, ticks, intent, planner, tools, text) {
  window._lastRun = { model_id: mid, observations: obs, params: params || {},
                      ticks: ticks || (obs ? obs.length - 1 : 120) };
  window._branchSeries = null; window._branchNote = null; state_branch_clear();
  // 新模型运行后，旧干预对照已失效 → 如实重置分支披露
  const tag = document.getElementById("branchTag");
  if (tag) tag.textContent = "基准 A · " + mid;
  const pn = document.getElementById("policyNote");
  if (pn) pn.textContent = "新模型基线 · 调整滑杆后可创建干预对照";
  window.DAYAN_AGENT_TRACE = { model: mid, text: text || "", intent: intent || "",
    planner: planner || "rule",
    tools: tools || ("run " + mid + "（" + (obs ? obs.length : 0) + " obs）"),
    result: obs && obs.length ? "运行成功，终值 " + Object.entries(obs[obs.length - 1])
      .filter(([k, v]) => typeof v === "number").slice(0, 3)
      .map(([k, v]) => k + "=" + (+v).toFixed(3)).join(" ") : "无观测" };
}
function state_branch_clear(){ if(window.appStateResetBranch){ window.appStateResetBranch(); } else { window._branchSeries = null; } }

/* 干预对照（模型模式，WP8 时点干预）：在 30% 进度处对首个数值参数 ×1.2，
   与基准共用同种子（配对随机流）——干预前轨迹一致、干预后按机制分化。 */
window.DAYAN_APPLY_INTERVENTION = async function () {
  const lr = window._lastRun;
  const btn = document.getElementById("applyPolicy");
  if (!lr || !btn) { if (window.DAYAN_EVENT) DAYAN_EVENT("warn", "干预对照不可用", "请先运行一个模型仿真"); return; }
  btn.innerHTML = "<span>⏳</span>对照运行中…";
  try {
    const params = { ...(lr.params || {}) };
    const keys = Object.keys(params).filter(k => typeof params[k] === "number" && isFinite(params[k]));
    let note;
    const atT = Math.max(0.1, (lr.ticks || 100) * 0.3 * 0.1);   // 30% 进度处（tick→sim_t）
    let interventions;
    if (keys.length) {
      const k0 = keys[0];
      interventions = [{ at_t: +atT.toFixed(4), label: `对照：${k0}×1.2`,
                         params: { [k0]: "*1.2" } }];
      note = `时点干预 t=${atT.toFixed(2)}：${k0} ${lr.params[k0]}→×1.2（同种子配对）`;
    } else {
      note = "对照运行：同配置复跑（模型无显式数值参数）";
      interventions = [];
    }
    const r = await fetch("/api/run", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ model_id: lr.model_id, ticks: lr.ticks,
                             parameters: params, seed: 0,
                             interventions })
    });
    const d = await r.json();
    if (!d.ok) throw new Error(d.detail || "运行失败");
    const ivRec = (d.manifest && d.manifest.interventions || [])[0] || {};
    if (interventions.length && !ivRec.applied) {
      throw new Error("干预未生效：" + (ivRec.error || "参数不可改写").slice(0, 40));
    }
    window._branchSeries = (d.observations || []).map(o => {
      for (const [k, v] of Object.entries(o)) {
        if (k !== "sim_t" && typeof v === "number" && isFinite(v)) return v;
      }
      return 0;
    });
    window._branchNote = note + " · " + lr.model_id;
    if (window.DAYAN_EVENT) DAYAN_EVENT("policy-event", "时点干预对照完成", note);
    if (typeof drawDashComparison === "function") drawDashComparison();
    const tag = document.getElementById("branchTag");
    if (tag) tag.textContent = "干预对照 · 已生成";
    const pn = document.getElementById("policyNote");
    if (pn) pn.textContent = note;
    const toast = document.getElementById("toast");
    if (toast) { toast.textContent = "对照分支已生成：" + note; toast.classList.add("show");
      setTimeout(() => toast.classList.remove("show"), 3200); }
  } catch (e) {
    if (window.DAYAN_EVENT) DAYAN_EVENT("warn", "干预对照失败", String(e.message || e).slice(0, 60));
  } finally {
    btn.innerHTML = "<span>↻</span>更新干预分支<span>→</span>";
  }
};

/* ===== 数据观测侧栏（独立一栏，与 3D 动画同步的实时曲线） ===== */
const OBS_COLORS = ["#00e5ff", "#c084fc", "#ffb74d", "#ff4d6d", "#00ffa3", "#68bbef"];

function updateObsPanel(mid, obs, note) {
  const skip = /_min$|_max$|_std$|_mean$|^sim_t$/;
  const last = (obs && obs.length) ? obs[obs.length - 1] : {};
  const keys = Object.keys(last).filter(k => !skip.test(k) &&
    typeof last[k] === "number" && isFinite(last[k]));
  const names = [], series = [];
  keys.forEach(k => {
    const vals = obs.map(o => o[k]).filter(v => typeof v === "number" && isFinite(v));
    if (vals.length > 1 && Math.max(...vals) - Math.min(...vals) > 1e-12) {
      names.push(k); series.push(vals);
    }
  });
  const modelEl = document.getElementById("obsModel");
  if (modelEl) modelEl.textContent = mid + (note ? " · " + String(note).slice(0, 26) : "");
  const legend = document.getElementById("obsLegend");
  if (legend) legend.innerHTML = names.slice(0, 6).map((nm, i) =>
    `<span><i style="background:${OBS_COLORS[i % 6]}"></i>${nm}</span>`).join("");
  window._obsData = names.length
    ? { names, series, n: series[0].length, DUR: 22 } : null;
  drawObsChart();
}

function drawObsChart() {
  if(window.DAYAN_RESULTS?.active)return;
  const cv = document.getElementById("obsChart");
  if (!cv) return;
  const dpr = Math.min(window.devicePixelRatio || 1, 2);
  const W = cv.clientWidth, H = cv.clientHeight;
  if (!W || !H) return;
  if (cv.width !== Math.round(W * dpr)) { cv.width = Math.round(W * dpr); cv.height = Math.round(H * dpr); }
  const ctx = cv.getContext("2d");
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  ctx.clearRect(0, 0, W, H);
  const padL = 8, padR = 8, padT = 11, padB = 16;
  const pw = W - padL - padR, ph = H - padT - padB;
  ctx.strokeStyle = "#1a3040"; ctx.lineWidth = 1;
  for (let i = 0; i <= 3; i++) {
    const gy = padT + ph * i / 3;
    ctx.beginPath(); ctx.moveTo(padL, gy); ctx.lineTo(W - padR, gy); ctx.stroke();
  }
  const d = window._obsData;
  if (!d) {
    ctx.fillStyle = "#4a6a7a"; ctx.font = "10px monospace"; ctx.textAlign = "center";
    ctx.fillText("运行仿真后此处显示实时曲线", W / 2, H / 2);
    const tickEl0 = document.getElementById("obsTick");
    if (tickEl0) tickEl0.textContent = "";
    return;
  }
  const { names, series, n, DUR } = d;
  const all = series.flatMap(s => s);
  const lo = Math.min(...all), hi = Math.max(...all);
  const y = v => padT + ph - (v - lo) / Math.max(hi - lo, 1e-12) * ph;
  const x = i => padL + i / (n - 1) * pw;
  // 播放头：与 3D 共用 clock（window._vizNow）
  const t = window._vizNow || 0;
  const idx = Math.min(n - 1, Math.floor((t % DUR) / DUR * n));
  series.slice(0, 6).forEach((vals, si) => {
    const c = OBS_COLORS[si % 6];
    ctx.strokeStyle = c; ctx.lineWidth = 1.4;
    ctx.beginPath();
    vals.forEach((v, i) => i ? ctx.lineTo(x(i), y(v)) : ctx.moveTo(x(i), y(v)));
    ctx.stroke();
    ctx.beginPath(); ctx.arc(x(idx), y(vals[idx]), 2.6, 0, 7);
    ctx.fillStyle = "#fff"; ctx.fill();
    ctx.beginPath(); ctx.arc(x(idx), y(vals[idx]), 1.4, 0, 7);
    ctx.fillStyle = c; ctx.fill();
  });
  ctx.strokeStyle = "rgba(255,255,255,0.45)"; ctx.setLineDash([3, 3]); ctx.lineWidth = 1;
  ctx.beginPath(); ctx.moveTo(x(idx), padT); ctx.lineTo(x(idx), padT + ph); ctx.stroke();
  ctx.setLineDash([]);
  ctx.fillStyle = "#5a7a8b"; ctx.font = "8px monospace"; ctx.textAlign = "left";
  ctx.fillText(hi.toPrecision(3), padL + 2, padT - 2);
  ctx.fillText(lo.toPrecision(3), padL + 2, padT + ph + 10);
  const tickEl = document.getElementById("obsTick");
  if (tickEl) tickEl.textContent =
    `tick ${idx + 1}/${n} · 当前 ${names[0]}=${series[0][idx].toPrecision(3)}`;
}
setInterval(drawObsChart, 250);   // 含后台标签页兜底

/* ===== Word 实验报告 ===== */
function aiReportButton(data) {
  const chat = document.getElementById("aiChatBody");
  const div = document.createElement("div");
  div.className = "ai-msg ai-bot";
  const btn = document.createElement("button");
  btn.textContent = "📄 一键生成 Word 实验报告";
  btn.style.cssText = "padding:6px 14px;background:rgba(255,183,77,.14);border:1px solid rgba(255,183,77,.5);border-radius:5px;color:#ffb74d;cursor:pointer;font-size:11px;font-weight:700";
  btn.onclick = () => generateReport(data, btn);
  div.appendChild(btn);
  chat.appendChild(div);
  chat.scrollTop = chat.scrollHeight;
}

async function generateReport(data, btn) {
  btn.disabled = true;
  btn.textContent = "⏳ AI 撰写报告中（约 30-120 秒）…";
  const chat = document.getElementById("aiChatBody");
  const pushMsg = (text, color) => {
    const m = document.createElement("div");
    m.className = "ai-msg ai-bot";
    m.style.color = color || "#d0e9ec";
    m.textContent = text;
    chat.appendChild(m);
    chat.scrollTop = chat.scrollHeight;
  };
  try {
    const r = await fetch("/api/report", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(data)
    });
    const d = await r.json();
    if (d.ok) {
      const m = document.createElement("div");
      m.className = "ai-msg ai-bot";
      const a = document.createElement("a");
      a.href = d.url;
      a.textContent = "✓ " + d.title + " — 点击下载 .docx";
      a.style.cssText = "color:#00ffa3;font-weight:700";
      m.appendChild(a);
      chat.appendChild(m);
      chat.scrollTop = chat.scrollHeight;
      setTimeout(() => {
        const x = document.createElement("a");
        x.href = d.url; x.download = "";
        document.body.appendChild(x); x.click(); x.remove();
      }, 400);
      if (window.DAYAN_EVENT) DAYAN_EVENT("", "实验报告已生成", d.title);
      btn.textContent = "📄 已生成 ✓";
    } else {
      pushMsg("✗ 报告生成失败：" + (d.detail || d.error || "未知错误"), "#ff4d6d");
      btn.disabled = false;
      btn.textContent = "📄 重试生成报告";
    }
  } catch (e) {
    pushMsg("✗ 报告请求失败：" + e.message, "#ff4d6d");
    btn.disabled = false;
    btn.textContent = "📄 重试生成报告";
  }
}

/* 把观测序列转成驾驶舱 KPI + 对照图序列 */
function dashFromObs(mid, obs, note) {  if (!window.DAYAN_DASH || !obs || obs.length < 2) return;
  const skip = /_min$|_max$|_std$|_mean$|^sim_t$/;
  const last = obs[obs.length - 1];
  const keys = Object.keys(last).filter(k => !skip.test(k) &&
    typeof last[k] === "number" && isFinite(last[k]));
  const kpis = keys.slice(0, 6).map(k => ({
    label: k,
    value: Math.abs(last[k]) >= 1000 ? Math.round(last[k]).toLocaleString()
                                      : Number(last[k].toFixed(4)),
    unit: "", foot: mid + " · 终值"
  }));
  const series = keys.slice(0, 3).map(k => ({
    name: k, vals: obs.map(o => o[k]).filter(v => typeof v === "number" && isFinite(v))
  })).filter(s => s.vals.length > 1);
  window.DAYAN_DASH({ title: mid + " · " + (note || "模型仿真"),
                      kpis, series, modelId: mid, note });
}

/* 对话记忆：近期用户消息 + 上次运行（发给 LLM 做指代消解） */
window._aiMsgs = [];

async function aiSend() {
  if(window.DAYAN_RESULTS?.send)return DAYAN_RESULTS.send();
  window.DAYAN_NOTICE?.('研究工作台尚未就绪，请稍后发送。');
}

/* ---- 初始化 ---- */
// 页面脚本在 app.js 之后加载，DOMContentLoaded 已触发 → 直接执行
  createAIDrawer();

  // 劫持 nav 按钮：切换页面而非打开 modal
  document.querySelectorAll("[data-nav]").forEach(btn => {
    // 移除 app.js 里绑定的 modal handler
    const newBtn = btn.cloneNode(true);
    btn.parentNode.replaceChild(newBtn, btn);
    newBtn.addEventListener("click", () => {
      document.querySelectorAll("[data-nav]").forEach(x =>
        x.classList.toggle("active", x === newBtn)
      );
      switchPage(newBtn.dataset.nav);
      loadPageContent(newBtn.dataset.nav);
    });
  });

  // configButton 也切页
  const cfg = document.getElementById("configButton");
  if (cfg) {
    const newCfg = cfg.cloneNode(true);
    cfg.parentNode.replaceChild(newCfg, cfg);
    newCfg.addEventListener("click", () => {
      document.querySelectorAll("[data-nav]").forEach(x =>
        x.classList.toggle("active", x.dataset.nav === "scenarios")
      );
      switchPage("scenarios");
      loadPageContent("scenarios");
    });
  }

  // modelButton 也切页
  const mb = document.getElementById("modelButton");
  if (mb) {
    const newMb = mb.cloneNode(true);
    mb.parentNode.replaceChild(newMb, mb);
    newMb.addEventListener("click", () => {
      document.querySelectorAll("[data-nav]").forEach(x =>
        x.classList.toggle("active", x.dataset.nav === "models")
      );
      switchPage("models");
      loadPageContent("models");
    });
  }

  // AI 悬浮按钮
  const fab = document.createElement("button");
  fab.className = "ai-fab";
  fab.innerHTML = "◈";
  fab.title = "AI 助手";
  fab.onclick = toggleAIDrawer;
  document.body.appendChild(fab);

/* ---- 页面内容加载 ---- */
async function loadPageContent(page) {
  if (page === "models") {
    await loadModelsPage();
  } else if (page === "scenarios") {
    loadScenariosPage();
  } else if (page === "replay") {
    loadReplayPage();
  } else if (page === "data") {
    await window.DAYAN_RESULTS?.openDataManager(window.DAYAN_RESULTS?.datasetFocus);
  }
}

/* 模型页数据缓存 + 搜索过滤 + 族类筛选渲染（含 WP1 忠实度徽章） */
window._modelsData = null;
window._modelsFamily = "";
window._fidelityMap = null;      // mid → {fidelity, fidelity_zh, reviewed}
const FID_STYLE = {
  full:        ["#00ffa3", "完整"],
  lite:        ["#68bbef", "简化"],
  prototype:   ["#ffb74d", "原型"],
  method_demo: ["#c084fc", "例题"],
  registered:  ["#5a6a7a", "登记"],
};

function escapeCatalogText(value) {return String(value??"").replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));}
function fidBadge(m) {
  const f = window._fidelityMap && window._fidelityMap[m.model_id];
  if (!f) return '<span style="font:9px monospace;color:#5a6a7a">未审</span>';
  const [color, zh] = FID_STYLE[f.fidelity] || ["#5a6a7a", "?"];
  return `<span title="${(f.basis || "").replace(/"/g, "&quot;")}"
    style="font:9px monospace;padding:1px 6px;border-radius:3px;color:${color};border:1px solid ${color}55;background:${color}14">${zh}</span>`;
}

function renderModelsTable(query) {
  const el = document.getElementById("modelsTable");
  if (!el || !window._modelsData) return;
  const { models, runnable } = window._modelsData;
  const fam = window._modelsFamily || "";
  const q = (query || "").trim().toLowerCase();
  const filtered = models.filter(m => {
    if (fam && !m.model_id.startsWith(fam)) return false;
    if (!q) return true;
    return m.model_id.toLowerCase().includes(q) ||
      (m.name || "").toLowerCase().includes(q) ||
      (m.status || "").toLowerCase().includes(q);
  });
  const rows = filtered.slice(0, 200).map(m => {
    const run = runnable.has(m.model_id);
    return `<tr>
      <td><span class="dot ${run ? "run" : "reg"}"></span></td>
      <td class="mono">${m.model_id}</td>
      <td>${escapeCatalogText(m.name)}</td>
      <td>${escapeCatalogText(m.status)} ${fidBadge(m)}</td>
      <td>${run ? '<button class="run-btn" onclick="runFromCatalog(\'' + m.model_id + '\')">设置</button>' : "—"}</td>
    </tr>`;
  }).join("");
  const fams = ["", "BEH", "NET", "ECO", "SYS", "MET", "APP", "TOO", "CPL", "USR"];
  const fcounts = {};
  Object.values(window._fidelityMap || {}).forEach(f => {
    fcounts[f.fidelity] = (fcounts[f.fidelity] || 0) + 1;
  });
  el.innerHTML = `
    <div style="padding:8px 14px 4px;display:flex;gap:8px;align-items:center">
      <input id="modelsSearch" placeholder="搜索 ID / 名称 / 状态，如 ECO01、Schelling、基准通过…"
        value="${(query || "").replace(/"/g, "&quot;")}"
        style="flex:1;padding:6px 9px;background:#04070f;border:1px solid #1b2a4a;border-radius:4px;color:#d8e2f2;font-size:11px;outline:none" />
      <span style="font:9px monospace;color:#657f91;white-space:nowrap">匹配 ${filtered.length} / ${models.length}</span>
    </div>
    <div style="display:flex;gap:4px;padding:2px 14px 6px;flex-wrap:wrap">
      ${fams.map(f => `<button class="fam-chip ${fam === f ? "on" : ""}" data-fam="${f}"
        style="padding:3px 9px;font:9px monospace;border-radius:3px;cursor:pointer;border:1px solid ${fam === f ? "#00e5ff" : "#1b2a4a"};color:${fam === f ? "#00e5ff" : "#8fa2c2"};background:${fam === f ? "rgba(0,229,255,.08)" : "transparent"}">${f || "全部"}</button>`).join("")}
      <span style="font:9px monospace;color:#657f91;margin-left:6px">忠实度：
        完整 ${fcounts.full || 0} · 简化 ${fcounts.lite || 0} · 原型 ${fcounts.prototype || 0} · 例题 ${fcounts.method_demo || 0} · 登记 ${fcounts.registered || 0}
        （悬停徽章看依据）</span>
    </div>
    <table class="modal-table"><thead>
      <tr><th></th><th>ID</th><th>名称</th><th>状态 / 忠实度</th><th>运行</th></tr>
    </thead><tbody>${rows}</tbody></table>
    <div class="modal-note">${q || fam ? `筛选命中 ${filtered.length} 条` : "显示前 200 条"} / 目录共 ${models.length} 条 ·
    可运行 ${runnable.size} 个 · 忠实度分级经源码逐模型审查（未审条目按原型降级处理，不虚标）</div>`;
  const inp = document.getElementById("modelsSearch");
  if (inp) {
    inp.addEventListener("input", () => {
      const pos = inp.selectionStart;
      renderModelsTable(inp.value);
      const inp2 = document.getElementById("modelsSearch");
      if (inp2) { inp2.focus(); inp2.setSelectionRange(pos, pos); }
    });
  }
  document.querySelectorAll(".fam-chip").forEach(chip => {
    chip.addEventListener("click", () => {
      window._modelsFamily = chip.dataset.fam || "";
      renderModelsTable(document.getElementById("modelsSearch")?.value || "");
    });
  });
}

async function loadModelsPage() {
  const el = document.getElementById("modelsTable");
  if (!el) return;
  try {
    const r = await fetch("/api/catalog");
    const d = await r.json();
    const models = d.models || [];
    const r2 = await fetch("/api/models/runnable");
    const d2 = await r2.json();
    const runnable = new Set((d2.models || []).map(m => m.model_id));
    // WP1 忠实度目录（独立来源，失败不阻塞表格渲染）
    if (!window._fidelityMap) {
      try {
        const r3 = await fetch("/api/models/catalog");
        const d3 = await r3.json();
        window._fidelityMap = {};
        (d3.models || []).forEach(m => {
          window._fidelityMap[m.model_id] = m;
        });
      } catch (e2) { window._fidelityMap = null; }
    }
    window._modelsData = { models, runnable };
    renderModelsTable(window._modelsQuery || "");
  } catch (e) {
    el.innerHTML = `<p>加载失败：${e.message}</p>`;
  }
}

function toastMsg(text, warn) {
  const t = document.getElementById("toast");
  if (t) {
    t.textContent = text;
    t.classList.add("show");
    t.style.borderColor = warn ? "rgba(255,77,109,.6)" : "";
    setTimeout(() => { t.classList.remove("show"); t.style.borderColor = ""; }, 3200);
  }
  if (window.DAYAN_EVENT) DAYAN_EVENT(warn ? "warn" : "", text, "");
}

/* 兼容入口：只读实际归档或观测，不为画面重新计算。 */
async function visualizeWithState(mid, obs, params, ticks, meta) {
  if(!window.DAYAN_RESULTS)throw new Error('研究工作台尚未就绪');
  if(meta?.run_id)return DAYAN_RESULTS.restore(meta.run_id);
  // Compatibility calls lacking a canonical run ID may display observations only; never rerun for a picture.
  return DAYAN_RESULTS.showResult('run',{model_id:mid,run_id:null,observations:obs||[]},{intent:'兼容观测回放'});
}

async function runFromCatalog(mid) {
  try {
    if (window.DAYAN_EVENT) DAYAN_EVENT("", `手动运行 ${mid}`, "仿真执行中…");
    toastMsg(`⏳ ${mid} 运行中…`);
    const r = await fetch("/api/run", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ model_id: mid, ticks: 100 })
    });
    const d = await r.json();
    if (d.ok) {
      toastMsg(`✓ ${mid} 运行成功（${d.n} obs）`);
      // WP3/WP5：参数警告如实披露（未知参数/别名/类型改写）
      const warns = (d.manifest && d.manifest.warnings) || [];
      if (warns.length) {
        if (window.DAYAN_EVENT) DAYAN_EVENT("warn", `${mid} 参数提示`,
          warns.slice(0, 3).join("；").slice(0, 120));
      }
      await visualizeWithState(mid, d.observations || [], {}, 100, {});
      dashFromObs(mid, d.observations || [], "手动运行");
      updateObsPanel(mid, d.observations || [], "手动运行");
      rememberRun(mid, d.observations || [], {}, 100, "手动运行", "manual", "run " + mid, "手动运行 " + mid);
      aiReportButton({ model_id: mid, observations: d.observations || [],
                       intent: "手动运行", planner: "manual",
                       manifest: d.manifest || {}, analysis: {} });
      if (window.DAYAN_EVENT) DAYAN_EVENT("", `模型运行完成 ${mid}`, `${d.n} 个观测 · 3D 场景已更新`);
    } else {
      toastMsg(`✗ ${mid} 运行失败`, true);
      if (window.DAYAN_EVENT) DAYAN_EVENT("warn", `运行失败 ${mid}`, d.error || "");
    }
  } catch (e) {
    toastMsg("✗ 运行失败: " + e.message, true);
  }
}

function loadScenariosPage() {
  const el = document.getElementById("scenariosGrid");
  if (!el) return;
  const scenarios = [
    { id: "NET106", name: "城市交通流", desc: "Nagel-Schreckenberg CA · 车流密度与通量", params: "density, vmax, p" },
    { id: "NET052", name: "SIS 疫情传播", desc: "易感-感染-易感 · 地方病均衡", params: "beta, gamma" },
    { id: "ECO015", name: "Solow 增长", desc: "外生储蓄 → 稳态资本 k*", params: "s, alpha, delta" },
    { id: "ECO016", name: "Ramsey 最优增长", desc: "跨期消费-储蓄权衡（打靶法鞍点）", params: "k0, beta, theta" },
    { id: "ECO047", name: "资产市场异质信念", desc: "基本面 vs 趋势交易者（Brock-Hommes）", params: "beta, g_t" },
    { id: "ECO054", name: "零智能交易者", desc: "Gode-Sunder 双向拍卖 · 配置效率", params: "n_buyers, n_sellers" },
    { id: "ECO091", name: "贝叶斯知识追踪", desc: "学习者掌握概率序列更新", params: "p0, learn, slip" },
    { id: "ECO110", name: "Richardson 军备竞赛", desc: "两国军备耦合 ODE · 稳定/发散", params: "a1, a2, r1, r2" },
  ];
  el.innerHTML = scenarios.map(s => `
    <div class="scenario-card" onclick="runFromCatalog('${s.id}')">
      <span class="scenario-id">${s.id}</span>
      <h3>${s.name}</h3>
      <p>${s.desc}</p>
      <span class="scenario-params">参数: ${s.params}</span>
      <button class="scenario-run">配置模型 →</button>
    </div>
  `).join("");
}

function loadReplayPage() {
  const el = document.getElementById("replayList");
  if (!el) return;
  const snaps = (typeof window.DAYAN_SNAPSHOTS === "function") ? window.DAYAN_SNAPSHOTS() : [];
  // 磁盘历史（跨会话持久化）
  fetch("/api/history?limit=20").then(r2 => r2.json()).then(hist => {
    const hh = t => { const m2 = String(Math.floor(t / 60) % 60).padStart(2, "0"); const s2 = String(Math.floor(t % 60)).padStart(2, "0"); return `T+${m2}:${s2}`; };
    el.innerHTML = `
      ${snaps.length ? `<div class="modal-note" style="margin:0">本会话快照（${snaps.length}）</div>
      <table class="modal-table"><thead><tr><th>回放节点</th><th>仿真时间</th><th>状态</th><th>操作</th></tr></thead><tbody>
      ${snaps.map(s2 => `<tr><td>${s2.name}</td><td class="mono">T+${String(Math.floor(s2.time / 3600)).padStart(2, "0")}:${String(Math.floor(s2.time % 3600 / 60)).padStart(2, "0")}</td><td>${s2.dash ? "模型仿真" : s2.branch ? "干预 B" : "基准 A"}</td><td><button class="run-btn" onclick="window.DAYAN_RESTORE(${s2.i});loadReplayPage()" title="恢复">↺</button></td></tr>`).join("")}
      </tbody></table>` : `<p style="color:#8ba6b8;font-size:12px;padding:12px 14px 4px">本会话还没有快照。运行仿真后点「◇ 快照」保存。</p>`}
      <div class="modal-note" style="margin:0">历史运行（磁盘持久化 · ${hist.count} 条，刷新不丢失）</div>
      <table class="modal-table"><thead><tr><th>模型</th><th>来源</th><th>时间</th><th>意图</th><th>操作</th></tr></thead><tbody>
      ${(hist.entries || []).map((e, i) => `<tr><td class="mono">${e.model_id}</td><td>${e.source}</td><td class="mono">${e.ts.slice(11, 16)}</td><td>${String(e.intent || "").slice(0, 18)}</td><td><button class="run-btn" onclick="window.DAYAN_HIST_RESTORE(${i})" title="恢复到驾驶舱">↺</button></td></tr>`).join("") || `<tr><td colspan="5" style="color:#5a7a8b">暂无</td></tr>`}
      </tbody></table>
      <div class="modal-note">恢复会将该运行的观测序列载入驾驶舱与 3D 场景（不重新计算）</div>`;
      window._histEntries = hist.entries || [];
  }).catch(() => {
    if (!el.innerHTML) el.innerHTML = `<p style="color:#8ba6b8;font-size:12px;padding:20px">历史加载失败。</p>`;
  });
}

/* 从磁盘历史恢复：直接载入观测序列，不重跑 */
window.DAYAN_HIST_RESTORE = function (i) {
  const entry=(window._histEntries||[])[i];if(!entry||!window.DAYAN_RESULTS)return;
  if(entry.complete&&entry.run_id)return DAYAN_RESULTS.restore(entry.run_id);
  return DAYAN_RESULTS.showResult('run',{...entry,run_id:null,observations:entry.observations||[]},{intent:'旧记录汇总回放'});
};
