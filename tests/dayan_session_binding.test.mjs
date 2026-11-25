/** Synthetic SDK boundary fixtures only; real native UI acceptance is recorded separately. */
import test from 'node:test';
import assert from 'node:assert/strict';
import { mkdtempSync, mkdirSync, readdirSync, readFileSync, writeFileSync } from 'node:fs';
import { join } from 'node:path';
import { reserveProjectSession } from '../plugins/dayan/host/session-binding.js';
import { openProjectConversation } from '../plugins/dayan/client/session-binding.js';

const fixtureRoot = join(import.meta.dirname, '../.claude/session_binding_fix_20261116/unit_fixtures');
mkdirSync(fixtureRoot, { recursive: true });
const id = 'session-dayan-11111111-1111-4111-8111-111111111111';
const root = 'D:/unit-fixture/dayan';
const record = { schemaVersion: 2, sessionId: id, projectRoot: root };

function sdkFixture({ own = true, ownRoot = root, actualId = id, openState = 'open', snapshotId = id, phase = 'ready' } = {}) {
  let snapshot = { phase, byId: { 'ordinary-foreign': { id: 'ordinary-foreign', cwd: 'C:/unrelated', retainedBy: { mainView: 1 } },
    ...(own ? { [id]: { id, cwd: ownRoot } } : {}) } };
  const listeners = new Set(), calls = [], binding = { session: {
    getSnapshot: () => ({ sessionId: snapshotId, openState }), rename: async title => { calls.push(['rename', title]); } } };
  let released = false, currentBinding = binding;
  const reference = {
    sessionId: id,
    ready: Promise.resolve(binding),
    get binding() {
      if (released) throw new Error('Session reference is released');
      return binding;
    },
    release() { released = true; calls.push(['release']); },
  };
  const sessions = { list: { getSnapshot: () => snapshot, subscribe: fn => { listeners.add(fn); return () => listeners.delete(fn); } },
    create: async args => { calls.push(['create', args]); snapshot.byId[id] = { id, cwd: root }; return actualId; },
    retain: (...args) => { calls.push(['retain', ...args]); return reference; }, binding: () => currentBinding };
  return { sessions, calls, invalidate: () => { currentBinding = undefined; },
    ready: () => { snapshot = { ...snapshot, phase: 'ready' }; for (const fn of listeners) fn(); } };
}

test('host reservation survives reload and isolates both profile and project', () => {
  const dataDir = mkdtempSync(join(fixtureRoot, '/reservation-'));
  const options = { dataDir, projectRoot: root, profileDir: 'C:/unit-fixture/profile-a' };
  const first = reserveProjectSession(options);
  assert.deepEqual(reserveProjectSession(options), first);
  assert.notEqual(reserveProjectSession({ ...options, profileDir: 'C:/unit-fixture/profile-b' }).sessionId, first.sessionId);
  assert.notEqual(reserveProjectSession({ ...options, projectRoot: root + '-other' }).sessionId, first.sessionId);
  assert.throws(() => reserveProjectSession({ ...options, profileDir: '' }), /profile identity/);
});

test('corrupt durable identity is rejected without overwriting it', () => {
  const dataDir = mkdtempSync(join(fixtureRoot, '/corrupt-'));
  const options = { dataDir, projectRoot: root, profileDir: 'C:/unit-fixture/profile-a' };
  reserveProjectSession(options);
  const directory = join(dataDir, 'integrations/dsh/project_sessions');
  const file = join(directory, readdirSync(directory).find(n => n.endsWith('.json')));
  writeFileSync(file, '{}');
  assert.throws(() => reserveProjectSession(options), /record mismatch/);
  assert.equal(readFileSync(file, 'utf8'), '{}');
});

test('foreign mainView retention cannot override the reserved project session', async () => {
  const fixture = sdkFixture();
  const bound = await openProjectConversation({ sessions: fixture.sessions, record, projectRoot: root });
  assert.equal(bound.sessionId, id);
  assert.deepEqual(fixture.calls.map(c => c[0]), ['retain']);
  assert.equal(fixture.calls[0][1], id);
});

