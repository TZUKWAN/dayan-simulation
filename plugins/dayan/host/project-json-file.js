/** Read bounded project JSON bytes; never evaluate/import file contents. */
import { open, realpath } from 'node:fs/promises';
import { createHash } from 'node:crypto';
import { extname, isAbsolute, relative, resolve, sep } from 'node:path';

const MAX_BYTES = 16 * 1024 * 1024;
const within = (root, path) => {
  const rel = relative(root, path);
  return rel !== '..' && !rel.startsWith('..' + sep) && !isAbsolute(rel);
};

export async function readProjectJson(path, { projectRoot, cwd }, label) {
  if (typeof path !== 'string' || !path.trim()) throw new Error(label + '须为实际 JSON 文件路径');
  const root = await realpath(projectRoot);
  const base = await realpath(cwd || projectRoot);
  if (!within(root, base)) throw new Error('当前会话目录不在大衍项目内，不能读取' + label);
  const actual = await realpath(resolve(base, path));
  if (!within(root, actual) || extname(actual).toLowerCase() !== '.json')
    throw new Error(label + '只读取大衍项目内的 JSON 文件，不接受越界或外部链接');
  const handle = await open(actual, 'r');
  try {
    const stat = await handle.stat();
    if (!stat.isFile() || stat.size < 1 || stat.size > MAX_BYTES)
      throw new Error(label + '须为 1 字节至 16 MiB 的普通 JSON 文件');
    const chunks = [];
    let size = 0;
    for (;;) {
      const buffer = Buffer.alloc(Math.min(65536, MAX_BYTES + 1 - size));
      const { bytesRead } = await handle.read(buffer);
      if (!bytesRead) break;
      chunks.push(buffer.subarray(0, bytesRead));
      size += bytesRead;
      if (size > MAX_BYTES) throw new Error(label + '超过 16 MiB 传输上限');
    }
    const bytes = Buffer.concat(chunks);
    let value;
    try { value = JSON.parse(new TextDecoder('utf-8', { fatal: true }).decode(bytes).replace(/^\uFEFF/, '')); }
    catch { throw new Error(label + '不是有效 UTF-8 JSON；请用 JSON 序列化保存，空值写 null，布尔值写 true/false，再按原任务提交'); }
    if (!value || typeof value !== 'object' || Array.isArray(value))
      throw new Error(label + '的顶层须为完整对象');
    return { value, receipt: { path: actual, bytes: size, sha256: createHash('sha256').update(bytes).digest('hex') } };
  } finally { await handle.close(); }
}
