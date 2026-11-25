/** Shared DSH-native tool bridge. All execution uses the platform's explicit tool contract. */
import { spawn } from 'node:child_process';
import { createHmac, createHash } from 'node:crypto';
import { closeSync, existsSync, mkdirSync, openSync, readFileSync } from 'node:fs';
import { isAbsolute, join, relative, resolve, sep } from 'node:path';
import { fileURLToPath } from 'node:url';
import { createConnection } from 'node:net';
import { isDeepStrictEqual } from 'node:util';
import { setTimeout as pause } from 'node:timers/promises';
import { projectScopeKey } from './session-binding.js';
import { readModelDefinition } from './model-definition-file.js';
import { readToolArguments } from './tool-arguments-file.js';
import { recoverPendingDesign, rememberPendingDesign } from './design-continuation.js';

// Captured when this module is evaluated, not reread when a health request arrives.
export const LOADED_BRIDGE_SOURCE=createHash('sha256').update(readFileSync(new URL(import.meta.url))).digest('hex');

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

async function portBound() {
  return new Promise(resolve=>{
    const socket=createConnection({host:endpoint.hostname.replace(/^\[|\]$/g,''),port:Number(endpoint.port||80)});
    let settled=false;const finish=value=>{if(settled)return;settled=true;socket.destroy();resolve(value);};
    socket.setTimeout(400,()=>finish(false));socket.once('connect',()=>finish(true));socket.once('error',()=>finish(false));
  });
}

export async function ensureBackend({timeoutMs=30000}={}) {
  if (await backendOnline()) return { online: true, url: BACKEND_URL };
  if (!startup) startup = (async () => {
    // A slow/busy listener is not permission to start a competing backend.
    const occupied=await portBound();
    const spawnResult = occupied?{started:false}:spawnBackend();
    const deadline = Date.now() + timeoutMs;
    while (Date.now() < deadline) {
      if (spawnFailure) throw spawnFailure;
      if (await backendOnline(1000)) return { online: true, url: BACKEND_URL, ...spawnResult };
      await new Promise(r => setTimeout(r, 350));
    }
    throw new Error(occupied?'Backend port is already occupied but health is unavailable; no competing process was started':
      'Backend did not become ready within startup timeout; inspect server_dsh.log in DAYAN_DATA_DIR');
  })().finally(() => { startup = null; });
  return startup;
}

function authoringTimeoutMs(extraSeconds) {
  const seconds = Number(process.env.DAYAN_AUTHORING_WALL_SECONDS || process.env.DAYAN_WALL_SECONDS || 900);
  if (!Number.isFinite(seconds) || seconds <= 0 || seconds > 3600)
    throw new Error('建模等待预算须为0到3600秒之间的正数');
  return (seconds + extraSeconds) * 1000;
}

export async function api(path, init = {}, signal, researchScope) {
  await ensureBackend();
  const token = process.env.DAYAN_ACCESS_TOKEN || readFileSync(
    join(process.env.DAYAN_DATA_DIR || join(PROJECT_ROOT, 'data'), '.workbench-token'), 'utf8').trim();
  if (token.length < 32) throw new Error('Backend access capability is missing or invalid');
  if (researchScope) {
    const body = JSON.parse(init.body);
    const proof = createHmac('sha256', token)
      .update(`dayan-research-memory-v1\n${body.session_id}\n${researchScope}`).digest('hex');
    init = { ...init, body: JSON.stringify({ ...body, research_scope: researchScope, research_scope_proof: proof }) };
  }
  const isAuthoring = /^\/api\/tools\/(design_model|build_model|reviewed_run)$/.test(path);
  const timeoutMs = isAuthoring ? Math.max(285000, authoringTimeoutMs(45)) : 285000;
  const r = await fetch(BACKEND_URL + path, { ...init,
    signal: signal ? AbortSignal.any([signal, AbortSignal.timeout(timeoutMs)]) : AbortSignal.timeout(timeoutMs),
    headers: { 'content-type': 'application/json', ...(init.headers || {}), authorization: 'Bearer ' + token } });
  const raw = await r.text();
  let value; try { value = JSON.parse(raw); } catch { throw new Error('Backend returned invalid JSON (' + r.status + ')'); }
  if (!r.ok) throw new Error(typeof value.detail === 'string' ? value.detail : JSON.stringify(value));
  return value;
}

export async function waitForPlatformJob(jobId, signal) {
  if (typeof jobId !== 'string' || !/^[a-f0-9]{32}$/.test(jobId)) throw new Error('Backend returned an invalid job ID');
  const budget = AbortSignal.timeout(Math.max(285000, authoringTimeoutMs(45)));
  const combined = signal ? AbortSignal.any([signal, budget]) : budget;
  try {
    while (true) {
      const job = await api('/api/jobs/' + encodeURIComponent(jobId) + '?preview=true', {}, combined);
      if (job.status === 'done') {
        if (!job.result || typeof job.result !== 'object') throw new Error('Completed backend job has no verifiable result');
        return job.result;
      }
      if (job.status === 'error') return { ok: false, error: job.error || 'Backend job failed',
        job_id: jobId, terminal_reason: job.terminal_reason };
      if (!['running', 'queued'].includes(job.status)) throw new Error('Backend job returned an unknown status');
      await pause(250, undefined, { signal: combined });
    }
  } catch (error) {
    if (combined.aborted) {
      // Only cancel the job returned for this invocation. An aborted caller's
      // signal must not also abort the cleanup request.
      try { await api('/api/jobs/' + encodeURIComponent(jobId), { method: 'DELETE' }, AbortSignal.timeout(5000)); }
      catch { /* Keep the original abort visible; the server's own budget remains active. */ }
    }
    throw error;
  }
}

