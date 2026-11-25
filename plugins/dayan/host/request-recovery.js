/** Recover only pre-dispatch malformed DAYAN calls in this project's live step. */
import { randomUUID } from 'node:crypto';
import { isAbsolute, relative, resolve, sep } from 'node:path';

const SOURCE = 'dayan-tool-argument-recovery';
const MAX_RETRIES = 5;

export function createArgumentRecovery({ projectRoot, workingDirectory, isActive = () => true, maxRetries = MAX_RETRIES }) {
  const root = resolve(projectRoot);
  if (!Number.isSafeInteger(maxRetries) || maxRetries < 1 || maxRetries > 20)
    throw new Error('参数恢复预算须为1至20次');
  return async function recover({ agent, turn, step, failure, signal }, next) {
    if (!isActive() || signal?.aborted || failure?.code !== 'MALFORMED_RESPONSE' ||
        !/^Tool call ["']dayan["']:/.test(failure.message || '')) return next();
    const session = agent?.session;
    const cwd = workingDirectory?.get(session) ?? session?.header?.cwd;
    if (!session || !cwd || !isAbsolute(cwd) || typeof session.deriveMessages !== 'function' ||
        !Number.isSafeInteger(turn) || turn < 0 || !Number.isSafeInteger(step) || step < 0) return next();
    const location = relative(root, resolve(cwd));
    if (location === '..' || location.startsWith('..' + sep) || isAbsolute(location)) return next();
    // Read the documented surface, not deprecated synchronous event snapshots.
    // This count survives session save/restore and is scoped to the same step.
    const prior = session.deriveMessages().filter(message => message.source?.kind === SOURCE &&
      message.source.turn === turn && message.source.step === step);
    const count = Math.max(0, ...prior.map(message => Number.isSafeInteger(message.source.retry) ? message.source.retry : 0));
    if (count >= maxRetries) return next();
    signal?.throwIfAborted();
    const retry = count + 1;
    const text = '大衍原生工具参数恢复：本次dayan工具调用因JSON格式无效在分派前失败，未进入大衍后台。' +
      `这是同一轮次/步骤的第${retry}/${maxRetries}次定向恢复，原失败保留在会话日志。` +
      '保持当前真实用户原文、已有数据集和MI/MD/MS编号、全部参数/划分/阈值/种子，按原next_action继续。' +
      '先核对应工具schema；复杂参数用JSON序列化写项目内文件{"tool":"实际工具名","arguments":{完整参数}}，' +
      '再dayan({action:"execute",tool:"同一工具名",arguments_path:"parameters.json"})，不混用inline参数。' +
      '原生research_model_prepare.question可省略，后台逐字绑定真实用户消息。' +
      '核已有回执，需要时用research_status恢复，勿重复采集或重建已经成功的阶段；不要缩减需求、编造通过或修改平台绕过检查。';
    // Plain developer text is not projected by every installed adapter. Use an
    // attributed context message; kind is deliberately not "user", so the
    // native bridge never mistakes this for the actual user's requirement.
    session.append('user/message', {
      id: randomUUID(), role: 'user',
      source: { kind: SOURCE, turn, step, retry, maxRetries, code: failure.code, tool: 'dayan' },
      content: [{ type: 'text', text }]
    }, { surfaceOp: 'append' });
    return { kind: 'retry' };
  };
}

export function registerDayanArgumentRecovery(ctx, projectRoot) {
  ctx.inject(['agents', 'sessions', 'workingDirectory'], scope => {
    let active = true;
    const recover = createArgumentRecovery({ projectRoot, workingDirectory: scope.workingDirectory, isActive: () => active });
    const off = scope.on('agent/request-error', recover);
    scope.effect(() => () => { active = false; if (typeof off === 'function') off(); }, 'dayan: scoped argument recovery');
  });
}
