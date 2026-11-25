/** Explicit SDK protocol fixtures; actual installed DSH is checked separately. */
import test from 'node:test';
import assert from 'node:assert/strict';
import { resolve, join } from 'node:path';
import { createArgumentRecovery } from '../plugins/dayan/host/request-recovery.js';

function sessionFixture(cwd, restored = []) {
  const messages = structuredClone(restored), events = [];
  return { header: { cwd }, messages, events,
    deriveMessages: () => messages.map(message => structuredClone(message)),
    append: (type, data, options) => {
      assert.equal(type, 'user/message');
      assert.deepEqual(options, { surfaceOp: 'append' });
      assert.equal(data.role, 'user');
      assert.notEqual(data.source.kind, 'user', 'recovery is attributed context, never an original user requirement');
      assert.match(data.id, /^[0-9a-f-]{36}$/);
      events.push({ type, data: structuredClone(data), ...options });
      messages.push(structuredClone(data));
    }
  };
}

test('malformed DAYAN request records safe same-step guidance and durable bounded recovery across restoration', async () => {
  const root = resolve('dayan-recovery-project');
  const session = sessionFixture(join(root, 'workspace'));
  const recover = createArgumentRecovery({ projectRoot: root, maxRetries: 2 });
  const failure = { code: 'MALFORMED_RESPONSE', message: 'Tool call "dayan": invalid JSON\nReceived arguments: PRIVATE_FIXTURE_DO_NOT_PROMOTE' };
  const signal = new AbortController().signal;
  let delegated = 0;
  const next = async () => { delegated++; return undefined; };
  assert.deepEqual(await recover({ agent: { session }, turn: 1, step: 3, failure, signal }, next), { kind: 'retry' });
  assert.equal(session.events[0].data.source.retry, 1);
  const text = session.messages[0].content[0].text;
  assert.match(text, /arguments_path/);
  assert.match(text, /原文/);
  assert.equal(text.includes('PRIVATE_FIXTURE_DO_NOT_PROMOTE'), false);
  const restored = sessionFixture(session.header.cwd, session.messages);
  assert.deepEqual(await recover({ agent: { session: restored }, turn: 1, step: 3, failure, signal }, next), { kind: 'retry' });
  assert.equal(restored.messages.at(-1).source.retry, 2);
  assert.equal(await recover({ agent: { session: restored }, turn: 1, step: 3, failure, signal }, next), undefined);
  assert.equal(delegated, 1);
  assert.equal(restored.events.length, 1);
  assert.deepEqual(await recover({ agent: { session: restored }, turn: 1, step: 4, failure, signal }, next), { kind: 'retry' });
  assert.equal(restored.messages.at(-1).source.retry, 1);
});

test('recovery does not intercept other tools, other failures, outside projects, cancellation or disposed scopes', async () => {
  const root = resolve('dayan-recovery-project');
  const session = sessionFixture(join(root, 'workspace'));
  const recover = createArgumentRecovery({ projectRoot: root });
  const good = { agent: { session }, turn: 1, step: 0,
    failure: { code: 'MALFORMED_RESPONSE', message: 'Tool call "dayan": malformed' }, signal: new AbortController().signal };
  const cancelled = new AbortController(); cancelled.abort();
  let delegated = 0;
  const next = async () => { delegated++; return { kind: 'other-policy-fixture' }; };
  for (const payload of [
    { ...good, failure: { code: 'MALFORMED_RESPONSE', message: 'Tool call "shell": malformed' } },
    { ...good, failure: { code: 'AUTH', message: 'Tool call "dayan": authentication' } },
    { ...good, failure: { code: 'MALFORMED_RESPONSE', message: 'unrelated invalid response' } },
    { ...good, signal: cancelled.signal },
    { ...good, agent: { session: sessionFixture(resolve('different-project')) } },
    { ...good, step: undefined }
  ]) assert.deepEqual(await recover(payload, next), { kind: 'other-policy-fixture' });
  assert.equal(delegated, 6);
  assert.equal(session.events.length, 0);
  const disposed = createArgumentRecovery({ projectRoot: root, isActive: () => false });
  assert.deepEqual(await disposed(good, next), { kind: 'other-policy-fixture' });
  assert.equal(session.events.length, 0);
  const moved = createArgumentRecovery({ projectRoot: root, workingDirectory: { get: () => resolve('different-project') } });
  assert.deepEqual(await moved(good, next), { kind: 'other-policy-fixture' });
  assert.equal(session.events.length, 0);
});
