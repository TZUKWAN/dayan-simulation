/** Files are real; API transport in the bridge case is an explicit protocol fixture. */
import test from 'node:test';
import assert from 'node:assert/strict';
import { mkdtemp, mkdir, writeFile, symlink, open, rm } from 'node:fs/promises';
import { createHash } from 'node:crypto';
import { tmpdir } from 'node:os';
import { join, resolve, sep } from 'node:path';
import { readModelDefinition } from '../plugins/dayan/host/model-definition-file.js';

async function fixture() {
  const folder = await mkdtemp(join(tmpdir(), 'dayan-definition-'));
  const root = join(folder, 'project'), cwd = join(root, 'workspace'), outside = join(folder, 'outside');
  for (const path of [cwd, outside]) await mkdir(path, { recursive: true });
  return { folder, root, cwd, outside, close: async () => {
    assert.ok(resolve(folder).startsWith(resolve(tmpdir()) + sep));
    assert.ok(folder.includes('dayan-definition-'));
    await rm(folder, { recursive: true, force: true });
  } };
}

test('UTF-8 JSON definition preserves multiline source without evaluating it; malformed data returns an error', async () => {
  const f = await fixture();
  try {
    const definition = { kind: 'program', source: 'raise RuntimeError("不得在宿主执行")\n# quotes "\\\n',
      parameters: {}, example: { unit: null, dynamic: false } };
    const bytes = Buffer.from('\uFEFF' + JSON.stringify(definition));
    await writeFile(join(f.cwd, 'definition.json'), bytes);
    const actual = await readModelDefinition('definition.json', { projectRoot: f.root, cwd: f.cwd });
    assert.deepEqual(actual.definition, definition);
    assert.equal(actual.receipt.sha256, createHash('sha256').update(bytes).digest('hex'));
    assert.equal(actual.receipt.bytes, bytes.length);
    for (const content of ['{"unit": None}', '[]', Buffer.from([0xff, 0xfe, 0x7b])]) {
      await writeFile(join(f.cwd, 'bad.json'), content);
      await assert.rejects(readModelDefinition('bad.json', { projectRoot: f.root, cwd: f.cwd }), /JSON|顶层/);
    }
    const handle = await open(join(f.cwd, 'large.json'), 'w');
    await handle.truncate(16 * 1024 * 1024 + 1);
    await handle.close();
    await assert.rejects(readModelDefinition('large.json', { projectRoot: f.root, cwd: f.cwd }), /16 MiB/);
  } finally { await f.close(); }
});

test('path and directory junction cannot read JSON outside the declared project', async () => {
  const f = await fixture();
  try {
    await writeFile(join(f.outside, 'private.json'), '{"private":true}');
    await symlink(f.outside, join(f.cwd, 'link'), process.platform === 'win32' ? 'junction' : 'dir');
    for (const path of ['../../outside/private.json', join(f.outside,'private.json'), 'link/private.json'])
      await assert.rejects(readModelDefinition(path,{ projectRoot:f.root,cwd:f.cwd }), /越界|外部链接/);
    await assert.rejects(readModelDefinition('private.json',{ projectRoot:f.root,cwd:f.outside }), /会话目录/);
  } finally { await f.close(); }
});