const directFields = {
  execution_capabilities:[], get_capabilities:['model_id'],
  build_model:['request','definition','definition_path','design_id','continuation_token','research_intent_id','parameters','ticks','dt','seed','seeds','data_bindings','last_run'],
  design_model:['request','design_id','continuation_token','revise_from','revise_proposal','research_intent_id','parameters','ticks','dt','seed','seeds','data_bindings','last_run'],
  validate_model:['definition','definition_path','design_id','continuation_token','research_intent_id','parameters','ticks','dt','seed','seeds','data_bindings','last_run'], research_status:['study_id'], import_collection:['collection_id','role'],
  analyze_data:['dataset_id','path'], reviewed_run:['model_id','design_id','parameters','ticks','dt','seed','data_bindings','allow_partial'],
  report_run:['run_id','primary_metric','experiment_id','analysis_id'], explain:['request','last_run','history'],
  research_model_context:['research_intent_id','evidence']
};
const aliases = { guide: 'modeling_guide', run: 'run', run_preset: 'run_preset', report_docx: 'research_report',
  ...Object.fromEntries(Object.keys(directFields).map(name=>[name,name])) };
const actions = ['guide', 'health', 'list_models', 'contract', 'sources', 'presets', 'tasks', 'schema', 'execute',
  'run', 'run_preset', 'report_docx', 'design_details', ...Object.keys(directFields), 'agent_hint'];
