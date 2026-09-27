import test from 'node:test';
import assert from 'node:assert/strict';
import {initialState,transition,statusOf,canLogin,canResume} from './model.mjs';
const opts={reason:'架空の操作確認'};
test('stop and ordinary resume preserve password and 98 child links; old sessions and push stay revoked',()=>{
  const s=initialState('active'), stopped=transition(s,'stop',opts), resumed=transition(stopped,'resume',opts);
  assert.equal(statusOf(stopped),'停止中');assert.equal(canLogin(stopped),false);
  assert.equal(statusOf(resumed),'利用中');assert.equal(canLogin(resumed),true);
  assert.deepEqual(resumed.childIds,s.childIds);assert.equal(resumed.childIds.length,98);
  assert.equal(resumed.passwordVersion,s.passwordVersion);
  assert.equal(resumed.originalSessionValid,false);assert.equal(resumed.sessions,0);assert.equal(resumed.pushDevices,0);assert.equal(resumed.mail.length,0);
});
test('legacy active account with disabled credential has one stopped display and can explicitly resume',()=>{
  const s=initialState('legacy');assert.equal(statusOf(s),'停止中');assert.equal(canLogin(s),false);
  assert.equal(statusOf(transition(s,'resume',opts)),'利用中');
});
test('reset-required resume stays blocked until the mock recipient completes setup',()=>{
  const s=initialState('security');assert.equal(canResume(s),false);assert.throws(()=>transition(s,'resume',opts));
  const p=transition(s,'reset_resume',opts);assert.equal(statusOf(p),'再開手続き待ち');assert.equal(canLogin(p),false);
  const r=transition(p,'complete',opts);assert.equal(canLogin(r),true);assert.equal(r.passwordVersion,2);assert.equal(r.originalSessionValid,false);
});
test('cancel pending returns to stopped without restoring login or old codes',()=>{
  const r=transition(initialState('pending'),'cancel_pending',opts);assert.equal(canLogin(r),false);assert.equal(statusOf(r),'停止中');assert.equal(r.pending,false);
});
test('removed email and no initial password cannot use ordinary resume',()=>{
  for(const scene of ['removed','unregistered','review']) assert.throws(()=>transition(initialState(scene),'resume',opts));
  assert.throws(()=>transition(initialState('removed'),'reset_resume',opts));
  assert.throws(()=>transition(initialState('review'),'initial',opts));
  assert.throws(()=>transition(transition(initialState('unregistered'),'stop',opts),'reset_resume',opts));
});
test('validation, access denial, stale confirmation and simulated failures leave state unchanged',()=>{
  for(const extra of [{reason:''},{admin:false},{revision:0},{fail:true}]) {
    const s=initialState('stopped'), copy=structuredClone(s);
    assert.throws(()=>transition(s,'resume',{...opts,...extra}));assert.deepEqual(s,copy);
  }
});
