/* 大衍 DAYAN 页面切换 + AI 助手抽屉 */
"use strict";

/* ---- 页面切换 ---- */
const pageIds = Object.fromEntries([...document.querySelectorAll("[data-workspace-page]")].map(page => [page.id.slice(4).toLowerCase(), page]));

function switchPage(name, remember = true) {
  if (!Object.hasOwn(pageIds, name)) return;
  const previous = document.body.dataset.page;
  document.body.dataset.page = name;
  for (const [key, page] of Object.entries(pageIds)) page.hidden = key !== name;
  for (const button of document.querySelectorAll("[data-nav]")) {
    const active = button.dataset.nav === (name === "scenarios" ? "lab" : name);
    button.classList.toggle("active", active);
    if (active) button.setAttribute("aria-current", "page");
    else button.removeAttribute("aria-current");
  }
  document.getElementById("systemPath").textContent =
    document.querySelector("[data-nav][aria-current]")?.title || "研究工作台";
  if (remember && new URLSearchParams(location.search).get("embed") !== "dsh") {
    try { sessionStorage.setItem("dayan_space_vnext", name); } catch {}
  }
  if (previous !== name) {
    if (previous === "overview") window.DAYAN_RESULTS?.setPlaying(false);
    if (previous) window.scrollTo(0, 0);
    window.dispatchEvent(new CustomEvent("dayan:page", {detail: name}));
    if (name === "overview") requestAnimationFrame(() => {window.dispatchEvent(new Event("resize"));window.DAYAN_RESULTS?.paint();});
  }
  const task = window.DAYAN_WORKBENCH?.load(name) || loadPageContent(name);
  return Promise.resolve(task).catch(error => window.DAYAN_NOTICE?.(error.message));
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

/* Results, reports, playback and interventions share DAYAN_RESULTS. */
window._aiMsgs = [];

async function aiSend() {
  if(window.DAYAN_RESULTS?.send)return DAYAN_RESULTS.send();
  window.DAYAN_NOTICE?.('研究工作台尚未就绪，请稍后发送。');
}

/* ---- 初始化 ---- */
// 页面脚本在 app.js 之后加载，DOMContentLoaded 已触发 → 直接执行
  createAIDrawer();

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
    await Promise.all([
      window.DAYAN_RESULTS?.openDataManager(window.DAYAN_RESULTS?.datasetFocus),
      window.DAYAN_RESEARCH?.loadSources(),
    ]);
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
  return `<span title="${escapeCatalogText(f.basis)}"
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
        value="${escapeCatalogText(query)}"
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
    有运行入口 ${runnable.size} 个 · 探针、当前机制审查、校准和独立留出分别核验；历史审查失效时按原型显示</div>`;
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
    el.innerHTML = `<p>加载失败：${escapeCatalogText(e.message)}</p>`;
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
  if(window.DAYAN_COMMAND)return DAYAN_COMMAND.chooseModel(mid);
  window.DAYAN_NOTICE?.('参数工作台尚未就绪，请稍后重试。');
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
  if(window.DAYAN_RESULTS)return DAYAN_RESULTS.loadReplay();
  document.getElementById('replayList').textContent='归档工作台尚未就绪。';
}
