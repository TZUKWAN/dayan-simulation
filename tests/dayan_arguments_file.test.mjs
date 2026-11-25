/** Real filesystem reads; no platform model or cloud acceptance is claimed. */
import test from 'node:test';
import assert from 'node:assert/strict';
import { mkdtemp, mkdir, writeFile, open, symlink, rm } from 'node:fs/promises';
import { createHash } from 'node:crypto';
import { tmpdir } from 'node:os';
import { join, resolve, sep } from 'node:path';
import { readToolArguments } from '../plugins/dayan/host/tool-arguments-file.js';

async function fixture() {
  const folder = await mkdtemp(join(tmpdir(), 'dayan-arguments-'));
  const root = join(folder, 'project'), cwd = join(root, 'workspace'), outside = join(folder, 'outside');
  for (const path of [cwd, outside]) await mkdir(path, { recursive: true });
  return { folder, root, cwd, outside, close: async () => {
    assert.ok(resolve(folder).startsWith(resolve(tmpdir()) + sep));
    assert.ok(folder.includes('dayan-arguments-'));
    await rm(folder, { recursive: true, force: true });
  } };
}

test('parameter file keeps nested research data, Unicode, bytes and hash without executing source', async () => {
  const f = await fixture();
  try {
    const envelope = { tool: 'research_model_prepare', arguments: {
      target_bindings: [{ id: 'population', columns: { value: { field: 'value', scale: 1 } } }],
      diagnostics: [{ kind: 'time_refinement', dts: [1, .5, .25], max_scaled_change: 1e-6 }],
      execution: { parameters: { r: 0 }, seed: 19 },
      source: 'raise RuntimeError("读取不得执行")\n# 引号 " 与反斜杠 \\',
      note: null, enabled: false
    } };
    const bytes = Buffer.from('\uFEFF' + JSON.stringify(envelope));
    await writeFile(join(f.cwd, 'parameters.json'), bytes);
    const actual = await readToolArguments('parameters.json', { projectRoot: f.root, cwd: f.cwd }, envelope.tool);
    assert.deepEqual(actual.arguments, envelope.arguments);
    assert.equal(actual.receipt.tool, envelope.tool);
    assert.equal(actual.receipt.bytes, bytes.length);
    assert.equal(actual.receipt.sha256, createHash('sha256').update(bytes).digest('hex'));
    await assert.rejects(readToolArguments('parameters.json', { projectRoot: f.root, cwd: f.cwd }, 'build_model'), /tool.*不一致/);
    for (const content of ['{"tool":"x","arguments":{', '[]', '{"tool":"x","arguments":[]}',
      '{"tool":"x","arguments":{},"extra":true}', Buffer.from([0xff, 0xfe, 0x7b])]) {
      await writeFile(join(f.cwd, 'invalid.json'), content);
      await assert.rejects(readToolArguments('invalid.json', { projectRoot: f.root, cwd: f.cwd }, 'x'), /JSON|顶层|参数对象|额外字段/);
    }
    const handle = await open(join(f.cwd, 'oversize.json'), 'w');
    try { await handle.truncate(16 * 1024 * 1024 + 1); } finally { await handle.close(); }
    await assert.rejects(readToolArguments('oversize.json', { projectRoot: f.root, cwd: f.cwd }, 'x'), /16 MiB/);
  } finally { await f.close(); }
});

test('parameter file rejects outside cwd, traversal and junction targets before reading arguments', async () => {
  const f = await fixture();
  try {
    await writeFile(join(f.outside, 'parameters.json'), JSON.stringify({ tool: 'x', arguments: {} }));
    await assert.rejects(readToolArguments(join(f.outside, 'parameters.json'), { projectRoot: f.root, cwd: f.cwd }, 'x'), /越界/);
    await assert.rejects(readToolArguments('parameters.json', { projectRoot: f.root, cwd: f.outside }, 'x'), /会话目录/);
    await symlink(f.outside, join(f.cwd, 'redirect'), process.platform === 'win32' ? 'junction' : 'dir');
    await assert.rejects(readToolArguments('redirect/parameters.json', { projectRoot: f.root, cwd: f.cwd }, 'x'), /越界/);
  } finally { await f.close(); }
});

