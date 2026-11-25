/** Recover only the same real user turn's saved next_action; never alter choices. */
import { isDeepStrictEqual } from 'node:util';
const pending=new WeakMap();
const controls=new Set(['continuation_token','design_id','revise_from','revise_proposal']);
const choices=value=>Object.fromEntries(Object.entries(value).filter(([key])=>!controls.has(key)));
const same=(saved,context)=>saved&&saved.sessionId===context.sessionId&&saved.seq===context.seq&&saved.originalText===context.originalText;

export function recoverPendingDesign(session,context,parameters){
  const saved=pending.get(session);
  if(!same(saved,context))return {arguments:parameters};
  const next=saved.arguments;
  const unchanged=Object.entries(choices(parameters)).every(([key,value])=>
    Object.hasOwn(saved.choices,key)&&isDeepStrictEqual(value,saved.choices[key]));
  const redundant=next.continuation_token&&parameters.continuation_token===next.continuation_token&&
    parameters.design_id===next.design_id&&parameters.revise_from===next.design_id&&parameters.revise_proposal===true&&unchanged;
  const fresh=!['continuation_token','design_id','revise_from','revise_proposal'].some(key=>Object.hasOwn(parameters,key))&&unchanged;
  if(!redundant&&!fresh)return {arguments:parameters};
  return {arguments:structuredClone(next),receipt:{kind:redundant?'redundant_revision_flags':'saved_pending_recovered',
    design_id:next.design_id||null,revise_from:next.revise_from||null,
    preserved_original_request:true,changed_model_choices:false}};
}

export function rememberPendingDesign(session,context,parameters,result){
  const next=result?.payload?.next_action;
  if(next?.action!=='design_model'||!next.arguments||typeof next.arguments!=='object'){
    if(result?.payload?.status==='approved')pending.delete(session);
    return;
  }
  const old=pending.get(session);
  pending.set(session,{...context,arguments:structuredClone(next.arguments),choices:{
    ...(same(old,context)?old.choices:{}),...choices(parameters),...choices(next.arguments)}});
}