test('a superseded connection remains live until its provider has unmounted', async () => {
  const fixture = sdkFixture();
  const owned = await openProjectConversation({ sessions: fixture.sessions, record, projectRoot: root });
  assert.equal(owned.isCurrent(), true);
  const binding = owned.reference.binding;
  const unmount = owned.hold();
  owned.retire();
  await Promise.resolve();
  assert.equal(owned.isCurrent(), false);
  assert.equal(owned.reference.binding, binding);
  unmount();
  assert.equal(owned.reference.binding, binding);
  owned.retire();
  unmount();
  await Promise.resolve();
  assert.throws(() => owned.reference.binding, /is released/);
  assert.equal(fixture.calls.filter(([action]) => action === 'release').length, 1);
});

test('an invalidated session controller cannot be rendered as a current connection', async () => {
  const fixture = sdkFixture();
  const owned = await openProjectConversation({ sessions: fixture.sessions, record, projectRoot: root });
  fixture.invalidate();
  assert.equal(owned.isCurrent(), false);
  owned.retire();
  await Promise.resolve();
  assert.equal(fixture.calls.filter(([action]) => action === 'release').length, 1);
});

test('missing owned session is created with the exact reserved identity', async () => {
  const fixture = sdkFixture({ own: false });
  const bound = await openProjectConversation({ sessions: fixture.sessions, record, projectRoot: root });
  assert.equal(bound.sessionId, id);
  assert.deepEqual(fixture.calls[0], ['create', { cwd: root, sessionId: id }]);
});

test('wrong directory and ordinary identities cannot be adopted', async () => {
  const fixture = sdkFixture({ ownRoot: 'C:/unrelated' });
  await assert.rejects(openProjectConversation({ sessions: fixture.sessions, record, projectRoot: root }), /实际项目目录不符/);
  await assert.rejects(openProjectConversation({ sessions: fixture.sessions, record: { ...record, sessionId: 'ordinary-foreign' }, projectRoot: root }), /身份与当前项目不符/);
  assert.equal(fixture.calls.length, 0);
});

test('an alternate create response never becomes a fallback conversation', async () => {
  const fixture = sdkFixture({ own: false, actualId: 'another-session' });
  await assert.rejects(openProjectConversation({ sessions: fixture.sessions, record, projectRoot: root }), /返回了另一对话/);
  assert.equal(fixture.calls.some(c => c[0] === 'retain'), false);
});

test('ready resolving to an error state or different actual binding is rejected', async () => {
  for (const change of [{ openState: 'error' }, { snapshotId: 'another-session' }]) {
    const fixture = sdkFixture(change);
    await assert.rejects(openProjectConversation({ sessions: fixture.sessions, record, projectRoot: root }), /实际会话绑定核验失败/);
    assert.equal(fixture.calls.filter(c => c[0] === 'release').length, 1);
  }
});

test('catalog must finish loading before a missing session can be created', async () => {
  const fixture = sdkFixture({ own: false, phase: 'pending' });
  const pending = openProjectConversation({ sessions: fixture.sessions, record, projectRoot: root });
  await Promise.resolve(); assert.equal(fixture.calls.length, 0);
  fixture.ready(); assert.equal((await pending).sessionId, id);
});

test('late session creation after cancellation cannot retain or publish a binding', async () => {
  const fixture = sdkFixture({ own: false }), controller = new AbortController();
  let finish;
  fixture.sessions.create = () => new Promise(resolve => { finish = resolve; });
  const pending = openProjectConversation({ sessions: fixture.sessions, record, projectRoot: root, signal: controller.signal });
  await Promise.resolve(); controller.abort(); finish(id);
  await assert.rejects(pending);
  assert.equal(fixture.calls.length, 0);
});
