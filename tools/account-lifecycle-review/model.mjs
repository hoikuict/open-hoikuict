// Isolated, synthetic state only. No database, HTTP or mail integrations.
export const children = Array.from({length:100}, (_, i) => ({id:i+1, name:`架空園児 ${String(i+1).padStart(3,'0')}`, family:String(Math.floor(i/2)+1), classroom:['きいちご','どんぐり','くるみ','うめ','たけ','まつ'][i%6]}));
export function initialState(scenario='stopped') {
  const state = {
    revision:1, accountEnabled:false, credentialEnabled:false, hasPassword:true,
    pending:false, pendingKind:'', emailRemoved:false, requiresReset:false,
    sessions:0, pushDevices:0, passwordVersion:1, originalSessionValid:false,
    profile:{display_name:'見本 さくら',email:'guardian@example.test',phone:'000-0000-0000',home_address:'見本市あおぞら町1-2-3',workplace:'架空の勤務先',workplace_phone:'000-0000-1111',workplace_address:'見本市若葉町4-5-6',registration_verification_name:'ミホン サクラ',registration_verification_name_type:'kana',family_id:'',guardian_link:'none'},
    loginId:'guardian@example.test',childIds:children.slice(0,98).map(c=>c.id),
    history:[{action:'利用停止',reason:'一時的な利用休止（架空の記録）',actor:'見本の管理者'}],
    mail:[], registrationStatus:'completed',
  };
  if(scenario==='active') Object.assign(state,{accountEnabled:true,credentialEnabled:true,sessions:2,pushDevices:2,originalSessionValid:true,history:[]});
  if(scenario==='legacy') state.accountEnabled=true;
  if(scenario==='pending') Object.assign(state,{pending:true,pendingKind:'resume',mail:[{label:'パスワード再設定を伴う利用再開',status:'メールサーバー受付済み（架空）'}]});
  if(scenario==='unregistered'||scenario==='review') Object.assign(state,{accountEnabled:true,credentialEnabled:true,hasPassword:false,registrationStatus:scenario==='review'?'pending_review':'none',history:[]});
  if(scenario==='removed') Object.assign(state,{emailRemoved:true,profile:{...state.profile,email:''}});
  if(scenario==='security') state.requiresReset=true;
  return state;
}
export function statusOf(s) {
  if(s.emailRemoved) return '停止中';
  if(s.pending) return s.pendingKind==='initial'?'初回設定待ち':'再開手続き待ち';
  if(!s.accountEnabled||!s.credentialEnabled) return '停止中';
  if(!s.hasPassword) return s.registrationStatus==='pending_review'?'登録確認待ち':'未登録';
  return '利用中';
}
export function canLogin(s) { return statusOf(s)==='利用中'; }
export function canResume(s) { return statusOf(s)==='停止中'&&s.hasPassword&&!s.emailRemoved&&!s.requiresReset; }
export function transition(s,action,{reason='',revision=s.revision,admin=true,fail=false}={}) {
  if(!admin) throw Error('利用停止・再開は管理者のみ操作できます。');
  if(revision!==s.revision) throw Error('別の操作で状態が変わりました。最新の状態を確認してください。');
  if(!reason.trim()) throw Error('操作理由を入力してください。');
  if(fail) throw Error('保存できませんでした。状態は変更されていません。入力を保持しています。');
  const next=structuredClone(s), status=statusOf(s);
  if(action==='stop') {
    if(status==='停止中') throw Error('既に停止中です。');
    Object.assign(next,{accountEnabled:false,credentialEnabled:false,pending:false,pendingKind:'',sessions:0,pushDevices:0,originalSessionValid:false});
  } else if(action==='resume') {
    if(!canResume(s)) throw Error('このアカウントは通常の利用再開ができません。必要な手続きを確認してください。');
    Object.assign(next,{accountEnabled:true,credentialEnabled:true,sessions:0,pushDevices:0,originalSessionValid:false});
  } else if(action==='reset_resume'||action==='initial') {
    if(s.emailRemoved||!s.profile.email) throw Error('送信先のメールアドレスを確認してください。');
    if(action==='reset_resume'&&(!s.hasPassword||!['停止中','再開手続き待ち'].includes(status))) throw Error('登録済みの停止中アカウントを選んでください。初回登録は別の手続きです。');
    if(action==='initial'&&(s.hasPassword||s.registrationStatus==='pending_review')) throw Error('登録確認を完了してから初回設定を案内してください。');
    Object.assign(next,{pending:true,pendingKind:action==='initial'?'initial':'resume',credentialEnabled:false,accountEnabled:false,sessions:0,pushDevices:0,originalSessionValid:false});
    next.mail.unshift({label:action==='initial'?'初回パスワード設定':'パスワード再設定を伴う利用再開',status:'送信待ち（架空）'});
  } else if(action==='complete') {
    if(!s.pending) throw Error('設定待ちの案内がありません。');
    Object.assign(next,{accountEnabled:true,credentialEnabled:true,hasPassword:true,pending:false,pendingKind:'',requiresReset:false,passwordVersion:s.passwordVersion+1,sessions:0,pushDevices:0,originalSessionValid:false});
  } else if(action==='cancel_pending') {
    if(!s.pending) throw Error('取り消せる手続きはありません。');
    Object.assign(next,{pending:false,pendingKind:'',accountEnabled:false,credentialEnabled:false});
    next.mail=next.mail.map(m=>({...m,status:'送信・コードを取消（架空）'}));
  } else throw Error('未対応の操作です。');
  next.revision++;
  next.history.unshift({action:({stop:'利用停止',resume:'利用再開',reset_resume:'再設定を伴う再開案内',initial:'初回設定案内',complete:'パスワード設定完了',cancel_pending:'再開手続き取消'})[action],reason:reason.trim(),actor:'見本の管理者'});
  return next;
}
