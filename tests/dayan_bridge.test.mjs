/** Synthetic SDK context, REAL Python service/auth/queue/model/archive. */
import test from 'node:test';
import assert from 'node:assert/strict';
import { spawn } from 'node:child_process';
import { createServer } from 'node:net';
import { mkdtemp, readFile, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

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
    const { dayanToolDefinition } = await import('../plugins/dayan/host/tools.js');
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
