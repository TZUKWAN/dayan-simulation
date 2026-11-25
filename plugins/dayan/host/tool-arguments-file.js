/** Bind an Agent-authored JSON envelope to exactly one native platform tool. */
import { readProjectJson } from './project-json-file.js';

export async function readToolArguments(path, context, tool) {
  const { value, receipt } = await readProjectJson(path, context, '工具参数文件');
  if (Object.keys(value).length !== 2 || !Object.hasOwn(value, 'tool') || !Object.hasOwn(value, 'arguments'))
    throw new Error('工具参数文件须为 {"tool":"实际工具名","arguments":{完整参数}}，不接受额外字段');
  if (typeof tool !== 'string' || !tool || value.tool !== tool)
    throw new Error('工具参数文件的 tool 与本次 execute.tool 不一致，未执行；请按原任务核对');
  if (!value.arguments || typeof value.arguments !== 'object' || Array.isArray(value.arguments))
    throw new Error('工具参数文件的 arguments 须为完整参数对象');
  return { arguments: value.arguments, receipt: { ...receipt, tool } };
}