const discoveryPrompt = [
  '建模pending直接执行next_action；有continuation_token时只传回凭据和方案编号，平台恢复原文/真实数据/运行设置，不重填几十个参数。获审后用同号build_model自动编译。自拟参数调整用revise_from与revise_proposal=true重新审核，原话固定值与MI保持。',
  '已知公开数据文件URL直接用schema(collect_data)，再execute调用collect_data(url,format,parse_options)，返回实际DS数据集。无标题/分隔符/ZIP成员按源字典显式声明。collect_source只用其schema枚举连接器，不能猜http或__list__；无需查平台源码寻找采集入口。',
  '用户原话由宿主自动传给 guide、reviewed_run 与建模工具。调用 guide 和 reviewed_run 时省略 request，直接用原话与真实工具回执推进。',
  '获批方案若带plan_omitted，先用plan_access的design_details读取完整方案。可按section及field分段，数组沿next_offset读取至null；函数路径、全部验收条件和原运行设置都须读全再编写definition。不必搜索磁盘或阅读平台源码猜合同。',
  '新仿真先用 dayan({action:"guide"}) 获取计算能力与数据合同。可自建时优先采用 invocation_examples.custom_model；有明确指定型号或专用求解能力时按适配合同执行。询问总体能力用 execution_capabilities，get_capabilities不填model_id也返回总体能力；指定model_id才查询该型号。模型合同用 dayan({action:"schema",tool:"build_model"})，包含DSL及kind=program；program_engine.eligible为真时可按需求自主实现不同人口池、动态图、连续/事件算法，不能把旧DSL限制当成全部系统能力。',
];
const executionPrompt = [
  '尚无获批design_id时，先完成原文要求的数据采集与绑定，再调用design_model；思路、缺陷审查、修订和方案由该工具实际完成。取得approved及完整plan后才编写definition或调用build_model自动编译。不要为了开始设计而扫描平台各层源码或猜内部校验实现；工具schema/guide/完整方案就是公开合同。只有工具错误无法由合同解释时才按故障维护处理。',
  '新模型以 guide.invocation_examples.custom_model 启动。action=build_model 启动思路、审查、构建与运行，省略 request 和 definition。适配的原生模型走 reviewed_run。',
  '规模先查 guide.execution_scale。准确保留用户的主体数、网格尺寸、步数及逐步导出的要求。大规模优先用列式执行，依据执行回执的 scale 和原始运行包交付。明确人数时画面抽样不影响实际计算或完整状态。',
  '本轮先依据完整原话独立提出建模思路。历史研究由平台在思路形成后的审查阶段提供参考，按本轮要求决定取舍。明确要求沿用时提供真实 last_run.run_id。',
  '科研与政策建模会在独立构思后在线搜索和阅读中英文期刊及 arXiv。以 literature_summary 核对实际读到的篇数和类型。复杂研究可先 design_model，随后按 next_action 构建。',
  '建模研究、编译和语义复核按阶段持久化。status=pending 表示请求尚未完成；多种子任务的 completed_runs 是已实际归档成员，仍须完成余下成员。新建DSL的 solver_progress 是已保存的实际计算步/时刻，按原终点续算。必须继续 payload.next_action，保留同一 design_id、原文与运行设置。暂时网络错误同样续接；已有归档会复用，不能另建缩减方案。',
  'pending回执里的草稿校验错误是下一次调用的定向修复依据。先按同一next_action续接，不另写无关probe、不切换小模型。方案blocked或实施revision_required都按回执design_model(revise_from)修订，保留同一研究MI、原文、数据和阈值；旧否决保留，有效阶段复用。未批准不能构建，也不需要另建研究绕开否决。',
  '方案 approved 后继续执行 payload.next_action 构建或运行。需要 Agent 自行编写规约时，才先用 validate_model 校验。单次模型以实际run_id和数值验收为准；科研任务还须完成同号MS校准、所选参数的实际结果运行与research_report。',
  '自行编写含多行Python的完整定义时，先用JSON序列化保存为当前项目内的.json文件，再调用dayan({action:"validate_model",definition_path:"definition.json",design_id:"真实获批ID",...原运行选项})，通过后用相同文件与选项build_model。路径相对会话目录；宿主只读取JSON，不执行文件。保留原方案函数名、变量含义和检查，不在工具参数手抄巨型源码或用Python None/True/False替代JSON。definition_path、definition、request互斥，原始需求仍由宿主独立绑定，所有预检/语义审查/实际验收照常执行。',
  '若预检返回 revision_required，使用 next_action 的 design_model(revise_from)对实际缺陷定向修订，保留原文和运行设置。已验证的研究阶段会复用，新方案须独立复核。不要改变量含义、添加零乘状态或删掉原文检查来迎合错误方案，也不要修改平台源码或方案文件绕过检查。',
  '有适配原生模型的对照、种子重复和参数变更使用 guide.next_tools.study_workflow。新建模型的种子重复和时点干预由 build_model 处理。保留原话的机制、数据、参数与单位。原文明示接受子范围时可传 allow_partial=true。',
  '复杂参数（研究准备、目标绑定、诊断、多行定义）用JSON序列化保存项目内文件{"tool":"实际工具名","arguments":{完整参数}}，再dayan({action:"execute",tool:"同一工具名",arguments_path:"parameters.json"})。不混用inline arguments或其他顶层参数；宿主只读JSON，完整后台校验保留。原生research_model_prepare的question可省略，后台会逐字绑定当前真实用户原文，不必重抄长问题。参数较小时inline arguments仍可用。',
  '固定局部网格可用 agents.grid。使用能力卡和实际符号范围，排查模型规模、时钟、拓扑与输入端口。当前方案不够时说明具体缺口，保留完整任务。'
];
const deliveryPrompt = [
  '入模的真实数据走采集、导入、字段口径核对、data_bindings。已绑定字段由数据确定实参。',
  '单次运行的场景、结果及 Word 使用同一个已验收 run_id。execution.delivery给实际回放状态API、工作台URL和恢复控制器，模型不必重写界面。科研回放必须使用research_finalize真正所选参数的run_id，Word用同study_id的research_report；普通模型用report_run(run_id)。'
];
const implementationPrompt = [
  '建模优先闭合数学与因果链：状态/参数/输入/动作/观测分别定义单位、初边界和更新顺序，真实数据与机制进入实际方程。区分用户硬约束、数学不变量、随机结果和运行后交付；不强迫正效应、伤亡人数或漂亮结论。DSL与program只应用各自实际合同。',
  '自主实现只维护一份权威提交定义。修改独立.py源码后必须读取最新版并JSON序列化更新definition.source，重新读取最终JSON核对本次实际代码，再用同文件同版本validate_model/build_model；有修改就重新预检。已有自写定义时不要切回默认编译生成第二份实现；长参数用当前schema的definition_path/arguments_path。',
  '实际否决要拆成逐条缺陷与反例，核对代码中的每个相关分支、状态保存、边界、指标和帧；原编号内有多项也逐项处理。只改说明、加未调用函数、把残差置零、声称resolved或修改未提交的草稿都不算修复。逐条核对本次提交源码后沿真实next_action修订/续接，不重复提交未改定义或重做已完成阶段。',
  '持久状态不能在每个advance重置；瞬时/累计/峰值指标按各自定义计算；假零诊断和自我相减不算独立验证。初始化覆盖完整实际人数，所有轴/层/孔洞/出口的边界在计算、validate和frame一致；动作意图与身体姿态分开，空间与图表读取真实状态。',
  '看当前实际源码和合同处理审核：指出具体函数/式子/失败条件，不照搬旧版错误或自行加论文篇数、额外规模、显著性门槛。决策时点、同一时点的多个batch、API尝试和动作人数分别计数。已执行和未执行如实区分；用户明确只改提示词/发布或停止运行时，不启动仿真、测试或全链验收。'
];
const modelWorkflow = [...implementationPrompt, ...discoveryPrompt, ...executionPrompt, ...deliveryPrompt].join('\n');
const hint = [
  modelWorkflow,
  '保留原始用户问题、地区、指标口径、时期、模型机制和分组；未能覆盖必须说明缺口，不能替换为中国人口或默认模型。',
  'schema列出全部平台工具及真实参数。execute的tool和arguments按schema传。DSH自身负责理解和调用；不要调用第二套agent接口。',
  '数据研究：collect_source/run_preset → collection_status（partial用相同ID续采）→ research_create（显式family/grid/tolerance/holdout）→ research_calibrate（返回新的study_id和run_id）→ research_report（只用新ID）。',
  '当前单变量研究适配器支持已核验WB国家年度指标的linear/exponential/logistic描述性趋势；不覆盖的机制须build_model或选择精确合同模型，不能将趋势拟合当政策因果。',
  '已有当前版本、通过完整审查和数值验收的自建模型run_id，可用schema(research_model_create)建立MS研究，明确真实目标数据映射、三分区、参数网格、重复种子、误差阈值和诊断。research_calibrate的MS沿同一study_id和next_action续接；research_report只用该ID。ST趋势研究才返回新ID。创建研究、基线运行成功均不表示校准通过。',
  '新原文同时要求自主建模、真实数据校准或独立验证时，先真实采集目标DS并读schema(research_model_prepare)。该工具冻结完整原文、目标观测/单位、时钟、三分区、输入、参数网格、种子、阈值和诊断，返回MI及next_action。设计/预检/修订/构建每次保持同一research_intent_id；基线仅为中间态，status=research_pending仍须继续research_calibrate至实际完成，再按next_action用research_finalize实际运行所选参数，取得大屏结果run_id后research_report。只有同号研究报告完成才交付整题；不能删校准要求或用基线report_run冒充。可用research_status(study_id=MI编号)恢复阶段。',
  '研究诊断按schema的oneOf填写：time_refinement.dynamics为deterministic或ensemble_moments，不能填population等观测名。随机矩模式须至少两个seed和max_scaled_mc_se。消融rule_refs为真实rates/agents.update/source路径，不能填裸函数名；准备先查结构/时钟/单位，模型生成后仍查真实参数范围和实现。',
  '指标定义、计量单位、方法和许可等来源文字先真实collect_data（可为background/source_snapshot），再读schema(research_model_context)，按同MI附加实际DS的JSON Pointer引用。它保持原输入/网格/阈值/划分/seed，自动核原文/hash并将文字给审查及同源报告/复核包；不是数值data_bindings，不需要为文字把简单模型改成program。方案被否决后可追加证据，按同MI的revise_from再独立审查；已开始运行/求值不能事后静默补证据。',
  '其他真实来源：collect_source可用huggingface_datasets/ckan_search发现目录，huggingface_file(repo_id,filename)/ckan_resource(instance,resource_id)真正下载，import_collection得到dataset_id；analyze_data后用run.data_bindings显式映射真实参数。目录/网页不算数值模型输入。',
  'run支持dt/interventions/data_bindings。experiment/ensemble/sweep/compare/resume均通过execute可用。',
  '独立提出建模思路后平台会检索本项目成功、真实失败与用户纠正，并在必要时比较跨措辞的机制语义，只供缺陷审查参考。用户纠正以前的模型时用execute(memory_feedback,{design_id或run_id})保存；真实原话由宿主绑定，不用Agent概括冒充用户指令。历史参考不能覆盖当前需求，删除/清空仍控制可见性。',
  '要扩大规模时，在真实获审基线后调用schema(plan_capacity)，实际测量两档探针并实跑目标档，按capacity_id续接。用实际耗时/CPU/峰值RSS/归档/LLM成本做建议；固定人数和正式时钟不自动改。自由规模的建议须经同原文design_model修订审查后采用，不能把探针当正式结论或假称最大容量。',
  '任意当前版本已审且实际验收通过的自建模型可用schema(global_sensitivity)，给baseline_run_id、独立参数distributions、实际metric、二次幂n和配对seeds。pending按同analysis_id续接直到全部真实求值；报告传其run_id及analysis_id。一阶/总效应和区间来自样本，常数输出标未定义，不强迫正效应，不改原科研冻结。',
  '原始用户文本由DSH会话直接送到合同检查，不能改写研究问题绕过约束。总结只引用实测变化与产物，不添加未核实的趋势加速/因果解释。研究的interpretation是按真实观测减模型预测计算的方向事实，直接遵从其中interpretation_text；不能把模型下降过快说成实际下降更快。',
  '校准执行成功与validation_pass分开；训练通过而留出失败必须如实报告，不事后放宽阈值，不将网格唯一最优称为可识别。',
  '报告用实际 run_id 或 study_id 返回下载地址。运行/研究结果按当前原生会话同步工作台。'
].join('\n');

