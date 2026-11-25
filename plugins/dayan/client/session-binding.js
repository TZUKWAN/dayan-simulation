/** Bind only the host-reserved Dayan identity, never the ordinary main chat. */
export function projectPathKey(value) {
  const text = String(value || '').replace(/\\/g, '/').replace(/\/+$/, '');
  return /^[a-z]:\//i.test(text) || text.startsWith('//') ? text.toLowerCase() : text;
}

function waitForCatalog(store, signal) {
  return new Promise((resolve, reject) => {
    let off = () => {};
    const stop = () => { off(); signal?.removeEventListener('abort', abort); };
    const abort = () => { stop(); reject(signal.reason || new Error('Conversation binding cancelled')); };
    const read = () => {
      if (signal?.aborted) return abort();
      const snapshot = store.getSnapshot();
      if (snapshot.phase === 'ready') { stop(); resolve(snapshot); }
      else if (snapshot.phase === 'error') { stop(); reject(new Error('DSH conversation catalog failed to load')); }
    };
    off = store.subscribe(read);
    signal?.addEventListener('abort', abort, { once: true });
    read();
  });
}

function ownConversation(sessions, reference, binding) {
  let mounts = 0, retired = false, released = false;
  function releaseWhenUnmounted() {
    if (!retired || mounts !== 0 || released) return;
    // The host's SessionProvider may still be finishing this React commit.
    queueMicrotask(() => {
      if (released || mounts !== 0) return;
      released = true;
      reference.release();
    });
  }
  return {
    sessionId: reference.sessionId,
    reference,
    isCurrent() {
      if (retired) return false;
      try {
        return reference.binding === binding && sessions.binding(reference.sessionId) === binding;
      } catch {
        // A replaced Session Controller invalidates the entire reference generation.
        return false;
      }
    },
    hold() {
      if (retired) return () => {};
      mounts += 1;
      let active = true;
      return () => {
        if (!active) return;
        active = false;
        mounts -= 1;
        releaseWhenUnmounted();
      };
    },
    retire() {
      retired = true;
      releaseWhenUnmounted();
    },
  };
}

export async function openProjectConversation({ sessions, record, projectRoot, signal }) {
  signal?.throwIfAborted();
  if (record?.schemaVersion !== 2 || !/^session-dayan-[a-f0-9-]{36}$/.test(record?.sessionId || '') ||
      !projectPathKey(projectRoot) || projectPathKey(record.projectRoot) !== projectPathKey(projectRoot)) {
    throw new Error('大衍专属对话身份与当前项目不符，已阻止绑定其他对话');
  }
  const id = record.sessionId;
  const catalog = await waitForCatalog(sessions.list, signal);
  const row = catalog.byId[id];
  if (row && projectPathKey(row.cwd) !== projectPathKey(projectRoot)) {
    throw new Error('大衍对话的实际项目目录不符，已阻止打开其他对话');
  }
  let created = false, reference;
  try {
    if (!row) {
      const result = await sessions.create({ cwd: projectRoot, sessionId: id });
      const actualId = typeof result === 'string' ? result : result?.sessionId || result?.id;
      if (actualId !== id) throw new Error('DSH返回了另一对话，已拒绝替代大衍专属对话');
      created = true;
    }
    signal?.throwIfAborted();
    reference = sessions.retain(id, { source: 'dayanProject', signal });
    const binding = await reference.ready;
    signal?.throwIfAborted();
    const snapshot = binding?.session?.getSnapshot?.();
    if (reference.sessionId !== id || snapshot?.sessionId !== id || snapshot?.openState !== 'open' ||
        sessions.binding(id) !== binding) {
      throw new Error('DSH实际会话绑定核验失败，未显示其他对话');
    }
    const actual = sessions.list.getSnapshot().byId[id];
    if (!actual || projectPathKey(actual.cwd) !== projectPathKey(projectRoot)) {
      throw new Error('DSH实际会话目录核验失败，未显示其他对话');
    }
    if (created) await binding.session.rename('大衍研究对话');
    signal?.throwIfAborted();
    return ownConversation(sessions, reference, binding);
  } catch (error) {
    reference?.release();
    throw error;
  }
}