test('native bridge reads the same JSON for validation and construction and preserves original session and options', async () => {
  const f = await fixture(), oldFetch = globalThis.fetch;
  const names = ['DAYAN_PROJECT_ROOT','DAYAN_BACKEND_URL','DAYAN_ACCESS_TOKEN'];
  const saved = Object.fromEntries(names.map(name => [name, process.env[name]]));
  const requests = [];
  let fixtureResponse={ ok:true,payload:{ executed:false } }, designRecord;
  try {
    process.env.DAYAN_PROJECT_ROOT=f.root;
    process.env.DAYAN_BACKEND_URL='http://127.0.0.1:40403';
    process.env.DAYAN_ACCESS_TOKEN='explicit-test-token-'.repeat(3);
    globalThis.fetch=async (url,init) => {
      if (new URL(url).pathname==='/api/health') return Response.json({ service:'dayan',contract_version:'research-integrity-1' });
      if (new URL(url).pathname.startsWith('/api/model-designs/')) {
        assert.equal(new URL(url).searchParams.get('session_id'),'file-submission-session');
        return Response.json(designRecord);
      }
      requests.push({ path:new URL(url).pathname,body:JSON.parse(init.body) });
      return Response.json(fixtureResponse);
    };
    const { dayanToolDefinition }=await import('../plugins/dayan/host/tools.js');
    const bridge=dayanToolDefinition();
    assert.equal(bridge.parameters.properties.definition_path.type,'string');
    const definition={kind:'program',source:'def advance():\n    return "原样多行源码"\n'};
    await writeFile(join(f.cwd,'definition.json'),JSON.stringify(definition));
    const original='完整用户要求，不允许替换';
    const session={id:'file-submission-session',header:{cwd:f.cwd},snapshotEvents:()=>[
      {type:'user/message',seq:1,data:{source:{kind:'user'},content:[{type:'text',text:original}]}}
    ]};
    const settings={design_id:'MD-actual-input',ticks:10,dt:.2,seed:19};
    for (const action of ['validate_model','build_model']) {
      const result=JSON.parse((await bridge.execute({action,definition_path:'definition.json',...settings},{agent:{session}})).json);
      assert.equal(result.ok,true,result.error);
      assert.equal(result.definition_file.sha256,createHash('sha256').update(JSON.stringify(definition)).digest('hex'));
      assert.deepEqual(requests.at(-1),{path:'/api/tools/'+action,body:{async_job:true,arguments:{...settings,definition},
        origin:'dsh',session_id:session.id,original_text:original}});
    }
    const count=requests.length;
    await writeFile(join(f.cwd,'definition.json'),'{"unit": None}');
    const malformed=JSON.parse((await bridge.execute({action:'validate_model',definition_path:'definition.json',...settings},{agent:{session}})).json);
    assert.equal(malformed.ok,false);
    assert.match(malformed.error,/有效 UTF-8 JSON/);
    assert.equal(requests.length,count);
    const conflict=JSON.parse((await bridge.execute({action:'build_model',definition_path:'definition.json',definition,...settings},{agent:{session}})).json);
    assert.equal(conflict.ok,false);
    assert.match(conflict.error,/只能提供一种/);
    // Invalid file content is a repairable tool result; the Agent thread need not exit.
    await writeFile(join(f.cwd,'definition.json'),JSON.stringify(definition));
    const repaired=JSON.parse((await bridge.execute({action:'execute',tool:'validate_model',arguments:{definition_path:'definition.json',...settings}},{agent:{session}})).json);
    assert.equal(repaired.ok,true,repaired.error);
    assert.equal(requests.length,count+1);
    const design_id='MD-'+'a'.repeat(32);
    const criteria=Array.from({length:40},(_,i)=>({id:'V'+(i+1),reason:'原文逐项验收'.repeat(250),target:i}));
    const plan={kind:'program',criteria,rule_refs:[{mechanism:'实际推进',paths:['source.advance']}]};
    designRecord={design_id,session_id:session.id,status:'approved',plan,plan_sha256:'fixture-plan-hash',request:original};
    fixtureResponse={ok:true,payload:{...designRecord,next_action:{action:'build_model',arguments:{design_id}},stages:['long'.repeat(20000)]}};
    const summary=JSON.parse((await bridge.execute({action:'design_model'},{agent:{session}})).json);
    assert.equal(summary.payload.plan_omitted,true);
    assert.deepEqual(summary.payload.plan_access,{action:'design_details',design_id,section:'plan'});
    const directory=JSON.parse((await bridge.execute(summary.payload.plan_access,{agent:{session}})).json);
    assert.equal(directory.complete,false);
    assert.deepEqual(directory.fields,Object.keys(plan));
    const received=[];
    let offset=0;
    do {
      const part=JSON.parse((await bridge.execute({action:'design_details',design_id,field:'criteria',offset,limit:8},{agent:{session}})).json);
      assert.equal(part.ok,true,part.error);
      assert.equal(part.total,criteria.length);
      received.push(...part.value);offset=part.next_offset;
    } while(offset!==null);
    assert.deepEqual(received,criteria,'all original criteria survive bounded native transport');
    for (const field of ['kind','rule_refs']) {
      const part=JSON.parse((await bridge.execute({action:'design_details',design_id,field},{agent:{session}})).json);
      assert.deepEqual(part.value,plan[field]);
    }
    designRecord={...designRecord,session_id:'another-session'};
    const denied=JSON.parse((await bridge.execute({action:'design_details',design_id},{agent:{session}})).json);
    assert.equal(denied.ok,false);assert.match(denied.error,/当前会话/);
  } finally {
    globalThis.fetch=oldFetch;
    for (const name of names) if (saved[name]===undefined) delete process.env[name]; else process.env[name]=saved[name];
    await f.close();
  }
});