const toolResultBytes = 42000;
const resultSize = value => Buffer.byteLength(JSON.stringify(value), 'utf8');

function boundedResult(value) {
  let run = value.payload;
  const workflow = run ? Object.fromEntries(['status','request_complete','execution_complete','research_intent_id','study_id','next_action']
    .filter(key=>run[key]!==undefined).map(key=>[key,run[key]])) : {};
  if (run?.status === 'pending' && run.next_action) {
    const draftError = run.llm_calls?.findLast(call => call.design_validation_error)?.design_validation_error;
    run = { ...run, continuation_note: '尚未完成，沿同一 next_action 继续保存的阶段。' +
      (draftError ? '草稿校验失败已保存，下一次将定向修复；不是最终语义否决，不改换任务或提交无关探针。' : ''),
      ...(draftError ? { pending_draft_error: draftError } : {}) };
    value = { ...value, payload: run };
  }
  if (run?.next_action) value = { next_action: run.next_action, ...value };
  if (value.ok && run?.run_id && Array.isArray(run.observations) && run.observations.length) {
    const { run_id, model_id, state_url, data_url, bundle_url, scale, observations, manifest } = run;
    value = { run_receipt: { run_id, model_id, state_url, data_url, bundle_url, scale: scale || manifest?.scale,
      first_observation: observations[0],
      final_observation: observations.at(-1), observation_count: observations.length,
      verification: manifest?.scenario_review?.runtime_checks?.verification?.status,
      ...(manifest?.actor_decisions ? {actor_decisions:Object.fromEntries(
        ['real_call_count','action_count','batch_count','replay_boundaries'].map(key=>[key,manifest.actor_decisions[key]]))} : {}) }, ...value };
  }
  if (resultSize(value) <= toolResultBytes) return value;
  if (run?.design_id && ['approved', 'pending', 'blocked', 'revision_required'].includes(run.status)) {
    const { design_id, status, next_action, plan, review, research_memory, literature_summary,
      executed, execution_complete, completed_runs, solver_progress, current_stage, pause_reason, continuation_note, pending_draft_error, last_error } = run;
    const output = {
      ...value, payload: { design_id, status, next_action, plan, review, research_memory, literature_summary,
        executed, execution_complete, completed_runs, solver_progress, current_stage, pause_reason, continuation_note, pending_draft_error, last_error },
      output_note: next_action ? '完整审查记录保存在同号建模方案。可直接执行 next_action。'
        : '未通过的完整审查记录保存在同号建模方案。',
    };
    if (resultSize(output) > toolResultBytes) {
      output.payload = { design_id, status, next_action, research_memory, literature_summary,
        executed, execution_complete, completed_runs, solver_progress, current_stage, pause_reason, continuation_note, pending_draft_error, last_error, review_issues: review?.issues?.slice(0, 5) };
      if (plan) {
        output.payload.plan_omitted = true;
        output.payload.plan_access = { action: 'design_details', design_id, section: 'plan' };
        output.output_note = '完整方案超过单次摘要长度。自行编写模型前须按plan_access读取全部方案，不能凭已批准状态猜测函数或验收条件。自动build_model仍读取同号完整方案。';
      }
    }
    return output;
  }
  if (value.run_receipt) {
    const { run_id, model_id, state_url, data_url, bundle_url, scale, design_id, warnings, research_memory, memory_index, literature_summary } = run;
    return { ...value,
      payload: { run_id, model_id, state_url, data_url, bundle_url, scale, design_id, warnings, research_memory, memory_index, literature_summary, ...workflow },
      output_note: '首末观测保留在 run_receipt，完整状态和观测与 run_id 同源。' };
  }
  if (value.ok && Array.isArray(run?.runs) && run.runs.length && run.runs.every(entry => typeof entry?.run_id === 'string')) {
    const { model_id, design_id, analysis_id, experiment_id, result_kind, seeds, data_url, research_memory, memory_index, literature_summary } = run;
    const output = {
      ...value, payload: { model_id, design_id, analysis_id, experiment_id, result_kind, seeds, data_url, research_memory, memory_index, literature_summary, ...workflow,
        runs: run.runs.map(({ run_id, seed, arm, value, state_url, final, observations, manifest }) => ({
          run_id, seed, arm, value, state_url,
          first_observation: observations?.[0],
          final_observation: observations?.at(-1) || final,
          scale: manifest?.scale,
          interventions: manifest?.interventions,
          verification: manifest?.scenario_review?.runtime_checks?.verification?.status,
        })),
      },
      output_note: '批次完整数据已归档。用 data_url 下载，或将各 run_id 传给 report_run 生成同源报告。',
    };
    if (resultSize(output) > toolResultBytes) {
      output.payload.runs = output.payload.runs.map(({run_id, seed, arm, value, state_url, verification, scale}) =>
        ({run_id, seed, arm, value, state_url, verification, scale}));
    }
    return output;
  }
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

const nativeArgumentsSubmission = {
  action: 'execute', field: 'arguments_path', format: 'UTF-8 JSON',
  invocation: { action: 'execute', tool: '实际平台工具名', arguments_path: 'parameters.json' },
  file_shape: { tool: '与execute.tool一致', arguments: {} },
  scope: '项目内普通.json文件，路径相对当前DSH会话目录；与inline arguments及其他顶层参数互斥',
  contract: '用JSON序列化保存完整参数。宿主只读取并核工具名，记录原字节hash；全部后台schema、原文/会话绑定、研究与执行校验照常。不是结果或模型注入通道。'
};

export function dayanToolDefinition({ profileDir } = {}) {
  const approvedDesigns = new WeakMap();
  return {
    name: 'dayan', description: '大衍社会仿真与真实数据研究工具。自然语言仿真先用 action=guide，再按返回的参数用 execute。\n' + modelWorkflow,
    parameters: { type: 'object', additionalProperties: false, required: ['action'], properties: {
      action: { type: 'string', enum: actions }, tool: { type: 'string', description: 'schema可按此名称过滤；execute必须提供平台工具名' },
      arguments: { type: 'object', description: 'execute参数严格按schema；保留原始问题和全部约束' },
      arguments_path: { type: 'string', description: '复杂参数用action=execute、tool和此路径提交；项目内UTF-8 JSON文件内容为{"tool":"同一工具名","arguments":{完整参数}}。相对当前会话目录，与inline arguments及其他顶层参数互斥。先JSON序列化写文件，宿主只读取不执行，后台全部校验保留。' },
      theme: { type: 'string' }, model_id: { type: 'string' }, study_id: { type: 'string' },
      run_id: { type: 'string', description: '已保存运行的编号，用于 report_run 或 report_docx' }, primary_metric: { type: 'string' },
      design_id: { type: 'string', description: 'design_model 返回的已审查方案编号，与原话及执行设置绑定' },
      continuation_token: { type: 'string', description: 'next_action返回的只读续接凭据；原样传回，平台恢复原文/会话/真实数据/运行设置，不重填参数' },
      experiment_id: { type: 'string', description: 'report_run整组报告使用实际experiment_id或analysis_id（二选一），run_id指定同组场景成员' },
      analysis_id: { type: 'string', description: 'report_run读取实际分析组全部成员；与experiment_id二选一' },
      section: { type: 'string', enum: ['plan','execution','review','request'], description: 'design_details读取同会话方案的部分；默认plan' },
      field: { type: 'string', description: 'design_details中section的一个实际字段；无field时返回完整section或字段目录' },
      offset: { type: 'integer', minimum: 0, description: 'design_details数组分段的起点，沿返回next_offset续读' },
      limit: { type: 'integer', minimum: 1, maximum: 64, description: 'design_details数组分段最多条数，默认8；不会以摘要替代未读条目' },
      revise_from: { type: 'string', description: '实际预检失败回执提供的原方案ID；design_model据此定向修订并重新审查' },
      revise_proposal: { type: 'boolean', description: '与revise_from一起显式修订Agent自拟设置并重新审核；原文固定值和MI科研协议保持' },
      research_intent_id: { type: 'string', description: 'research_model_prepare实际返回的MI编号；设计、修订、预检、构建及next_action全程保留，基线并非完整研究交付' },
      evidence: { type: 'array', items: { type: 'object' }, description: 'research_model_context的真实来源DS引用；先读schema，含id/dataset_id/purpose/applies_to/basis/fields(JSON Pointer)' },
      definition: { type: 'object', description: 'Agent 自行编写的完整模型定义（DSL 或 kind=program）；先读 schema(build_model)，与同一 design_id 预检和构建' },
      definition_path: { type: 'string', description: 'DSH原生文件提交：当前项目内的完整JSON定义，相对会话目录。与definition/request互斥；适合含多行Python的program。先validate_model，再同文件/方案build_model。宿主只读文件，后台仍完整审查。' },
      request: {type:'string'}, last_run: {type:'object'}, history: {type:'array'},
      collection_id: {type:'string'}, dataset_id: {type:'string'}, path: {type:'string'}, role: {type:'string'},
      allow_partial: {type:'boolean'},
      ticks: { type: 'integer', minimum: 0, maximum: 10000 }, dt: { type: 'number', exclusiveMinimum: 0 }, seed: { type: 'integer' },
      seeds: { type: 'array', minItems: 1, items: { type: 'integer' } },
      parameters: { type: 'object' }, interventions: { type: 'array', items: { type: 'object' } }, data_bindings: { type: 'array', items: { type: 'object' } },
      preset_id: { type: 'string' }, values: { type: 'object' }, page_budget: { type: 'integer', minimum: 1, maximum: 50 },
      report: { type: 'string', enum: ['academic','B_academic','policy','data_quality'] }
    } },
    output: { schema: { type: 'object', additionalProperties: false, required: ['json'], properties: { json: { type: 'string' } } },
      render: (_args, value) => [{ type: 'text', text: value.json }] }, timeoutMs: Math.max(300000, authoringTimeoutMs(90)),
    async execute(args, exec = {}) {
      try {
        exec.signal?.throwIfAborted();
        if (Object.hasOwn(args, 'arguments_path') && args.action !== 'execute')
          throw new Error('arguments_path只用于action=execute；文件中保存同一tool及完整arguments');
        let result;
        if (args.action === 'health') result = await ensureBackend();
        else if (args.action === 'agent_hint') result = { ok: true, workflow: hint };
        else if (args.action === 'design_details') {
          const sessionId = exec.agent?.session?.id, section = args.section || 'plan';
          if (!sessionId || !/^MD-[a-f0-9]{32}$/.test(args.design_id || '')) throw new Error('读取方案须使用本会话真实design_id');
          if (!['plan','execution','review','request'].includes(section)) throw new Error('未知方案section');
          const record = await api('/api/model-designs/'+encodeURIComponent(args.design_id)+'?session_id='+encodeURIComponent(sessionId), {}, exec.signal);
          if (record.design_id !== args.design_id || record.session_id !== sessionId) throw new Error('方案不属于当前会话');
          const source = record[section];
          if (source === undefined) throw new Error('当前方案尚未产生'+section+'，请继续原next_action');
          const base = { ok:true, design_id:record.design_id, status:record.status, section, plan_sha256:record.plan_sha256 };
          if (args.field === undefined && resultSize(source)>toolResultBytes && source && typeof source==='object' && !Array.isArray(source)) {
            return { json:JSON.stringify({...base,complete:false,fields:Object.keys(source),
              instruction:'按field逐项读取；数组沿next_offset读至null。完整字段不会被静默截断。'}) };
          }
          if (args.field !== undefined && (!source || typeof source!=='object' || !Object.hasOwn(source,args.field))) throw new Error('该section没有此字段');
          const value = args.field === undefined ? source : source[args.field];
          if (Array.isArray(value)) {
            const offset=args.offset??0,limit=args.limit??8;
            if (!Number.isInteger(offset)||offset<0||offset>value.length||!Number.isInteger(limit)||limit<1||limit>64) throw new Error('方案分段offset/limit超出实际范围');
            const items=[];
            for (const item of value.slice(offset,offset+limit)) {
              if (items.length && resultSize([...items,item])>toolResultBytes) break;
              items.push(item);
            }
            const next=offset+items.length;
            result={...base,field:args.field,value:items,offset,total:value.length,next_offset:next<value.length?next:null,complete:offset===0&&next===value.length};
          } else result={...base,field:args.field,value,complete:true};
          return { json:JSON.stringify(result) };
        }
        else if (args.action === 'schema') {
          const manifest = await api('/api/agent/tools', {}, exec.signal);
          const name = args.tool === 'report_docx' ? ['report_run','research_report'] : [aliases[args.tool] || args.tool];
          if (args.tool === 'execute') {
            result = { ok: true, action: 'execute', arguments_shape: {action:'execute',tool:'实际平台工具名',arguments:{}},
              native_arguments_submission: nativeArgumentsSubmission,
              tools: manifest.tools.map(tool => tool.name) };
            return { json: JSON.stringify(result) };
          }
          const tools = args.tool ? manifest.tools.filter(t => name.includes(t.name)) : manifest.tools;
          result = args.tool && !tools.length
            ? { ok: false, error: '未找到该工具。可以调用 schema 查看平台当前支持的工具。' }
            : { ok: true, tools, native_arguments_submission: nativeArgumentsSubmission,
              native_session_binding: { original_text: '由宿主绑定当前真实用户消息，文件或arguments不能替换它',
                research_model_prepare: { question: '在DSH原生arguments中可省略，由后台protect逐字绑定真实原文；独立HTTP schema仍要求question。无需在巨型工具JSON中重抄原文。' } },
              ...(!args.tool || ['build_model','validate_model'].includes(args.tool) ? {
              native_file_submission: { actions: ['validate_model','build_model'], field: 'definition_path',
                format: 'UTF-8 JSON', scope: '项目内文件，路径相对DSH会话目录；与definition/request互斥',
                contract: '仅DSH桥接层支持此路径，读取后按上面的真实API schema传definition；design_id与全部原运行设置仍须保留。' }
            } : {}) };
        } else if (args.action === 'list_models') result = await api('/api/models/search?theme='+encodeURIComponent(args.theme || ''), {}, exec.signal);
        else if (args.action === 'contract') result = await api('/api/models/contract/'+encodeURIComponent(args.model_id || ''), {}, exec.signal);
        else if (args.action === 'sources') result = await api('/api/collection/sources'+(args.theme ? '?theme='+encodeURIComponent(args.theme) : ''), {}, exec.signal);
        else if (args.action === 'presets') result = await api('/api/collection/presets', {}, exec.signal);
        else if (args.action === 'tasks') result = await api('/api/collection/tasks', {}, exec.signal);
        else {
          const tool = args.action === 'execute' ? args.tool : args.action === 'report_docx' && args.run_id
            ? 'report_run' : aliases[args.action];
          if (!tool) throw new Error('缺少有效动作或工具名。先用 action=guide 获取当前任务合同');
          let parameters = args.arguments;
          if (args.action === 'run') parameters = Object.fromEntries(['model_id','ticks','dt','seed','parameters','interventions','data_bindings'].filter(k => args[k] !== undefined).map(k => [k,args[k]]));
          if (args.action === 'run_preset') parameters = { preset_id: args.preset_id, values: args.values || {}, page_budget: args.page_budget ?? 2 };
          if (args.action === 'report_docx') parameters = args.run_id
            ? {run_id:args.run_id, ...(args.primary_metric ? {primary_metric:args.primary_metric} : {})}
            : { study_id: args.study_id, kind: args.report === 'B_academic' ? 'academic' : args.report || 'academic' };
          if (args.action === 'guide') parameters = {};
          if (directFields[args.action] && parameters === undefined) parameters = Object.fromEntries(
            directFields[args.action].filter(key=>args[key]!==undefined).map(key=>[key,args[key]])
          );
          const session = exec.agent?.session;
          const sessionId = session?.id;
          const user = session?.snapshotEvents?.().filter(e => e.type === 'user/message' && e.data?.source?.kind === 'user').at(-1);
          const userContent = user?.data?.content || user?.data?.message?.content || [];
          const originalText = userContent.filter(b => b.type === 'text').map(b => b.text).join('\n');
          const cwd = session?.header?.cwd;
          let submittedArgumentsFile;
          if (Object.hasOwn(args, 'arguments_path')) {
            if (Object.keys(args).some(key => !['action','tool','arguments_path'].includes(key)))
              throw new Error('arguments_path不能混用inline arguments或其他顶层参数；完整参数只放同一JSON文件');
            const loaded = await readToolArguments(args.arguments_path, { projectRoot: PROJECT_ROOT, cwd }, tool);
            parameters = loaded.arguments;
            submittedArgumentsFile = loaded.receipt;
          }
          if (!parameters || typeof parameters !== 'object' || Array.isArray(parameters)) throw new Error('execute needs arguments object or arguments_path');
          if (tool === 'run' && (typeof parameters.model_id !== 'string' || !parameters.model_id.trim()))
            throw new Error('run(model_id) 启动新仿真。已完成运行使用构建回执和状态包，生成报告请传 report_run(run_id)。');
          let submittedFile;
          if (Object.hasOwn(parameters, 'definition_path')) {
            if (!['validate_model','build_model'].includes(tool)) throw new Error('definition_path 只用于 validate_model/build_model');
            if (parameters.definition != null || parameters.request != null)
              throw new Error('definition_path、definition、request只能提供一种；原文由DSH会话独立绑定');
            const loaded = await readModelDefinition(parameters.definition_path, { projectRoot: PROJECT_ROOT, cwd });
            parameters = { ...parameters, definition: loaded.definition };
            delete parameters.definition_path;
            delete parameters.request;
            submittedFile = loaded.receipt;
          }
          const researchScope = sessionId && profileDir && cwd && isAbsolute(cwd) &&
            ['build_model', 'design_model', 'validate_model'].includes(tool) ? projectScopeKey(profileDir, cwd) : undefined;
          const hasUserTurn = sessionId && originalText && Number.isInteger(user?.seq);
          const previous = hasUserTurn ? approvedDesigns.get(session) : undefined;
          // This shortcut only fills omitted options. The backend still verifies the complete design binding.
          if (tool === 'build_model' && previous && previous.sessionId === sessionId && previous.seq === user.seq &&
              previous.originalText === originalText &&
              !['design_id', 'definition', 'request'].some(key => Object.hasOwn(parameters, key)) &&
              Object.entries(parameters).every(([key, value]) => isDeepStrictEqual(value, previous.arguments[key]))) {
            parameters = previous.arguments;
          }
          const submittedParameters=parameters;
          const turnContext={sessionId,seq:user?.seq,originalText};
          const continuation=tool==='design_model'&&hasUserTurn?recoverPendingDesign(session,turnContext,parameters):null;
          if(continuation)parameters=continuation.arguments;
          result = await api('/api/tools/'+encodeURIComponent(tool), { method: 'POST', body: JSON.stringify({ async_job: true, arguments: parameters,
            ...(sessionId ? { origin: 'dsh', session_id: sessionId, original_text: originalText } : {}) }) }, exec.signal, researchScope);
          if (result?.job_id && !Object.hasOwn(result, 'ok')) result = await waitForPlatformJob(result.job_id, exec.signal);
          if(tool==='design_model'&&hasUserTurn)rememberPendingDesign(session,turnContext,submittedParameters,result);
          if(continuation?.receipt)result={...result,continuation_recovery:continuation.receipt};
          if (submittedFile) result = { ...result, definition_file: submittedFile };
          if (submittedArgumentsFile) result = { ...result, arguments_file: submittedArgumentsFile };
          if (tool === 'design_model' && hasUserTurn && result.ok) {
            const { status, request, design_id, next_action } = result.payload || {};
            if (status === 'approved' && request === originalText && typeof design_id === 'string' &&
                next_action?.action === 'build_model' && next_action.arguments?.design_id === design_id) {
              approvedDesigns.set(session, { sessionId, seq: user.seq, originalText, arguments: next_action.arguments });
            }
          }
        }
        return { json: JSON.stringify(boundedResult(result)) };
      } catch (error) { return { json: JSON.stringify({ ok: false, error: String(error?.message || error),
        ...(typeof error?.cause?.code === 'string' ? { transport_error_code: error.cause.code } : {}) }) }; }
    }
  };
}

export function registerDayanTool(ctx) {
  ctx.inject(['tools'], scope => {
    const off = scope.tools.register(dayanToolDefinition({ profileDir: ctx.get('profileContext')?.dir }));
    if (typeof off === 'function') scope.effect(() => off, 'dayan: shared platform tool');
  });
}

export function registerDayanContext(ctx) {
  const root = resolve(PROJECT_ROOT);
  function inProject(cwd) {
    if (!cwd) return false;
    const path = relative(root, cwd);
    return path !== '..' && !path.startsWith('..' + sep) && !isAbsolute(path);
  }

  ctx.inject(['systemPrompt', 'workingDirectory'], scope => {
    scope.systemPrompt.context({
      name: 'dayan:project-workflow',
      order: scope.systemPrompt.getContextOrder('WORKING_DIRECTORY') + 1,
      required: true,
      interpolate: false,
      text: ({ agent }) => {
        if (!agent?.session) return '';
        const session = agent.session;
        return inProject(session.header?.cwd) || inProject(scope.workingDirectory.get(session))
          ? modelWorkflow : '';
      }
    });
  });
}

export async function stopManagedBackend() {
  if (!backendChild || backendChild.exitCode !== null) return { stopped: false };
  const child = backendChild, pid = child.pid;
  const ended = new Promise(resolve => child.once('exit', resolve));
  child.kill();
  await Promise.race([ended, new Promise(r => setTimeout(r, 5000))]);
  return { stopped: child.exitCode !== null || child.signalCode !== null, pid };
}
