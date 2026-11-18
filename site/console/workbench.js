/* The console shell reads the same archives and supervisor as the simulation. */
(() => {
  'use strict';
  const $ = selector => document.querySelector(selector);
  const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const format = new Intl.NumberFormat('zh-CN');
  const date = value => value ? new Date(value).toLocaleString('zh-CN', {hour12:false}) : '未记录';
  const number = value => Number.isFinite(value) ? format.format(value) : '—';
  const bytes = (value, power = 30) => Number.isFinite(value) ? (value / 2 ** power).toFixed(2) : '—';
  const write = (selector, value) => { const element = $(selector); if (element && element.textContent !== String(value)) element.textContent = value; };
  const empty = value => `<p class="space-empty">${esc(value)}</p>`;
  const taskNames = {
    api_run:'仿真运行', api_experiment:'配对实验', api_agent:'研究助手', api_platform_tool:'研究工具',
    api_run_preset:'数据采集', api_dataset_collect:'数据下载', api_report:'生成研究报告',
    api_prepare_bundle:'复现包', api_resume:'检查点续算',
  };
  const validations = {pass:'独立留出通过', failed_holdout:'独立留出未通过', prepared:'规约已建立', calibrated:'已校准'};
  const embedded = new URLSearchParams(location.search).get('embed') === 'dsh';
  const telemetry = [];
  let status, catalogTask, assets, assetsPromise, pollTimer;
  let queueMarkup = '';

  async function api(path, body, method = body === undefined ? 'GET' : 'POST') {
    const request = body === undefined ? {method} : {method, headers:{'Content-Type':'application/json'}, body:JSON.stringify(body)};
    const response = await fetch(path, request);
    const data = await response.json().catch(() => ({}));
    if (!response.ok) {
      const reason = typeof data.detail === 'string' ? data.detail : data.detail?.map?.(x => x.msg).join('；');
      throw new Error(reason || `请求未成功（HTTP ${response.status}）`);
    }
    return data;
  }
  function preference(key, value, session = false) {
    try {
      const store = session ? sessionStorage : localStorage;
      if (value === undefined) return store.getItem(key);
      store.setItem(key, value);
    } catch {}
    return null;
  }
  const catalog = () => catalogTask ||= api('/api/models/catalog').catch(error => {catalogTask = null; throw error;});
  function jobTable(jobs) {
    return jobs.length ? `<div class="system-rows">${jobs.map(j => `
      <div class="system-row"><div><b>${esc(taskNames[j.target] || '引擎任务')}</b><small>${esc(j.stage)}</small></div>
      <span class="state-pill" data-state="${esc(j.status)}">${j.status === 'queued' ? '排队' : '执行中'}</span>
      <button class="ws-button stop-job" data-cancel-job="${esc(j.job_id)}">取消</button></div>`).join('')}</div>`
      : empty('队列空闲。开始仿真或采集时，任务会显示在这里。');
  }
  function resourceSpark(values) {
    if (values.length < 2 || !values.some(Number.isFinite)) return '';
    const points = values.map((v,i) => `${(i * 320 / (values.length - 1)).toFixed(1)},${(38 - Math.max(0, Math.min(1, v)) * 36).toFixed(1)}`).join(' ');
    return `<svg class="resource-spark" viewBox="0 0 320 40" preserveAspectRatio="none" role="img" aria-label="最近 ${values.length} 次实际内存占用采样，纵轴 0 到 100%"><path d="M0 38H320M0 20H320M0 2H320" class="spark-grid"/><polyline points="${points}"/></svg>`;
  }
  function paintStatus(sample) {
    status = sample;
    const {queue, resources} = sample;
    const active = queue.jobs.length;
    write('#connectionStatus', '引擎在线');
    $('#connectionStatus').dataset.state = 'online';
    $('#notificationCount').hidden = !active;
    write('#notificationCount', active);
    write('#missionSample', date(sample.sampled_at));
    write('#missionJobs', `${queue.running} / ${queue.queued}`);
    write('#missionQueueNote', `执行容量 ${queue.concurrent_limit} · 等待容量 ${queue.queue_limit}`);
    const markup = jobTable(queue.jobs);
    if (markup !== queueMarkup) {
      queueMarkup = markup;
      $('#missionQueue').innerHTML = markup;
    }
    telemetry.push(resources.host_memory_used_bytes / resources.host_memory_total_bytes);
    if (telemetry.length > 36) telemetry.shift();
    $('#missionResources').innerHTML = `<div class="resource-meters">
      <div><span>引擎常驻内存</span><b>${bytes(resources.engine_rss_bytes,20)} MiB</b></div>
      <div><span>主机内存已用</span><b>${bytes(resources.host_memory_used_bytes)} / ${bytes(resources.host_memory_total_bytes)} GiB</b></div>
      <meter min="0" max="1" value="${telemetry.at(-1)}" aria-label="主机内存已用比例"></meter>
      ${resourceSpark(telemetry)}
      <div><span>数据卷可用</span><b>${bytes(resources.disk_free_bytes)} GiB</b></div>
      <div><span>引擎已运行</span><b>${number(Math.round(sample.uptime_seconds))} 秒</b></div>
      <div><span>规划器</span><b>${sample.planner === 'configured' ? '语言模型已配置' : '规则规划可用'}</b></div>
      <div><span>执行源码</span><code title="${esc(sample.revision)}">${esc(sample.revision?.slice(0, 12))}</code></div>
      </div>`;
  }
  async function refreshStatus() {
    try {
      paintStatus(await api('/api/workbench/status'));
    } catch (error) {
      status = null;
      write('#connectionStatus', '引擎连接异常');
      $('#notificationCount').hidden = true;
      $('#connectionStatus').dataset.state = 'error';
      write('#missionSample', '实时状态不可用');
      write('#missionJobs', '—');
      $('#missionResources').replaceChildren();
      $('#missionQueue').innerHTML = empty(error.message);
      queueMarkup = '';
      throw error;
    }
  }
  async function poll() {
    if (document.hidden) return;
    try { await refreshStatus(); } catch {}
    if (!document.hidden) pollTimer = setTimeout(poll, document.body.dataset.page === 'mission' ? 3100 : 7400);
  }
  function showAssets(results) {
    const [modelData, datasetData, collectionData, studyData, historyData] = results.map(item => item.value);
    if (modelData) {
      const c = modelData.counts;
      write('#missionModels', number(c.factory_entries));
      write('#missionModelNote', `${number(c.total)} 个目录条目 · ${number(c.reviewed)} 个当前机制审查`);
      const labels = {full:'完整实现',lite:'显式简化',prototype:'原型',method_demo:'方法示例',registered:'仅登记'};
      $('#missionCapability').innerHTML = `<div class="capability-chart" aria-label="按实现级别统计目录条目">
        ${Object.entries(c.fidelity).map(([key,v]) => `<div data-fidelity="${esc(key)}"><span>${esc(labels[key] || key)}</span><div class="capability-bar"><i style="width:${v / Math.max(1,c.total) * 100}%"></i></div><b>${number(v)}</b></div>`).join('')}
        </div><p class="space-note">当前源码探针通过 ${number(c.probe_passed)} · 外部依赖 ${number(c.probe_skipped_external)} · 无模型工厂 ${number(c.registered_no_factory)}</p>`;
    }
    if (datasetData && collectionData) {
      write('#missionDatasets', number(datasetData.datasets.filter(d => d.role === 'input').length));
      write('#missionDataNote', `${number(datasetData.datasets.length)} 个本地资产 · ${number(collectionData.n_tasks)} 个采集任务`);
    }
    if (studyData) {
      const completed = studyData.studies.filter(s => Boolean(s.calibration));
      write('#missionStudies', number(studyData.studies.length));
      write('#missionStudiesNote', `${number(completed.length)} 条已归档验证`);
      const failed = (collectionData?.tasks || []).filter(t => ['error','blocked','failed','quota'].includes(t.status));
      $('#missionEvidence').innerHTML = completed.length || failed.length ? `<div class="system-rows">
        ${completed.slice(0,5).map(s => `<button class="system-row row-action" data-study="${esc(s.study_id)}"><div><b>${esc(s.question)}</b><small>${esc(s.study_id)}</small></div><span class="state-pill" data-state="${esc(s.calibration.status)}">${esc(validations[s.calibration.status] || s.calibration.status)}</span></button>`).join('')}
        ${failed.slice(0,3).map(t => `<div class="system-row"><div><b>${esc(t.source_id)}</b><small>${esc(t.error || t.status)}</small></div><button data-go="data">检查采集 ↗</button></div>`).join('')}</div>`
        : empty('当前没有留出验证或采集异常记录。');
    }
    if (historyData) {
      const rows = historyData.entries;
      $('#missionHistory').innerHTML = rows.length ? `<div class="system-rows">
        ${rows.slice(0,6).map(r => `<button class="system-row row-action" data-open-run="${esc(r.run_id)}"><div><b>${esc(r.intent || r.model_id)}</b><small>${esc(r.model_id)} · ${esc(r.run_id)}</small></div><time datetime="${esc(r.created_at)}">${esc(date(r.created_at))}</time><span aria-hidden="true">↗</span></button>`).join('')}
        </div>` : empty('还没有研究档案。运行后的模型、状态和结果会出现在这里。');
      write('#missionContext', rows.length ? `最近研究 · ${rows[0].intent || rows[0].model_id}` : '本地研究工作区 · 尚无完整运行');
    }
    write('#missionError', results.some(r => r.status === 'rejected') ? '部分档案读取失败，可刷新重试。' : '');
  }
  async function mission(force = false) {
    if (force) catalogTask = null;
    if (!force && assets && Date.now() - assets.at < 5000) return;
    if (assetsPromise) return assetsPromise;
    assetsPromise = Promise.allSettled([
      catalog(), api('/api/datasets'), api('/api/collection/tasks?limit=30'),
      api('/api/research/studies'), api('/api/history?metadata_only=true&limit=8'),
    ]).then(results => {
      assets = {...assets, at:Date.now(), history:results[4].value?.entries || []};
      showAssets(results);
    }).finally(() => {assetsPromise = null;});
    return assetsPromise;
  }

  const commandActions = [
    ['仿真指挥 · 向 AI 描述需求', () => window.toggleAIDrawer()],
    ['专业参数 · 检查或调整模型合同', () => {switchPage('overview'); window.DAYAN_COMMAND.setMode('professional');}],
    ['当前运行 · 播放或暂停', () => {switchPage('overview'); const s = window.DAYAN_RESULTS; if (s.runs.length) s.setPlaying(!s.playing);}],
    ['当前运行 · 研究包', () => {switchPage('overview'); const a = $('#exportBundle'); if (a.href) a.click(); else window.DAYAN_NOTICE('需要完整的运行档案。');}],
    ['切换全屏', () => $('#fullscreen').click()],
  ];
  function palette() {
    window.DAYAN_MODAL('搜索与操作', `<label class="palette-label">工作空间、模型 ID 或操作<input id="paletteQuery" type="search" placeholder="例如 NET106、留出验证或数据中心" autocomplete="off"></label><div id="paletteResults" class="palette-results" aria-label="可用操作"></div>`);
    const query = $('#paletteQuery'), host = $('#paletteResults');
    let models = [];
    const openModel = mid => {
      switchPage('models');
      if (window.DAYAN_TOOLS) window.DAYAN_TOOLS.openModel(mid);
      else window.DAYAN_COMMAND.chooseModel(mid);
    };
    const update = () => {
      const term = query.value.trim().toLowerCase();
      const pages = [...document.querySelectorAll('[data-nav]')].map(b => [b.title, () => switchPage(b.dataset.nav)]);
      const modelMatches = term ? models.filter(m => `${m.model_id} ${m.name}`.toLowerCase().includes(term)).slice(0,7).map(m => [`${m.model_id} · ${m.name}`, () => openModel(m.model_id)]) : [];
      const choices = [...pages, ...commandActions].filter(([label]) => !term || label.toLowerCase().includes(term)).concat(modelMatches);
      host.replaceChildren();
      for (const [label, perform] of choices) {
        const button = document.createElement('button');
        button.textContent = label;
        button.onclick = () => {window.DAYAN_CLOSE_MODAL(); perform();};
        host.append(button);
      }
      if (!choices.length) host.textContent = '没有匹配操作';
    };
    query.oninput = update;
    query.onkeydown = e => {
      if (e.key === 'Enter') {e.preventDefault(); host.querySelector('button')?.click();}
      if (e.key === 'ArrowDown') {e.preventDefault(); host.querySelector('button')?.focus();}
    };
    host.onkeydown = e => {
      if (e.key === 'ArrowDown') {e.preventDefault(); document.activeElement.nextElementSibling?.focus();}
      if (e.key === 'ArrowUp') {e.preventDefault(); (document.activeElement.previousElementSibling || query).focus();}
    };
    update(); query.focus();
    catalog().then(data => {models = data.models; if (query.isConnected) update();}).catch(() => {});
  }
  function resizeRail() {
    const rail = $('#operationRail'), shell = $('#commandShell'), handle = document.createElement('div');
    rail.before(handle);
    handle.id = 'operationResize';
    handle.tabIndex = 0;
    handle.setAttribute('role','separator');
    handle.setAttribute('aria-label','调整对话与参数面板宽度');
    handle.setAttribute('aria-orientation','vertical');
    const initial = () => innerWidth >= 1850 ? 354 : 294;
    const apply = (value, remember = false) => {
      const maximum = Math.max(260, Math.min(630, shell.clientWidth - 560));
      const width = Math.max(260, Math.min(maximum, value));
      shell.style.setProperty('--operation-width', width + 'px');
      for (const [attribute, val] of Object.entries({valuemin:260,valuemax:maximum,valuenow:width,valuetext:width + ' 像素'})) handle.setAttribute('aria-'+attribute, val);
      if (remember) preference('dayan_operation_width_vnext', width);
    };
    const preferred = () => Number(preference('dayan_operation_width_vnext')) || initial();
    let drag;
    handle.onpointerdown = e => {
      if (e.button !== 0) return;
      drag = {pointer:e.pointerId, x:e.clientX, width:rail.getBoundingClientRect().width};
      handle.setPointerCapture(e.pointerId); handle.classList.add('dragging'); e.preventDefault();
    };
    window.addEventListener('pointermove', e => {
      if (drag?.pointer === e.pointerId) apply(drag.width + drag.x - e.clientX);
    });
    const finish = e => {
      if (drag?.pointer !== e.pointerId) return;
      const width = e.type === 'pointerup' ? drag.width + drag.x - e.clientX : rail.getBoundingClientRect().width;
      drag = null; handle.classList.remove('dragging'); apply(Math.round(width), true);
      window.dispatchEvent(new Event('resize'));
    };
    window.addEventListener('pointerup', finish);
    window.addEventListener('pointercancel', finish);
    handle.onlostpointercapture = finish;
    handle.ondblclick = () => {apply(initial(),true);window.dispatchEvent(new Event('resize'));};
    handle.onkeydown = e => {
      const change = e.key === 'ArrowLeft' ? 24 : e.key === 'ArrowRight' ? -24 : 0;
      if (!change && e.key !== 'Home' && e.key !== 'End') return;
      apply(change ? Math.round(rail.getBoundingClientRect().width) + change : e.key === 'Home' ? 260 : 630, true);
      e.preventDefault(); window.dispatchEvent(new Event('resize'));
    };
    window.addEventListener('resize', () => {if (!drag) apply(preferred());});
    apply(preferred());
  }
  function collapseNavigation(collapsed) {
    document.body.classList.toggle('nav-collapsed', collapsed);
    const button = $('#collapseNavigation');
    button.setAttribute('aria-expanded', String(!collapsed));
    button.title = collapsed ? '展开导航' : '收起导航';
    button.setAttribute('aria-label', button.title);
    button.textContent = collapsed ? '⇥' : '⇤';
    window.dispatchEvent(new Event('resize'));
  }
  function notification() {
    const count = status?.queue.jobs.length || 0;
    window.DAYAN_MODAL('任务与通知', `<div class="notification-body">${status ? jobTable(status.queue.jobs) : empty('当前未取得引擎状态。')}<p class="space-note">${count ? '此列表为打开时的队列快照。' : ''}</p><button class="ws-button" data-go="mission">前往运行队列</button></div>`);
  }
  function boot() {
    resizeRail();
    collapseNavigation(preference('dayan_nav_vnext') === 'collapsed' || (embedded && !preference('dayan_nav_vnext')));
    $('#collapseNavigation').onclick = () => {
      const collapsed = !document.body.classList.contains('nav-collapsed');
      preference('dayan_nav_vnext', collapsed ? 'collapsed' : 'expanded');
      collapseNavigation(collapsed);
    };
    $('#openPalette').onclick = palette;
    $('#notificationButton').onclick = () => refreshStatus().catch(()=>{}).then(notification);
    document.addEventListener('keydown', e => {
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'k') {e.preventDefault(); palette();}
    });
    document.addEventListener('click', async e => {
      const button = e.target.closest('[data-nav],[data-go],[data-open-run],[data-study],[data-cancel-job]');
      if (!button) return;
      const {nav,go,openRun,study,cancelJob} = button.dataset;
      try {
        if (nav || go) { window.DAYAN_CLOSE_MODAL(); switchPage(nav || go); }
        if (openRun) await window.DAYAN_RESULTS.restore(openRun);
        if (study) await window.DAYAN_TOOLS.openStudy(study);
        if (cancelJob) {
          button.disabled = true;
          await api('/api/jobs/'+encodeURIComponent(cancelJob), undefined, 'DELETE');
          window.DAYAN_NOTICE('已提交取消，现有归档保留。');
          await refreshStatus();
          if (button.closest('.modal')) notification();
        }
      } catch (error) {button.disabled = false; window.DAYAN_NOTICE(error.message);}
    });
    $('#refreshMission').onclick = () => Promise.allSettled([mission(true),refreshStatus()]);
    document.addEventListener('visibilitychange', () => { clearTimeout(pollTimer); if (!document.hidden) poll(); });
    const params = new URLSearchParams(location.search);
    const saved = preference('dayan_space_vnext', undefined, true);
    const initial = embedded || params.has('run') ? 'overview' : Object.hasOwn(pageIds, saved) ? saved : 'mission';
    switchPage(initial, false);
    if (initial === 'overview' && !embedded && !params.has('run')) window.DAYAN_COMMAND.restoreDefault();
    if (!embedded) {
      const input = $('#aiInput');
      input.value = preference('dayan_assistant_draft_vnext',undefined,true) || '';
      input.addEventListener('input', () => preference('dayan_assistant_draft_vnext', input.value, true));
    }
    poll();
  }
  window.DAYAN_WORKBENCH = {api, catalog, esc, date, number, empty, write, preference, validations, refreshStatus,
    load(name) {
      if (name === 'mission') return mission();
      return window.DAYAN_TOOLS?.load(name);
    },
  };
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', boot);
  else boot();
})();
