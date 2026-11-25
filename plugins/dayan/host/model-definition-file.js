/** Read an Agent-authored JSON definition; never evaluate/import its source. */
import { readProjectJson } from './project-json-file.js';

export async function readModelDefinition(path, context) {
  const { value, receipt } = await readProjectJson(path, context, '模型定义');
  return { definition: value, receipt };
}
