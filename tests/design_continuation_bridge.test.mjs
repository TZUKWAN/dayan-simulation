import test from 'node:test';
import assert from 'node:assert/strict';
import { recoverPendingDesign,rememberPendingDesign } from '../plugins/dayan/host/design-continuation.js';
const context={sessionId:'test-session',seq:1,originalText:'原始128人需求'};
const next={continuation_token:'test-only-token',design_id:'test-design'};
function state(){const session={};rememberPendingDesign(session,context,{ticks:24,parameters:{n:128}},
  {ok:true,payload:{status:'pending',next_action:{action:'design_model',arguments:next}}});return session;}
test('same-turn redundant revision flags and accidental restart recover the real saved action',()=>{
  const session=state();
  for(const args of [{...next,revise_from:next.design_id,revise_proposal:true},{ticks:24,parameters:{n:128}},{}]){
    const result=recoverPendingDesign(session,context,args);
    assert.deepEqual(result.arguments,next);assert.equal(result.receipt.changed_model_choices,false);
  }
});
test('changed values, other user turns and other conversations are never silently resumed',()=>{
  const session=state();
  for(const [owner,ctx,args] of [[session,context,{ticks:25}],[session,context,{parameters:{n:64}}],
    [session,{...context,seq:2},{}],[{},context,{}],[session,{...context,originalText:'另一个问题'},{}]]){
    const result=recoverPendingDesign(owner,ctx,args);assert.deepEqual(result.arguments,args);assert.equal(result.receipt,undefined);
  }
});
test('approved completion releases pending state',()=>{
  const session=state();rememberPendingDesign(session,context,next,{ok:true,payload:{status:'approved'}});
  assert.deepEqual(recoverPendingDesign(session,context,{}),{arguments:{}});
});
