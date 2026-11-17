/** Shared DSH-native tool bridge. All execution uses the platform's explicit tool contract. */
import { spawn } from 'node:child_process';
import { closeSync, existsSync, mkdirSync, openSync, readFileSync } from 'node:fs';
import { join } from 'node:path';
import { fileURLToPath } from 'node:url';

export const PROJECT_ROOT = process.env.DAYAN_PROJECT_ROOT || fileURLToPath(new URL('../../../', import.meta.url));
export const BACKEND_URL = process.env.DAYAN_BACKEND_URL || 'http://127.0.0.1:8899';
const endpoint = new URL(BACKEND_URL);
if (endpoint.protocol !== 'http:' || !['127.0.0.1', 'localhost', '[::1]'].includes(endpoint.hostname) || endpoint.pathname !== '/') throw new Error('DAYAN_BACKEND_URL must be a loopback HTTP origin');
let backendChild = null, startup = null, spawnFailure = null;

export async function backendOnline(timeout = 1800) {
  try {
    const r = await fetch(BACKEND_URL + '/api/health', { signal: AbortSignal.timeout(timeout) });
    const v = await r.json();
    return r.ok && v.service === 'dayan' && v.contract_version === 'research-integrity-1';
  } catch { return false; }
}

export function spawnBackend() {
  if (backendChild && backendChild.exitCode === null && !spawnFailure) return { started: false, pid: backendChild.pid };
  const dataDir = process.env.DAYAN_DATA_DIR || join(PROJECT_ROOT, 'data');
  mkdirSync(dataDir, { recursive: true });
  const log = openSync(join(dataDir, 'server_dsh.log'), 'a');
  const candidates = [process.env.DAYAN_PYTHON, join(PROJECT_ROOT, '.venv', 'Scripts', 'python.exe'), process.env.USERPROFILE && join(process.env.USERPROFILE, 'miniconda3', 'python.exe')].filter(Boolean);
  let python = candidates.find(p => existsSync(p)) || 'python';
  // pythonw avoids console allocation for a background host; the entry redirects logs explicitly.
  if (process.platform === 'win32' && /python\.exe$/i.test(python) && existsSync(python.replace(/python\.exe$/i, 'pythonw.exe'))) python=python.replace(/python\.exe$/i, 'pythonw.exe');
  spawnFailure = null;
  try {
    backendChild = spawn(python, ['-m', 'dayan.background_server'], { cwd: PROJECT_ROOT, windowsHide: true, detached: true,
      stdio: ['ignore', log, log], env: { ...process.env, DAYAN_PORT: endpoint.port || '80', PYTHONUNBUFFERED: '1' } });
    backendChild.unref();
    backendChild.on('error', error => { spawnFailure = error; });
    backendChild.on('exit', () => { backendChild = null; });
    return { started: true, pid: backendChild.pid, projectRoot: PROJECT_ROOT, python };
  } finally { closeSync(log); }
}

export async function ensureBackend() {
  if (await backendOnline()) return { online: true, url: BACKEND_URL };
  if (!startup) startup = (async () => {
    const spawnResult = spawnBackend();
    const deadline = Date.now() + 30000;
    while (Date.now() < deadline) {
      if (spawnFailure) throw spawnFailure;
      if (await backendOnline(1000)) return { online: true, url: BACKEND_URL, ...spawnResult };
      await new Promise(r => setTimeout(r, 350));
    }
    throw new Error('Backend did not become ready in 30s; inspect server_dsh.log in DAYAN_DATA_DIR');
  })().finally(() => { startup = null; });
  return startup;
}

export async function api(path, init = {}, signal) {
  await ensureBackend();
  const token = process.env.DAYAN_ACCESS_TOKEN || readFileSync(
    join(process.env.DAYAN_DATA_DIR || join(PROJECT_ROOT, 'data'), '.workbench-token'), 'utf8').trim();
  if (token.length < 32) throw new Error('Backend access capability is missing or invalid');
  const r = await fetch(BACKEND_URL + path, { ...init,
    signal: signal ? AbortSignal.any([signal, AbortSignal.timeout(285000)]) : AbortSignal.timeout(285000),
    headers: { 'content-type': 'application/json', ...(init.headers || {}), authorization: 'Bearer ' + token } });
  const raw = await r.text();
  let value; try { value = JSON.parse(raw); } catch { throw new Error('Backend returned invalid JSON (' + r.status + ')'); }
  if (!r.ok) throw new Error(typeof value.detail === 'string' ? value.detail : JSON.stringify(value));
  return value;
}

