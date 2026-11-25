/** Real loopback listener fixture, not a mocked simulation or live LLM. */
import test from 'node:test';
import assert from 'node:assert/strict';
import {createServer} from 'node:http';
import {mkdtemp,readdir,rm} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join} from 'node:path';

test('occupied unhealthy backend port never launches another process',{timeout:10000},async()=>{
  const directory=await mkdtemp(join(tmpdir(),'dayan-start-'));
  const listener=createServer((_req,res)=>{res.writeHead(200,{'content-type':'application/json'});res.end('{"service":"explicit unrelated listener fixture"}');});
  await new Promise(resolve=>listener.listen(0,'127.0.0.1',resolve));
  process.env.DAYAN_BACKEND_URL=`http://127.0.0.1:${listener.address().port}`;
  process.env.DAYAN_DATA_DIR=directory;
  try{
    const {ensureBackend}=await import('../plugins/dayan/host/tools.js');
    await assert.rejects(ensureBackend({timeoutMs:100}),/already occupied.*no competing process/);
    assert.deepEqual(await readdir(directory),[],'No process log, token or data should be created');
  }finally{
    await new Promise(resolve=>listener.close(resolve));
    await rm(directory,{recursive:true,force:true});
  }
});
