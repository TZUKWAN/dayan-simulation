/**
 * 大衍 DAYAN for DSH — host entry.
 * 注册三条宿主路由 + 一组 DSH agent 工具（host/tools.js）：
 *   GET  /dayan/api/health        探测本机 8899 后端是否在线
 *   POST /dayan/api/backend/start 拉起 python -m dayan.server（幂等，已在线则直接返回）
 *   POST /dayan/api/backend/stop  停止由本插件拉起的后端
 *   tools: dayan（list_models/contract/run/sources/presets/run_preset/tasks/report_docx…）
 * AI 助手 = DSH 原生 agent：对话走 DSH 会话，能力经 dayan 工具驱动平台；
 * 工作台完整界面由后端直接提供，面板 iframe 原样嵌入，功能不阉割。
 */
import { join } from 'node:path';
import { readFileSync } from 'node:fs';
import { createHash } from 'node:crypto';
import * as bridge from './host/tools.js';
import { backendOnline, ensureBackend, stopManagedBackend, registerDayanContext, registerDayanTool, PROJECT_ROOT, BACKEND_URL } from './host/tools.js';
import { reserveProjectSession } from './host/session-binding.js';
import { registerDayanArgumentRecovery } from './host/request-recovery.js';

export const name = 'dayan';
const LOADED_HOST_SOURCE=createHash('sha256').update(readFileSync(new URL(import.meta.url))).digest('hex');

function send(res, status, payload) {
  if (res.destroyed || res.headersSent) return;
  const body = JSON.stringify(payload);
  res.writeHead(status, { 'content-type': 'application/json; charset=utf-8' });
  res.end(body);
}

export function apply(ctx) {
  const routes = [
    {
      kind: 'exact',
      path: '/dayan/api/health',
      handler: async (_req, res) => {
        const online = await backendOnline();
        send(res, 200, { ok: true, online, url: BACKEND_URL, projectRoot: PROJECT_ROOT,
          bridge_version: 'native-research-integrity-1', conversation_binding: 'project-session-v2',
          loaded_modules:{host_sha256:LOADED_HOST_SOURCE,bridge_sha256:bridge.LOADED_BRIDGE_SOURCE||null,
            proof:'captured_at_module_evaluation',feature_contract:'feature-closure-20261125'} });
      }
    },
    {
      kind: 'exact',
      path: '/dayan/api/native-session',
      handler: async (_req, res) => {
        try {
          const session = reserveProjectSession({ projectRoot: PROJECT_ROOT,
            dataDir: process.env.DAYAN_DATA_DIR || join(PROJECT_ROOT, 'data'),
            profileDir: ctx.get('profileContext')?.dir });
          send(res, 200, { ok: true, session });
        } catch (error) { send(res, 200, { ok: false, error: String(error.message || error) }); }
      }
    },
    {
      kind: 'exact',
      path: '/dayan/api/session-binding.js',
      handler: async (_req, res) => {
        if (res.destroyed || res.headersSent) return;
        res.writeHead(200, { 'content-type': 'application/javascript; charset=utf-8', 'cache-control': 'no-store' });
        res.end(readFileSync(new URL('./client/session-binding.js', import.meta.url), 'utf8'));
      }
    },
    {
      kind: 'exact',
      path: '/dayan/api/backend/start',
      handler: async (_req, res) => {
        if (await backendOnline(1200)) { send(res, 200, { ok: true, online: true, started: false }); return; }
        try { send(res, 200, { ok: true, ...await ensureBackend() }); }
        catch (error) { send(res, 200, { ok: false, error: String(error.message || error) }); }
      }
    },
    {
      kind: 'exact',
      path: '/dayan/api/backend/stop',
      handler: async (_req, res) => { send(res, 200, { ok: true, ...await stopManagedBackend() }); }
    }
  ];

  ctx.inject(['webServer'], (scope) => {
    for (const route of routes) {
      const off = scope.webServer.register(route);
      if (typeof off === 'function') scope.effect(() => off, 'dayan: ' + route.path);
    }
  });

  // DSH agent 工具：让 DSH 的 AI 直接驱动采集/仿真/报告
  registerDayanTool(ctx);
  registerDayanContext(ctx);
  registerDayanArgumentRecovery(ctx, PROJECT_ROOT);

  ctx.effect(() => () => {
    // 宿主卸载插件时不主动杀后端：工作台可能仍被外部浏览器使用。
  }, 'dayan: host lifetime');
}