const aliases = { run: 'run', run_preset: 'run_preset', report_docx: 'research_report' };
const actions = ['health', 'list_models', 'contract', 'sources', 'presets', 'tasks', 'schema', 'execute', 'run', 'run_preset', 'report_docx', 'agent_hint'];
const hint = [
  '保留原始用户问题、地区、指标口径、时期、模型机制和分组；未能覆盖必须说明缺口，不能替换为中国人口或默认模型。',
  'schema列出全部平台工具及真实参数。execute的tool和arguments按schema传。DSH自身负责理解和调用；不要调用第二套agent接口。',
  '数据研究：collect_source/run_preset → collection_status（partial用相同ID续采）→ research_create（显式family/grid/tolerance/holdout）→ research_calibrate（返回新的study_id和run_id）→ research_report（只用新ID）。',
  '当前单变量研究适配器支持已核验WB国家年度指标的linear/exponential/logistic描述性趋势；不覆盖的机制须build_model或选择精确合同模型，不能将趋势拟合当政策因果。',
  '其他真实来源：collect_source可用huggingface_datasets/ckan_search发现目录，huggingface_file(repo_id,filename)/ckan_resource(instance,resource_id)真正下载，import_collection得到dataset_id；analyze_data后用run.data_bindings显式映射真实参数。目录/网页不算数值模型输入。',
  '通用模型：search_models→get_capabilities→run（支持dt/interventions/data_bindings），或build_model（完整原问题）；experiment/ensemble/sweep/compare/resume均通过execute可用。',
  '原始用户文本由DSH会话直接送到合同检查，不能改写研究问题绕过约束。总结只引用实测变化与产物，不添加未核实的趋势加速/因果解释。研究的interpretation是按真实观测减模型预测计算的方向事实，直接遵从其中interpretation_text；不能把模型下降过快说成实际下降更快。',
  '校准执行成功与validation_pass分开；训练通过而留出失败必须如实报告，不事后放宽阈值，不将网格唯一最优称为可识别。',
  '报告只能绑定具体study_id，返回file/bundle_url实际下载。不能拿旧report_B或旧复现包冒称本次结果。所有运行/研究结果会按当前原生会话同步工作台。'
].join('\n');

function boundedResult(value) {
  if (JSON.stringify(value).length < 65000) return value;
  const shrink = (v, key = '') => {
    if (Array.isArray(v)) {
      const cap = ['observations','evaluations','state_frames','records','preview'].includes(key) ? 8 : 60;
      return v.length > cap ? { total: v.length, preview: v.slice(0, cap).map(x => shrink(x)), truncated: true } : v.map(x => shrink(x));
    }
    if (v && typeof v === 'object') return Object.fromEntries(Object.entries(v).map(([k,x]) => [k,shrink(x,k)]));
    return v;
  };
  return { ...shrink(value), output_note: 'Long arrays are previews; full data remain in referenced run/study artifacts and download URLs.' };
}

