/** Durable identity for this project's Dayan chat in one DSH profile. */
import { createHash, randomUUID } from 'node:crypto';
import { linkSync, mkdirSync, readFileSync, unlinkSync, writeFileSync } from 'node:fs';
import { join, resolve } from 'node:path';

function pathKey(value) {
  const path = resolve(value).replace(/\\/g, '/').replace(/\/+$/, '');
  return process.platform === 'win32' ? path.toLowerCase() : path;
}

export function projectScopeKey(profileDir, projectRoot) {
  return createHash('sha256').update(pathKey(profileDir) + '\0' + pathKey(projectRoot)).digest('hex');
}

export function reserveProjectSession({ dataDir, projectRoot, profileDir }) {
  if (!profileDir) throw new Error('DSH profile identity unavailable; refusing to bind another conversation');
  const project = pathKey(projectRoot), profile = pathKey(profileDir);
  const profileKey = createHash('sha256').update(profile).digest('hex');
  const key = projectScopeKey(profileDir, projectRoot);
  const directory = join(dataDir, 'integrations', 'dsh', 'project_sessions');
  mkdirSync(directory, { recursive: true });
  const filename = join(directory, key + '.json');
  try {
    readFileSync(filename);
  } catch (error) {
    if (error.code !== 'ENOENT') throw error;
    const record = { schemaVersion: 2, sessionId: 'session-dayan-' + randomUUID(),
      projectRoot: resolve(projectRoot), profileKey, createdAt: new Date().toISOString() };
    const temporary = join(directory, key + '.' + randomUUID() + '.tmp');
    // Publish a complete record without overwriting a concurrent winner.
    writeFileSync(temporary, JSON.stringify(record, null, 2), { flag: 'wx' });
    try { linkSync(temporary, filename); }
    catch (error) { if (error.code !== 'EEXIST') throw error; }
    finally { unlinkSync(temporary); }
  }
  const record = JSON.parse(readFileSync(filename, 'utf8'));
  if (record.schemaVersion !== 2 || record.profileKey !== profileKey || pathKey(record.projectRoot) !== project ||
      !/^session-dayan-[a-f0-9-]{36}$/.test(record.sessionId || '')) {
    throw new Error('Dayan project conversation record mismatch; refusing a fallback conversation');
  }
  return record;
}