test('native file transport preserves complete arguments, durable user text and receipts; rejected files never dispatch', async () => {
  const f = await fixture();
  const names = ['DAYAN_PROJECT_ROOT', 'DAYAN_BACKEND_URL', 'DAYAN_ACCESS_TOKEN'];
  const saved = Object.fromEntries(names.map(name => [name, process.env[name]]));
  const previousFetch = globalThis.fetch;
  const requests = [];
  try {
    process.env.DAYAN_PROJECT_ROOT = f.root;
    process.env.DAYAN_BACKEND_URL = 'http://127.0.0.1:61237';
    process.env.DAYAN_ACCESS_TOKEN = 'explicit-transport-fixture-token'.repeat(3);
    const { dayanToolDefinition } = await import('../plugins/dayan/host/tools.js?arguments-file-fixture');
    const bridge = dayanToolDefinition();
    const original = '这是明确标记的传输测试原文；保留所有科学条件，不用文件中的文字替换。';
    const session = { id: 'arguments-file-fixture', header: { cwd: f.cwd }, snapshotEvents: () => [
      { type: 'user/message', seq: 8, data: { source: { kind: 'user' }, content: [{ type: 'text', text: original }] } },
      { type: 'user/message', seq: 9, data: { source: { kind: 'context' }, content: [{ type: 'text', text: '非用户的恢复提示' }] } }
    ] };
    const parameters = { time_origin: '2010年度', param_grid: { r: [-.004, -.003, -.002, -.001, 0] },
      target_bindings: [{ id: 'population', columns: { value: { field: 'value', source_unit: 'person' } } }],
      diagnostics: [{ kind: 'time_refinement', dts: [1, .5, .25], max_scaled_change: .000001 }],
      execution: { ticks: 10, dt: 1, seed: 19 } };
    const bytes = Buffer.from(JSON.stringify({ tool: 'research_model_prepare', arguments: parameters }));
    await writeFile(join(f.cwd, 'study.json'), bytes);
    globalThis.fetch = async (url, init) => {
      const path = new URL(url).pathname;
      if (path === '/api/health') return Response.json({ service: 'dayan', contract_version: 'research-integrity-1' });
      if (path === '/api/agent/tools') return Response.json({ tools: [{ name: 'research_model_prepare', parameters: { type: 'object' } }] });
      requests.push(JSON.parse(init.body));
      return Response.json({ ok: true, payload: { status: 'awaiting_model', research_intent_id: 'MI-' + 'a'.repeat(24) } });
    };
    const schema = JSON.parse((await bridge.execute({ action: 'schema', tool: 'research_model_prepare' }, { agent: { session } })).json);
    assert.equal(schema.native_arguments_submission.field, 'arguments_path');
    assert.match(schema.native_session_binding.research_model_prepare.question, /可省略/);
    const result = JSON.parse((await bridge.execute({ action: 'execute', tool: 'research_model_prepare', arguments_path: 'study.json' }, { agent: { session } })).json);
    assert.equal(result.ok, true, result.error);
    assert.deepEqual(requests[0].arguments, parameters);
    assert.equal(requests[0].original_text, original);
    assert.equal(requests[0].session_id, session.id);
    assert.equal(requests[0].origin, 'dsh');
    assert.equal(Object.hasOwn(requests[0].arguments, 'question'), false, 'native backend binds the real user text, not a recopied question');
    assert.equal(result.arguments_file.sha256, createHash('sha256').update(bytes).digest('hex'));
    assert.equal(result.arguments_file.bytes, bytes.length);
    for (const call of [
      { action: 'execute', tool: 'research_model_prepare', arguments_path: 'study.json', arguments: {} },
      { action: 'execute', tool: 'research_model_prepare', arguments_path: 'study.json', ticks: 1 },
      { action: 'execute', tool: 'build_model', arguments_path: 'study.json' },
      { action: 'schema', tool: 'research_model_prepare', arguments_path: 'study.json' }
    ]) {
      const denied = JSON.parse((await bridge.execute(call, { agent: { session } })).json);
      assert.equal(denied.ok, false);
      assert.match(denied.error, /混用|不一致|只用于/);
      assert.equal(requests.length, 1);
    }
  } finally {
    globalThis.fetch = previousFetch;
    for (const name of names) if (saved[name] === undefined) delete process.env[name]; else process.env[name] = saved[name];
    await f.close();
  }
});