export function dayanToolDefinition() {
  return {
    name: 'dayan', description: '大衍社会仿真与真实数据研究工具。DSH原生AI直接调用共享平台能力。先schema获取全部工具合同，execute执行。' + hint,
    parameters: { type: 'object', additionalProperties: false, required: ['action'], properties: {
      action: { type: 'string', enum: actions }, tool: { type: 'string', description: 'schema可按此名称过滤；execute必须提供平台工具名' },
      arguments: { type: 'object', description: 'execute参数严格按schema；保留原始问题和全部约束' },
      theme: { type: 'string' }, model_id: { type: 'string' }, study_id: { type: 'string' },
      ticks: { type: 'integer', minimum: 0, maximum: 10000 }, dt: { type: 'number', exclusiveMinimum: 0 }, seed: { type: 'integer' },
      parameters: { type: 'object' }, interventions: { type: 'array', items: { type: 'object' } }, data_bindings: { type: 'array', items: { type: 'object' } },
      preset_id: { type: 'string' }, values: { type: 'object' }, page_budget: { type: 'integer', minimum: 1, maximum: 50 },
      report: { type: 'string', enum: ['academic','B_academic','policy','data_quality'] }
    } },
    output: { schema: { type: 'object', additionalProperties: false, required: ['json'], properties: { json: { type: 'string' } } },
      render: (_args, value) => [{ type: 'text', text: value.json }] }, timeoutMs: 300000,
    async execute(args, exec = {}) {
      try {
        exec.signal?.throwIfAborted();
        let result;
        if (args.action === 'health') result = await ensureBackend();
        else if (args.action === 'agent_hint') result = { ok: true, workflow: hint };
        else if (args.action === 'schema') {
          const manifest = await api('/api/agent/tools', {}, exec.signal);
          result = { ok: true, tools: args.tool ? manifest.tools.filter(t => t.name === args.tool) : manifest.tools };
        } else if (args.action === 'list_models') result = await api('/api/models/search?theme='+encodeURIComponent(args.theme || ''), {}, exec.signal);
        else if (args.action === 'contract') result = await api('/api/models/contract/'+encodeURIComponent(args.model_id || ''), {}, exec.signal);
        else if (args.action === 'sources') result = await api('/api/collection/sources'+(args.theme ? '?theme='+encodeURIComponent(args.theme) : ''), {}, exec.signal);
        else if (args.action === 'presets') result = await api('/api/collection/presets', {}, exec.signal);
        else if (args.action === 'tasks') result = await api('/api/collection/tasks', {}, exec.signal);
        else {
          const tool = args.action === 'execute' ? args.tool : aliases[args.action];
          if (!tool) throw new Error('Unknown action; use schema then execute');
          let parameters = args.arguments;
          if (args.action === 'run') parameters = Object.fromEntries(['model_id','ticks','dt','seed','parameters','interventions','data_bindings'].filter(k => args[k] !== undefined).map(k => [k,args[k]]));
          if (args.action === 'run_preset') parameters = { preset_id: args.preset_id, values: args.values || {}, page_budget: args.page_budget ?? 2 };
          if (args.action === 'report_docx') parameters = { study_id: args.study_id, kind: args.report === 'B_academic' ? 'academic' : args.report || 'academic' };
          if (!parameters || typeof parameters !== 'object' || Array.isArray(parameters)) throw new Error('execute needs arguments object');
          const session = exec.agent?.session;
          const sessionId = session?.id;
          const user = session?.snapshotEvents?.().filter(e => e.type === 'user/message' && e.data?.source?.kind === 'user').at(-1);
          const userContent = user?.data?.content || user?.data?.message?.content || [];
          const originalText = userContent.filter(b => b.type === 'text').map(b => b.text).join('\n');
          result = await api('/api/tools/'+encodeURIComponent(tool), { method: 'POST', body: JSON.stringify({ arguments: parameters,
            ...(sessionId ? { origin: 'dsh', session_id: sessionId, original_text: originalText } : {}) }) }, exec.signal);
        }
        return { json: JSON.stringify(boundedResult(result)) };
      } catch (error) { return { json: JSON.stringify({ ok: false, error: String(error?.message || error) }) }; }
    }
  };
}

export function registerDayanTool(ctx) {
  ctx.inject(['tools'], scope => {
    const off = scope.tools.register(dayanToolDefinition());
    if (typeof off === 'function') scope.effect(() => off, 'dayan: shared platform tool');
  });
}

export async function stopManagedBackend() {
  if (!backendChild || backendChild.exitCode !== null) return { stopped: false };
  const child = backendChild, pid = child.pid;
  const ended = new Promise(resolve => child.once('exit', resolve));
  child.kill();
  await Promise.race([ended, new Promise(r => setTimeout(r, 5000))]);
  return { stopped: child.exitCode !== null, pid };
}
