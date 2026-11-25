/** Synthetic SDK context, REAL Python service/auth/queue/model/archive. */
import test from 'node:test';
import assert from 'node:assert/strict';
import { spawn } from 'node:child_process';
import { createServer } from 'node:net';
import { mkdtemp, readFile, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { createHmac } from 'node:crypto';
import { join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const sourceEvidenceBridgeTest = async () => {
  const { dayanToolDefinition } = await import('../plugins/dayan/host/tools.js');
  const bridge = dayanToolDefinition();
  const original = '完整研究需求：数据口径引用已采集原件，保持原参数和检验标准。';
  const mi = 'MI-' + 'c'.repeat(24), md = 'MD-' + 'e'.repeat(32), contextId = 'a'.repeat(64);
  const session = { id:'controlled-source-owner', snapshotEvents:()=>[
    {type:'user/message',seq:8,data:{source:{kind:'user'},content:[{type:'text',text:original}]}}
  ] };
  const args = {research_intent_id:mi,evidence:[{id:'definition',dataset_id:'DS-'+'d'.repeat(24),
    purpose:'definition',applies_to:['population'],basis:'明确标记的协议测试',fields:{definition:'/1/0/sourceNote'}}]};
  const next = {action:'design_model',arguments:{request:original,research_intent_id:mi,revise_from:md}};
  const previousFetch=globalThis.fetch, previousToken=process.env.DAYAN_ACCESS_TOKEN;
  const requests=[];
  process.env.DAYAN_ACCESS_TOKEN='controlled-source-token'.repeat(4);
  globalThis.fetch=async(url,init)=>{
    if(new URL(url).pathname==='/api/health')return Response.json({service:'dayan',contract_version:'research-integrity-1'});
    requests.push(JSON.parse(init.body));
    return Response.json({ok:true,validation_pass:false,payload:{research_intent_id:mi,status:'awaiting_model',
      source_evidence_id:contextId,source_evidence_count:1,request_complete:false,next_action:next}});
  };
  try {
    const result=JSON.parse((await bridge.execute({action:'execute',tool:'research_model_context',arguments:args},{agent:{session}})).json);
    assert.equal(result.ok,true);assert.equal(result.validation_pass,false);
    assert.equal(result.payload.source_evidence_id,contextId);assert.deepEqual(result.next_action,next);
    assert.deepEqual(requests.at(-1).arguments,args);
    assert.equal(requests.at(-1).original_text,original);assert.equal(requests.at(-1).session_id,session.id);
    assert.ok(!result.run_receipt);
    await bridge.execute({action:'research_model_context',...args},{agent:{session}});
    assert.deepEqual(requests.at(-1).arguments,args);
  } finally {
    globalThis.fetch=previousFetch;
    if(previousToken===undefined)delete process.env.DAYAN_ACCESS_TOKEN;else process.env.DAYAN_ACCESS_TOKEN=previousToken;
  }
};

test('DSH tool bridge authenticates and archives an actual model execution', { timeout: 45000 }, async () => {
  const root = fileURLToPath(new URL('../', import.meta.url));
  const folder = await mkdtemp(join(tmpdir(), 'dayan-bridge-'));
  const server = createServer();
  await new Promise(r => server.listen(0, '127.0.0.1', r));
  const port = server.address().port;
  await new Promise(r => server.close(r));
  process.env.DAYAN_BACKEND_URL = `http://127.0.0.1:${port}`;
  process.env.DAYAN_PROJECT_ROOT = root;
  process.env.DAYAN_DATA_DIR = folder;
  const child = spawn(process.env.DAYAN_PYTHON || 'python', ['-m', 'dayan.server'], {
    cwd: root, windowsHide: true, stdio: 'ignore',
    env: { ...process.env, DAYAN_PORT: String(port), DAYAN_API_KEY: '', DAYAN_BASE_URL: '', DAYAN_MODEL: '' }
  });
  try {
    const base = process.env.DAYAN_BACKEND_URL;
    let health;
    for (let attempt = 0; attempt < 100; attempt++) {
      try { const r = await fetch(base + '/api/health'); if (r.ok) { health = await r.json(); break; } } catch {}
      await new Promise(r => setTimeout(r, 100));
    }
    assert.equal(health?.access_contract, 'loopback-capability-1');
    assert.equal((await fetch(base + '/api/history')).status, 401);
    const { dayanToolDefinition, BACKEND_URL } = await import('../plugins/dayan/host/tools.js');
    assert.equal(BACKEND_URL, base, 'bridge must be imported after the test configures its isolated backend');
    const text = '运行NET052，运行3步，种子7';
    const sdkContextFixture = { agent: { session: { id: 'unit-sdk-context', snapshotEvents: () => [
      { type: 'user/message', data: { source: { kind: 'user' }, content: [{ type: 'text', text }] } }
    ] } } };
    const response = await dayanToolDefinition().execute({ action: 'run', model_id: 'NET052', ticks: 3, seed: 7 }, sdkContextFixture);
    const result = JSON.parse(response.json);
    assert.equal(result.ok, true, response.json);
    const run = result.payload;
    assert.equal(run.observations.length, 4);
    assert.equal(run.manifest.rng.seed, 7);
    const record = JSON.parse(await readFile(join(folder, 'research_runs', run.run_id, 'observations.json'), 'utf8'));
    assert.deepEqual(record, run.observations);
    assert.equal((await fetch(base + '/api/history', { headers: { Origin: 'https://evil.example' } })).status, 403);
  } finally {
    child.kill();
    await new Promise(r => child.exitCode !== null ? r() : child.once('exit', r));
    // Only the exact temporary directory created above may be removed.
    assert.ok(resolve(folder).startsWith(resolve(tmpdir()) + (process.platform === 'win32' ? '\\' : '/')));
    assert.ok(folder.includes('dayan-bridge-'));
    await rm(folder, { recursive: true, force: true });
  }
});

test('the native tool retains approved settings only for the same user turn', async () => {
  const { dayanToolDefinition } = await import('../plugins/dayan/host/tools.js');
  const bridge = dayanToolDefinition();
  const { properties } = bridge.parameters;
  assert.equal(properties.design_id.type, 'string');
  assert.equal(properties.definition.type, 'object');
  assert.equal(properties.seeds.items.type, 'integer');

  const originalText = '新建并运行某个模型\n采用种子3和5，其他设置依照方案';
  let seq = 7;
  const session = { id: 'original-session', snapshotEvents: () => [
    { type: 'user/message', seq, data: { source: { kind: 'user' }, content: [
      { type: 'text', text: '新建并运行某个模型' },
      { type: 'text', text: '采用种子3和5，其他设置依照方案' }
    ] } },
    { type: 'user/message', seq: seq + 1, data: { source: { kind: 'agent-instructions' }, content: [] } }
  ] };
  const approved = { design_id: 'MD-approved', ticks: 12, dt: .25, seeds: [3, 5], parameters: { rate: 2 } };
  const runIds = ['R-seed-3', 'R-seed-5'];
  const archivedBatch = {
    model_id: 'USR-batch', analysis_id: 'AN-batch', data_url: '/api/runs/AN-batch/bundle.zip',
    runs: runIds.map((run_id, index) => ({
      run_id, seed: approved.seeds[index],
      observations: [{ sim_t: 0, inventory: 20 }, { sim_t: 1, inventory: 19 }],
      manifest: { model_definition: { description: '超过工具正文传输阈值'.repeat(3500) },
        interventions: [{ requested_t: 1, actual_t: 1, applied: true }] }
    }))
  };
  const requests = [];
  let receivedDesign;
  const fetchBefore = globalThis.fetch;
  const tokenBefore = process.env.DAYAN_ACCESS_TOKEN;
  process.env.DAYAN_ACCESS_TOKEN = 'test-token'.repeat(4);
  globalThis.fetch = async (url, init) => {
    const path = new URL(url).pathname;
    if (path === '/api/health') return Response.json({ service: 'dayan', contract_version: 'research-integrity-1' });
    const body = JSON.parse(init.body);
    requests.push(body);
    if (path === '/api/tools/design_model') return Response.json({ ok: true, payload: {
      status: 'approved', request: originalText, design_id: approved.design_id,
      plan: { observables: ['inventory'] }, stages: ['超过工具正文传输阈值'.repeat(3500)],
      next_action: { action: 'build_model', arguments: approved }
    } });
    assert.equal(path, '/api/tools/build_model');
    if (body.arguments.design_id === 'MD-compact') return Response.json({ ok: true, payload: archivedBatch });
    return Response.json({ ok: true });
  };
  try {
    const execute = async (args, current = session) => {
      const reply = await bridge.execute(args, { agent: { session: current } });
      const result = JSON.parse(reply.json);
      assert.equal(result.ok, true, reply.json);
      if (args.action === 'design_model') receivedDesign = result;
      return requests.at(-1);
    };
    assert.deepEqual(await execute({ action: 'design_model', seeds: [3, 5] }), {
      async_job: true, arguments: { seeds: [3, 5] }, origin: 'dsh', session_id: session.id, original_text: originalText
    });
    assert.deepEqual(receivedDesign.next_action.arguments, approved);
    assert.deepEqual(receivedDesign.payload.plan.observables, ['inventory']);
    assert.deepEqual((await execute({ action: 'build_model', ticks: 12 })).arguments, approved);
    assert.deepEqual((await execute({ action: 'execute', tool: 'build_model', arguments: {} })).arguments, approved);
    assert.deepEqual((await execute({ action: 'build_model', seeds: [4, 6] })).arguments, { seeds: [4, 6] });
    assert.deepEqual((await execute({ action: 'build_model', definition: { name: 'explicit' } })).arguments,
      { definition: { name: 'explicit' } });
    assert.deepEqual((await execute({ action: 'build_model', design_id: 'MD-other' })).arguments, { design_id: 'MD-other' });
    assert.deepEqual((await execute({ action: 'build_model' }, { ...session, id: 'different-session' })).arguments, {});
    seq += 2;
    const nextTurn = await execute({ action: 'build_model' });
    assert.equal(nextTurn.original_text, originalText);
    assert.deepEqual(nextTurn.arguments, {});
    const compact = await bridge.execute({ action: 'build_model', design_id: 'MD-compact' }, { agent: { session } });
    const batch = JSON.parse(compact.json).payload;
    assert.ok(Buffer.byteLength(compact.json) < 42000);
    assert.deepEqual(batch.runs.map(row => row.run_id), runIds);
    assert.deepEqual(batch.runs.map(row => row.final_observation.inventory), [19, 19]);
    assert.deepEqual(batch.runs.map(row => row.interventions[0].actual_t), [1, 1]);
    assert.equal(batch.data_url, archivedBatch.data_url);

    const { projectScopeKey } = await import('../plugins/dayan/host/session-binding.js');
    const projectRoot = resolve('memory-project');
    const profileDir = resolve('research-profile');
    const scoped = dayanToolDefinition({ profileDir });
    const reply = await scoped.execute({ action: 'design_model' }, {
      agent: { session: { ...session, header: { cwd: projectRoot } } }
    });
    assert.equal(JSON.parse(reply.json).ok, true, reply.json);
    const scopedRequest = requests.at(-1);
    const key = projectScopeKey(profileDir, projectRoot);
    assert.equal(scopedRequest.research_scope, key);
    assert.deepEqual(scopedRequest.arguments, {});
    assert.notEqual(projectScopeKey(profileDir, resolve('other-project')), key);
    assert.notEqual(projectScopeKey(resolve('other-profile'), projectRoot), key);
    const proof = createHmac('sha256', process.env.DAYAN_ACCESS_TOKEN)
      .update(`dayan-research-memory-v1\n${session.id}\n${key}`).digest('hex');
    assert.equal(scopedRequest.research_scope_proof, proof);
  } finally {
    globalThis.fetch = fetchBefore;
    if (tokenBefore === undefined) delete process.env.DAYAN_ACCESS_TOKEN;
    else process.env.DAYAN_ACCESS_TOKEN = tokenBefore;
  }
});

test('pending design keeps its continuation and is never cached as approved', async () => {
  const { dayanToolDefinition } = await import('../plugins/dayan/host/tools.js');
  const bridge = dayanToolDefinition();
  const original = '完整研究需求';
  const session = { id: 'pending-owner', snapshotEvents: () => [
    { type: 'user/message', seq: 5, data: { source: { kind: 'user' }, content: [{ type: 'text', text: original }] } }
  ] };
  const next = { action: 'design_model', arguments: { request: original, design_id: 'MD-pending', ticks: 50 } };
  const requests = [];
  let partialExecution = false;
  let needsRevision = false;
  const oldFetch = globalThis.fetch, oldToken = process.env.DAYAN_ACCESS_TOKEN;
  process.env.DAYAN_ACCESS_TOKEN = 'controlled-token'.repeat(4);
  globalThis.fetch = async (url, init) => {
    if (new URL(url).pathname === '/api/health') return Response.json({ service: 'dayan', contract_version: 'research-integrity-1' });
    const body = JSON.parse(init.body); requests.push(body);
    return Response.json({ ok: !needsRevision, payload: { design_id: 'MD-pending', request: original,
      status: 'pending', executed: false, current_stage: 'review', pause_reason: 'next_stage_budget',
      ...(partialExecution ? { executed: true, execution_complete: false, completed_runs: ['R-accepted-member'],
        solver_progress: { saved_step: 50, saved_time: 5 } } : {}),
      stages: ['checkpoint data'.repeat(5000)], next_action: next,
      llm_calls: [{ design_validation_error: 'source.integrate_segment 缺失' }],
      ...(needsRevision ? { status: 'revision_required', executed: false,
        next_action: { action: 'design_model', arguments: { request: original, revise_from: 'MD-pending', ticks: 50 } } } : {}) } });
  };
  try {
    const first = JSON.parse((await bridge.execute({ action: 'design_model' }, { agent: { session } })).json);
    assert.equal(first.payload.status, 'pending'); assert.equal(first.payload.executed, false);
    assert.equal(first.payload.current_stage, 'review'); assert.deepEqual(first.next_action, next);
    assert.match(first.payload.continuation_note, /定向修复/);
    assert.equal(first.payload.pending_draft_error, 'source.integrate_segment 缺失');
    assert.ok(!first.run_receipt && Buffer.byteLength(JSON.stringify(first)) < 42000);
    await bridge.execute(first.next_action, { agent: { session } });
    assert.deepEqual(requests.at(-1).arguments, next.arguments);
    await bridge.execute({ action: 'build_model' }, { agent: { session } });
    assert.deepEqual(requests.at(-1).arguments, {});
    partialExecution = true;
    const partial = JSON.parse((await bridge.execute({ action: 'build_model' }, { agent: { session } })).json);
    assert.equal(partial.payload.execution_complete, false);
    assert.deepEqual(partial.payload.completed_runs, ['R-accepted-member']);
    assert.deepEqual(partial.payload.solver_progress, { saved_step: 50, saved_time: 5 });
    assert.ok(!partial.run_receipt);
    needsRevision = true;
    const revision = JSON.parse((await bridge.execute({ action: 'validate_model' }, { agent: { session } })).json);
    assert.equal(revision.ok, false); assert.equal(revision.payload.status, 'revision_required');
    assert.equal(revision.next_action.arguments.revise_from, 'MD-pending');
    await bridge.execute({ action: 'design_model', revise_from: 'MD-pending', ticks: 50 }, { agent: { session } });
    assert.deepEqual(requests.at(-1).arguments, { revise_from: 'MD-pending', ticks: 50 });
  } finally {
    globalThis.fetch = oldFetch;
    if (oldToken === undefined) delete process.env.DAYAN_ACCESS_TOKEN; else process.env.DAYAN_ACCESS_TOKEN = oldToken;
  }
});

test('controlled oversized research baseline keeps MI, MS and the real next stage', async () => {
  const { dayanToolDefinition } = await import('../plugins/dayan/host/tools.js');
  const bridge = dayanToolDefinition();
  const original='构建模型并用真实数据校准和独立验证';
  const session={id:'research-stage-owner',snapshotEvents:()=>[
    {type:'user/message',seq:1,data:{source:{kind:'user'},content:[{type:'text',text:original}]}}
  ]};
  const next={action:'research_calibrate',arguments:{study_id:'MS-controlled-stage',max_evaluations:1}};
  const previousFetch=globalThis.fetch,previousToken=process.env.DAYAN_ACCESS_TOKEN;
  let forwarded;
  process.env.DAYAN_ACCESS_TOKEN='controlled-token'.repeat(4);
  globalThis.fetch=async(url,init)=>{
    if(new URL(url).pathname==='/api/health')return Response.json({service:'dayan',contract_version:'research-integrity-1'});
    forwarded=JSON.parse(init.body);
    return Response.json({ok:true,validation_pass:false,payload:{run_id:'R-baseline',model_id:'USR-controlled',
      research_intent_id:'MI-controlled-stage',study_id:'MS-controlled-stage',status:'research_pending',
      request_complete:false,execution_complete:true,next_action:next,
      observations:Array.from({length:3000},(_,i)=>({sim_t:i,stock:i})),
      manifest:{scenario_review:{runtime_checks:{verification:{status:'passed'}}}}}});
  };
  try{
    const result=JSON.parse((await bridge.execute({action:'build_model',research_intent_id:'MI-controlled-stage'},
      {agent:{session}})).json);
    assert.equal(forwarded.arguments.research_intent_id,'MI-controlled-stage');
    assert.equal(forwarded.original_text,original);
    assert.equal(result.payload.status,'research_pending');assert.equal(result.payload.request_complete,false);
    assert.equal(result.payload.research_intent_id,'MI-controlled-stage');assert.equal(result.payload.study_id,'MS-controlled-stage');
    assert.deepEqual(result.payload.next_action,next);assert.deepEqual(result.next_action,next);
    assert.equal(result.run_receipt.final_observation.stock,2999);
    assert.ok(Buffer.byteLength(JSON.stringify(result))<42000);
  }finally{
    globalThis.fetch=previousFetch;
    if(previousToken===undefined)delete process.env.DAYAN_ACCESS_TOKEN;else process.env.DAYAN_ACCESS_TOKEN=previousToken;
  }
});

// Register after the real isolated test so module-level endpoint configuration
// cannot be cached before that test sets its own temporary URL and data dir.
test('controlled source evidence bridge preserves the original, same MI and real revision action', sourceEvidenceBridgeTest);

test('controlled native transport forwards opaque continuation, proposal revision and full-group report inputs',async()=>{
  const {dayanToolDefinition}=await import('../plugins/dayan/host/tools.js');
  const original='保留本轮研究问题、真实数据与运行设置。';
  const session={id:'controlled-continuation-owner',snapshotEvents:()=>[
    {type:'user/message',seq:9,data:{source:{kind:'user'},content:[{type:'text',text:original}]}}
  ]};
  const md='MD-'+'c'.repeat(32), token='MC-'+'d'.repeat(64);
  const next={action:'design_model',arguments:{design_id:md,continuation_token:token}};
  const previousFetch=globalThis.fetch,previousToken=process.env.DAYAN_ACCESS_TOKEN,requests=[];
  const previousAuth=process.env.DAYAN_AUTHORING_WALL_SECONDS,previousWall=process.env.DAYAN_WALL_SECONDS;
  const previousTimeout=AbortSignal.timeout,deadlines=[];
  delete process.env.DAYAN_AUTHORING_WALL_SECONDS;delete process.env.DAYAN_WALL_SECONDS;
  const bridge=dayanToolDefinition();
  AbortSignal.timeout=ms=>{deadlines.push(ms);return previousTimeout.call(AbortSignal,ms);};
  process.env.DAYAN_ACCESS_TOKEN='controlled-transport-token'.repeat(4);
  globalThis.fetch=async(url,init)=>{
    if(new URL(url).pathname==='/api/health')return Response.json({service:'dayan',contract_version:'research-integrity-1'});
    requests.push(JSON.parse(init.body));
    return Response.json({ok:true,payload:{status:'pending',design_id:md,next_action:next,
      fixture:'controlled SDK transport only; no model or report executed'}});
  };
  try{
    assert.equal(bridge.timeoutMs,990000);
    for(const field of ['continuation_token','revise_proposal','experiment_id','analysis_id'])
      assert.ok(bridge.parameters.properties[field],field);
    const result=JSON.parse((await bridge.execute({action:'design_model',...next.arguments},{agent:{session}})).json);
    assert.equal(deadlines.at(-1),945000);
    assert.deepEqual(requests.at(-1).arguments,next.arguments);
    assert.equal(requests.at(-1).original_text,original);
    assert.deepEqual(result.next_action,next);
    const explicitDefinition={fixture:'controlled transport only; not an executed model'};
    await bridge.execute({action:'validate_model',...next.arguments,definition:explicitDefinition},{agent:{session}});
    assert.deepEqual(requests.at(-1).arguments,{...next.arguments,definition:explicitDefinition});
    await bridge.execute({action:'design_model',revise_from:md,revise_proposal:true},{agent:{session}});
    assert.deepEqual(requests.at(-1).arguments,{revise_from:md,revise_proposal:true});
    await bridge.execute({action:'report_run',run_id:'R-controlled',experiment_id:'EX-controlled'},{agent:{session}});
    assert.deepEqual(requests.at(-1).arguments,{run_id:'R-controlled',experiment_id:'EX-controlled'});
    await bridge.execute({action:'report_run',run_id:'R-controlled',analysis_id:'AN-controlled'},{agent:{session}});
    assert.deepEqual(requests.at(-1).arguments,{run_id:'R-controlled',analysis_id:'AN-controlled'});
    assert.equal(deadlines.at(-1),285000);
    process.env.DAYAN_WALL_SECONDS='240';
    await bridge.execute({action:'design_model',...next.arguments},{agent:{session}});
    assert.equal(deadlines.at(-1),285000);
  }finally{
    globalThis.fetch=previousFetch;
    AbortSignal.timeout=previousTimeout;
    if(previousAuth===undefined)delete process.env.DAYAN_AUTHORING_WALL_SECONDS;else process.env.DAYAN_AUTHORING_WALL_SECONDS=previousAuth;
    if(previousWall===undefined)delete process.env.DAYAN_WALL_SECONDS;else process.env.DAYAN_WALL_SECONDS=previousWall;
    if(previousToken===undefined)delete process.env.DAYAN_ACCESS_TOKEN;else process.env.DAYAN_ACCESS_TOKEN=previousToken;
  }
});

test('controlled async transport submits once, waits for actual job completion and cancels only its own job',async()=>{
  const {dayanToolDefinition,waitForPlatformJob}=await import('../plugins/dayan/host/tools.js');
  const bridge=dayanToolDefinition(),jobId='e'.repeat(32),md='MD-'+'b'.repeat(32);
  const session={id:'controlled-async-owner',snapshotEvents:()=>[
    {type:'user/message',seq:10,data:{source:{kind:'user'},content:[{type:'text',text:'保持原始建模需求。'}]}}
  ]};
  const previousFetch=globalThis.fetch,previousToken=process.env.DAYAN_ACCESS_TOKEN;
  const calls=[];let polls=0,mode='done';
  process.env.DAYAN_ACCESS_TOKEN='controlled-async-token'.repeat(4);
  globalThis.fetch=async(url,init={})=>{
    const path=new URL(url).pathname;
    if(path==='/api/health')return Response.json({service:'dayan',contract_version:'research-integrity-1'});
    calls.push({path,method:init.method||'GET',body:init.body&&JSON.parse(init.body),signal:init.signal});
    if(path==='/api/tools/build_model')return Response.json({job_id:jobId});
    assert.equal(path,'/api/jobs/'+jobId);
    if(init.method==='DELETE'){
      assert.equal(init.signal.aborted,false);
      return Response.json({status:'error',terminal_reason:'cancelled'});
    }
    if(mode==='error')return Response.json({status:'error',error:'controlled resource failure',terminal_reason:'wall_timeout'});
    if(mode==='cancel')return Response.json({status:'running'});
    polls++;
    return Response.json(polls<3?{status:polls===1?'queued':'running'}:{status:'done',result:{ok:true,payload:{
      fixture:'controlled transport only, not an executed model',status:'pending',design_id:md}}});
  };
  try{
    const result=JSON.parse((await bridge.execute({action:'build_model',design_id:md},{agent:{session}})).json);
    assert.equal(result.ok,true);assert.equal(polls,3);
    const submitted=calls.filter(c=>c.path.startsWith('/api/tools/'));
    assert.equal(submitted.length,1);assert.equal(submitted[0].body.async_job,true);
    assert.deepEqual(submitted[0].body.arguments,{design_id:md});
    assert.equal(submitted[0].body.original_text,'保持原始建模需求。');
    mode='cancel';const controller=new AbortController();
    const timer=setTimeout(()=>controller.abort(new Error('controlled caller cancellation')),20);
    await assert.rejects(waitForPlatformJob(jobId,controller.signal));clearTimeout(timer);
    assert.equal(calls.filter(c=>c.method==='DELETE').length,1);
    mode='error';const failed=await waitForPlatformJob(jobId);
    assert.equal(failed.ok,false);assert.equal(failed.terminal_reason,'wall_timeout');
  }finally{
    globalThis.fetch=previousFetch;
    if(previousToken===undefined)delete process.env.DAYAN_ACCESS_TOKEN;else process.env.DAYAN_ACCESS_TOKEN=previousToken;
  }
});
