import {children,initialState,statusOf,canLogin,canResume,transition} from './model.mjs';
const $=id=>document.getElementById(id);
const esc=value=>String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
let state=initialState(),page='auth',profileDraft=structuredClone(state.profile),linksDraft=[...state.childIds],drafts={},pending=null,retry=null;
const labels={display_name:'表示名',email:'メールアドレス',registration_verification_name:'登録照合用氏名',phone:'電話番号',home_address:'現住所',workplace:'勤務先',workplace_phone:'勤務先電話番号',workplace_address:'勤務先住所'};
const badge=()=>`<span class="badge ${statusOf(state)==='利用中'?'active':statusOf(state)==='停止中'?'stopped':'pending'}" data-status>${statusOf(state)}</span>`;
const admin=()=>$('actor').value==='admin';
const preset=()=>$('input-mode').value==='empty'?'':$('input-mode').value==='partial'?'一時的な利用休止のため':'本人からの依頼を確認しました（架空の入力）';
function field(name,label,value='',type='text',required=false,note='') {return `<label class="field">${label}${required?' <span class="small muted">必須</span>':''}<input name="${name}" type="${type}" value="${esc(value)}" ${required?'required':''} ${type==='email'?'maxlength="255"':''}>${note?`<small>${note}</small>`:''}</label>`;}
function reason(kind,label='操作理由') {return `<label class="field">${label} <span class="small muted">必須</span><textarea name="reason" required maxlength="500" rows="3" placeholder="操作の理由を記録してください">${esc(drafts[kind]?.reason??preset())}</textarea></label>`;}
function head(title,description,actions='') {return `<header class="page-head"><div><div class="eyebrow">保護者アカウント</div><h1>${title}</h1><p>${description}</p></div><div class="actions">${actions}</div></header>`;}
const link=(target,label)=>`<a class="button" href="#${target}" data-page="${target}">${label}</a>`;
function summary(){return `<dl class="card summary"><div><dt>保護者</dt><dd><strong>${esc(state.profile.display_name)}</strong><br><span class="small muted">${esc(state.profile.email||'メールアドレス削除済み')}</span></dd></div><div><dt>利用状態</dt><dd>${badge()}</dd></div><div><dt>有効セッション</dt><dd><span class="count">${state.sessions}</span> 件</dd></div></dl>`;}
function lifecycle(){
  const status=statusOf(state), rights=admin()?'':'disabled', permission=admin()?'':'<p class="notice warning">利用停止・再開は管理者に依頼してください。保護者情報の編集は行えます。</p>';
  let body='';
  if(status==='利用中') body=`<p>停止すると、ログイン中の端末と通知登録が無効になります。園児との紐づけ・登録情報は保持されます。</p><form data-kind="stop">${reason('stop','停止理由')}<div class="actions"><button class="danger" ${rights}>利用停止の内容を確認</button></div></form>`;
  else if(state.pending) body=`<div class="notice warning">メールのコードでパスワード設定を完了すると利用できます。それまではログインできません。</div><p>案内の有効期限：発行から24時間。送信状況は下の「メールの配送状況」で確認できます。</p><form data-kind="cancel_pending">${reason('cancel_pending','取消理由')}<div class="actions"><button ${rights}>手続き取消の内容を確認</button></div></form><p class="small muted">取り消すと「停止中」に戻り、発行したコードは使えなくなります。</p>`;
  else if(status==='停止中') {
    if(canResume(state)) body=`<p>現在のパスワードで、保護者が再ログインできるようになります。パスワードの再設定やメール送信は行いません。</p><p class="small muted">停止前のログイン状態・通知登録は復活しません。園児${state.childIds.length}人の紐づけは保持されます。</p><form data-kind="resume">${reason('resume','再開理由')}<div class="actions"><button class="primary" ${rights}>利用再開の内容を確認</button></div></form>`;
    else body=`<div class="notice warning">${state.emailRemoved?'メールアドレスが削除済みのため、この画面から通常の再開はできません。登録情報の復旧手順を管理者が確認してください。':'パスワードの再設定が必要な停止です。下の「パスワード再設定を伴う利用再開」を使ってください。'}</div>`;
    if(!state.emailRemoved) body+=`<details class="details" ${state.requiresReset?'open':''}><summary>パスワード再設定を伴う利用再開</summary><p>パスワードを忘れた場合や、再設定が必要な場合に使います。設定完了まではログインできません。</p><form data-kind="reset_resume">${reason('reset_resume','発行理由')}<div class="actions"><button ${rights}>再開案内の内容を確認</button></div></form></details>`;
  } else body=`<p>${state.registrationStatus==='pending_review'?'初回登録の内容を確認してください。承認後に本人がパスワードを設定すると利用できます。':'初回登録の案内と本人のパスワード設定が必要です。下の「初回登録の案内」から進めてください。'}</p>`;
  return `<section class="card lifecycle ${status==='利用中'?'stop':''}"><h2>利用停止・再開</h2>${permission}${body}</section>`;
}
const childLabels=['子どもの姓','子どもの名','子どもの姓（カナ）','子どもの名（カナ）','生年月日','入園予定日','自宅住所','自宅電話','アレルギー','健康面で伝えたいこと'];
const childValues=['見本','あおい','ミホン','アオイ','2022-04-01','2026-04-01','見本市あおぞら町1-2-3','000-0000-0000','なし（架空）','なし（架空）'];
const guardianLabels=['姓','名','姓（カナ）','名（カナ）','続柄','電話番号','勤務先','勤務先住所','勤務先電話'];
function submitted(){const pairs=childLabels.map((l,i)=>[l,childValues[i]]);[1,2].forEach(i=>guardianLabels.forEach((l,j)=>pairs.push([`保護者${i}・${l}`,i===1?['見本','さくら','ミホン','サクラ','母','000-0000-0000','架空の勤務先','見本市若葉町4-5-6','000-0000-1111'][j]:'未入力'])));return `<dl class="submitted">${pairs.map(([l,v])=>`<div><dt>${l}</dt><dd>${v}</dd></div>`).join('')}</dl>`;}
function registration(){
  const reviewing=state.registrationStatus==='pending_review';
  if(state.registrationStatus==='none') return `<section class="card"><h2>登録申請の履歴</h2><p>登録申請はまだありません。</p></section>`;
  return `<section class="card"><h2>登録申請の履歴</h2><p>初回入力の提出内容と申請状態を確認できます。</p><article class="registration"><div class="row-head"><strong>申請 1</strong><span class="badge">${reviewing?'確認待ち':state.registrationStatus==='rejected'?'却下':'登録完了'}</span></div><p class="small muted">提出：2026-09-20 10:00 JST（架空）</p><p>初回入力の依頼：見本 あおいさん</p>${submitted()}${reviewing?`<form data-kind="review"><label class="field">承認先の園児・保護者<select name="public_child_target" required><option value="">承認する場合は選択してください</option><option value="1:1">架空園児 001 ／ 保護者1</option><option value="new">台帳にいないため、新しい園児・家族を登録する</option></select></label>${reason('review','確認理由')}<label class="check"><input type="checkbox" name="enrollment_confirmed" required>招待先・保護者と園児の対応・入力内容を確認しました。</label><div class="actions"><button name="decision" value="approve" class="primary" ${admin()?'':'disabled'}>承認の内容を確認</button><button name="decision" value="reject" class="danger" ${admin()?'':'disabled'}>却下の内容を確認</button></div></form>`:'<p class="notice success">園児・家族・保護者アカウントに反映済みです（架空の記録）。</p>'}</article></section>`;
}
function authPage(){
  const a=admin()?'':'disabled', current=drafts.login_id||{};
  let email=state.hasPassword?`<section class="card"><h2>登録メール・ログインIDの変更</h2><p>本人確認後に変更します。パスワードは維持されますが、ログイン中の端末・再設定コード・通知登録は失効します。</p><dl class="submitted"><div><dt>現在の登録メール</dt><dd>${esc(state.profile.email||'削除済み')}</dd></div><div><dt>現在のログインID</dt><dd>${esc(state.loginId)}</dd></div></dl><form data-kind="login_id">${field('new_email','新しいメールアドレス／ログインID',current.new_email??($('input-mode').value==='filled'||$('input-mode').value==='error'?'updated@example.test':''),'email',true)}${reason('login_id','本人確認方法と変更理由')}<label class="check"><input type="checkbox" name="confirmed" required ${current.confirmed||(['filled','error'].includes($('input-mode').value)&&!current.reason)?'checked':''}>パスワードは変わらず、次回から新しいメールアドレスでログインすることを確認しました</label><div class="actions"><button ${a}>登録メールとログインIDの変更を確認</button></div></form></section>`:'';
  const init=`<section class="card"><h2>初回登録の案内</h2><p>${state.hasPassword?'初回入力は台帳へ反映済みです。利用停止からの再開は上の「利用停止・再開」で行えます。':'本人情報を入力してもらい、園が確認・承認します。承認後に本人がパスワードを設定します。'}</p><form data-kind="invite">${state.registrationStatus==='none'?field('enrollment_child_name','招待する子どもの名前','見本 あおい','text',true):''}${reason('invite','招待理由')}<div class="actions"><button ${a}>招待・再送の内容を確認</button></div></form></section>`;
  const initialCode=!state.hasPassword&&!state.pending&&state.registrationStatus!=='pending_review'?`<section class="card"><h2>初回パスワード設定</h2><p>本人確認後にコードを発行し、登録メールへ案内します。コードは24時間有効です。</p><form data-kind="initial">${reason('initial','発行理由')}<div class="actions"><button ${a}>初回設定案内の内容を確認</button></div></form></section>`:'';
  const reset=statusOf(state)==='利用中'?`<section class="card"><h2>パスワード再設定</h2><p>本人確認後に再設定コードを登録メールへ送ります。設定完了後に新しいパスワードでログインします。</p><form data-kind="password_reset">${reason('password_reset','再設定理由')}<div class="actions"><button ${a}>再設定案内の内容を確認</button></div></form></section>`:'';
  return head('認証管理',`${esc(state.profile.display_name)}さんの利用状態・本人確認・パスワードを管理します。`,link('edit','保護者情報を編集')+link('list','一覧へ戻る'))+summary()+lifecycle()+email+init+initialCode+`<section class="card"><h2>メールの配送状況</h2><p>直近20件。受付後の到着は受信者が確認します。</p>${state.mail.length?state.mail.map(m=>`<div class="history-row"><strong>${esc(m.label)}</strong><p>${esc(m.status)} ／ 宛先：${esc(state.profile.email)}</p></div>`).join(''):'<p class="muted">このモックで発行した案内はありません。</p>'}</section>`+registration()+reset+`<section class="card"><h2>利用停止・再開の履歴</h2>${state.history.length?state.history.map(h=>`<div class="history-row"><strong>${h.action}</strong><p>${esc(h.reason)} ／ ${h.actor}</p></div>`).join(''):'<p>操作履歴はありません。</p>'}</section>`;
}
function editPage(){
  const p=profileDraft, fields=[field('display_name','表示名',p.display_name,'text',true,'家族と紐付ける場合は姓と名をスペースで区切ってください。'),field('email','メールアドレス',p.email,'email',true,'連絡先として使います。ログインID変更は「認証管理」で行います。'),field('registration_verification_name','登録照合用氏名',p.registration_verification_name,'text',false,'日本人はカナ、外国人は本人確認済みの英字表記を登録します。'),`<label class="field">照合表記<select name="registration_verification_name_type">${[['','未設定'],['kana','カナ'],['latin','英字']].map(([v,l])=>`<option value="${v}" ${p.registration_verification_name_type===v?'selected':''}>${l}</option>`).join('')}</select></label>`,...['phone','home_address','workplace','workplace_phone','workplace_address'].map(n=>field(n,labels[n],p[n]))];
  return `<div class="narrow">${head('保護者情報を編集','氏名・連絡先・勤務先と、園児の閲覧許可を編集します。',link('list','一覧へ戻る'))}<div class="notice"><div class="row-head"><span>利用状態：${badge()}</span>${link('auth','利用停止・再開は認証管理へ')}</div><p>この画面で連絡先や家族を変更しても、利用状態は変わりません。</p></div><form id="profile-form" data-kind="profile" class="card"><div class="notice"><label class="field">家族プロフィールの保護者と紐付ける<select name="guardian_link"><option value="none" ${p.guardian_link==='none'?'selected':''}>紐付けなし</option><option value="1:1" ${p.guardian_link==='1:1'?'selected':''}>見本家 ／ 見本 さくら（母）</option></select><small>選ぶと入力済み情報を取り込みます。園児の閲覧許可は下のチェック欄で確認してください。</small></label></div><div class="form-grid">${fields.join('')}<div class="field">状態<div class="readonly">${badge()}<br><span class="small muted">認証管理で変更します</span></div></div><label class="field">所属家族<select name="family_id"><option value="">未設定</option>${[['1','見本家 ／ 架空園児 001、002'],['2','若葉家 ／ 架空園児 003、004']].map(([v,l])=>`<option value="${v}" ${p.family_id===v?'selected':''}>${l}</option>`).join('')}</select></label></div><fieldset><legend>閲覧を許可する園児（明示的な紐付け）</legend><p class="small muted">家族の紐づけと閲覧許可は別です。チェックした園児だけを閲覧できます。</p><button type="button" id="select-family" class="plain">この家族の園児をまとめて選択</button><p class="children-count">チェック済み <strong class="target-count">${linksDraft.length}</strong> 人 ／ 全100人</p><div class="children">${children.map(c=>`<label ${p.family_id&&p.family_id!==c.family&&!linksDraft.includes(c.id)?'hidden':''}><input type="checkbox" name="child_ids" value="${c.id}" ${linksDraft.includes(c.id)?'checked':''}>${c.name} ／ ${c.classroom}</label>`).join('')}</div></fieldset><div class="actions"><button class="primary">更新内容を確認</button><button type="button" id="cancel-edit">キャンセル</button></div></form></div>`;
}
function listPage(){return head('保護者アカウント','一覧・編集・認証管理で同じ利用状態を表示します。')+`<section class="card"><div class="table-wrap"><table><thead><tr><th>保護者</th><th>メール</th><th>利用状態</th><th>所属家族</th><th>紐づく園児</th><th>最終ログイン</th><th>操作</th></tr></thead><tbody><tr><td><strong>${esc(state.profile.display_name)}</strong><p class="small muted">${esc(state.profile.phone)}<br>${esc(state.profile.home_address)}<br>勤務先：${esc(state.profile.workplace)}</p></td><td>${esc(state.profile.email||'削除済み')}</td><td>${badge()}</td><td>${state.profile.family_id?'見本家':'未設定'}</td><td><details><summary>${state.childIds.length} 人</summary>${children.filter(c=>state.childIds.includes(c.id)).map(c=>c.name).join('<br>')}</details></td><td>2026-09-20<br>10:00 JST<br><span class="small muted">架空の記録</span></td><td><div class="actions">${link('edit','編集')}${link('auth','認証管理')}</div></td></tr></tbody></table></div></section><p class="small muted">「有効なのにログインできない」という別々の状態表示をなくす案です。</p>`;}
const candidates=[
 ['今回の対象','保護者の利用停止・再開','編集画面の状態と、認証管理の停止が別々に残る。','認証管理へ操作を集約し、一覧・編集・園児詳細も同じ利用状態を表示する。'],
 ['同時に扱う必要あり','CSVからのアカウント状態変更','保護者CSVは状態を書き換えるが、画面の停止処理を呼ばない。','通常の台帳CSVでは既存アカウントの利用状態変更を受け付けず、認証管理へ案内する案。一括停止が必要なら専用の確認画面と共通処理を設ける。'],
 ['次の候補・未確定','職員の利用停止・再開','一覧の「一覧から削除」と編集の「有効」、認証管理の有効化に操作が分かれている。','職員も認証管理へ集約。「一覧から削除」を利用停止と同じ表現に揃える。最後の管理者を止めない制限は維持する。'],
 ['次の候補・未確定','登録メールとログインIDの変更','保護者情報・家族情報・保護者本人の画面で連絡先だけを変更でき、認証管理ではログインIDも変更する。','「連絡先メール」と「ログインID」の名前を明確にし、ログインに関わる変更を認証管理へ。二つのアドレスを自動的に同じ値へ上書きする案ではない。'],
 ['次の候補・未確定','初回招待・再招待・パスワード設定の案内','新規登録、在園児への初回入力、既存アカウントの再招待と再開が並ぶ。','園児からの入口は残し、選んだ人の状態に応じて共通の認証管理へ引き継ぐ。「初回」と「再開」を分ける。'],
 ['既に整理済み／維持','職員権限と家族・園児の共有情報','職員の権限は権限設定へ集約済み。家族と園児には場面に応じた編集入口がある。','同じ処理・同じ保存内容であれば複数の入口は残す。家族の所属と園児の閲覧許可、家庭のアーカイブと利用停止も別の操作として保つ。'],
];
function auditPage(){return head('一本化候補の整理','現行の配備版のコードを基準にした一次調査です。停止・再開以外はまだ変更範囲を確定していません。',link('auth','モックへ戻る'))+candidates.map(([tag,title,problem,proposal])=>`<section class="card audit-card"><div class="priority">${tag}</div><h3>${title}</h3><p>${problem}</p><p><strong>整理案：</strong>${proposal}</p></section>`).join('');}
function render(){
  $('app').innerHTML=({auth:authPage,edit:editPage,list:listPage,audit:auditPage})[page]();
  document.querySelectorAll('[data-page]').forEach(a=>{if(a.dataset.page===page)a.setAttribute('aria-current','page');else a.removeAttribute('aria-current');});
  $('complete-password').hidden=!state.pending;
  $('review-result').textContent=`現在：${statusOf(state)}。通常の再開はパスワードを維持し、過去のログイン状態・通知登録は復活させません。`;
}
function feedback(message,error=false){$('feedback').hidden=false;$('feedback').className=`notice ${error?'error':'success'}`;$('feedback').setAttribute('role',error?'alert':'status');$('feedback').textContent=message;}
function captureProfile(form){new FormData(form).forEach((v,k)=>{if(k!=='child_ids')profileDraft[k]=String(v);});linksDraft=Array.from(form.querySelectorAll('[name="child_ids"]:checked'),x=>Number(x.value));}
function confirmation(kind,values){
  const copy=structuredClone(values), n=state.childIds.length;
  const descriptions={stop:['利用を停止しますか？',`ログイン中の${state.sessions}件のセッション、${state.pushDevices}件の通知登録、未完了の再設定コードを失効させます。園児${n}人の紐づけと登録情報は保持します。`,'利用を停止する'],resume:['利用を再開しますか？',`現在のパスワードを維持し、保護者が再ログインできるようにします。園児${n}人の閲覧許可を維持します。停止前のセッション・通知登録は復活しません。メールは送信しません。`,'利用を再開する'],reset_resume:['再設定を伴う再開案内を送りますか？','登録メールにコードを送信する想定です。パスワード設定の完了までは「再開手続き待ち」で、ログインできません。','再開案内を送信する'],initial:['初回設定の案内を送りますか？','本人がパスワードを設定するまで利用開始になりません。','初回設定案内を送信する'],cancel_pending:['手続きを取り消しますか？','案内済みのコードを無効にし、「停止中」に戻します。','手続きを取り消す'],profile:['保護者情報を更新しますか？',`利用状態は${statusOf(state)}のままです。閲覧を許可する園児は${values.childIds?.length??n}人です。`,'更新する'],login_id:['登録メールとログインIDを変更しますか？',`新しいメール：${values.new_email||''}。パスワードは維持し、現在のログインと通知登録を失効させます。`,'変更する'],invite:['招待を送信・再送しますか？','以前の招待と未承認の提出内容を取り消し、初回登録の案内を送る想定です。','招待を送信する'],password_reset:['パスワード再設定を案内しますか？','発行だけでは利用状態は変わりません。本人による設定完了後、過去のログインと通知登録が失効します。','再設定案内を送信する'],review:[values.decision==='approve'?'登録申請を承認しますか？':'登録申請を却下しますか？','提出内容と対象を確認した結果を保存する想定です。','確認結果を保存する']};
  const [title,description,button]=descriptions[kind];pending={kind,values:copy,revision:state.revision};
  $('confirm-title').textContent=title;$('confirm-body').innerHTML=`<p>${esc(description)}</p>${values.reason?`<div class="notice"><strong>理由</strong><p>${esc(values.reason)}</p></div>`:''}<p class="small muted">モック内でのみ反映されます。本番の保存・送信は行いません。</p>`;$('execute').textContent=button;$('confirmation').showModal();
}
function execute(simulateFailure=$('input-mode').value==='error'){
  const task=pending;if(!task)return;
  try{
    if(task.revision!==state.revision)throw Error('状態が変わりました。最新の状態を確認してください。');
    if(task.kind!=='profile'&&!admin())throw Error('この操作は管理者のみ可能です。');
    if(simulateFailure)throw Error('保存できませんでした。状態は変更されていません。入力を保持しています。「再試行」で成功時の動作を試せます。');
    if(['stop','resume','reset_resume','initial','cancel_pending'].includes(task.kind)) state=transition(state,task.kind,{reason:task.values.reason,revision:task.revision,admin:admin()});
    else {
      const next=structuredClone(state);next.revision++;
      if(task.kind==='profile') {next.profile=task.values.profile;next.childIds=task.values.childIds;}
      if(task.kind==='login_id'){next.profile.email=task.values.new_email;next.loginId=task.values.new_email;next.sessions=0;next.pushDevices=0;next.originalSessionValid=false;}
      if(['invite','password_reset'].includes(task.kind))next.mail.unshift({label:task.kind==='invite'?'初回登録の招待':'パスワード再設定',status:'送信待ち（架空）'});
      if(task.kind==='invite')next.registrationStatus='none';
      if(task.kind==='review'){next.registrationStatus=task.values.decision==='approve'?'completed':'rejected';if(task.values.decision==='approve'){next.pending=true;next.pendingKind='initial';next.accountEnabled=false;next.credentialEnabled=false;}}
      state=next;
    }
    profileDraft=structuredClone(state.profile);linksDraft=[...state.childIds];delete drafts[task.kind];retry=null;pending=null;
    $('confirmation').close();render();feedback(`モック内で反映しました。現在の利用状態：${statusOf(state)}。`);
  }catch(error){retry=task;pending=null;$('confirmation').close();feedback(error.message,true);const button=document.createElement('button');button.type='button';button.textContent='再試行（成功時を試す）';button.id='retry';button.addEventListener('click',()=>{pending=retry;execute(false);});$('feedback').append(document.createElement('br'),button);}
}
document.addEventListener('click',e=>{
  const a=e.target.closest('[data-page]');if(a){e.preventDefault();if(page==='edit'&&$('profile-form'))captureProfile($('profile-form'));page=a.dataset.page;$('feedback').hidden=true;render();window.scrollTo({top:0});}
  if(e.target.id==='select-family'){captureProfile($('profile-form'));if(!profileDraft.family_id){feedback('先に所属家族を選んでください。',true);return;}linksDraft=[...new Set([...linksDraft,...children.filter(c=>c.family===profileDraft.family_id).map(c=>c.id)])];render();}
  if(e.target.id==='cancel-edit'){profileDraft=structuredClone(state.profile);linksDraft=[...state.childIds];page='list';render();feedback('今回の編集を取り消しました。保存済みの内容は変わりません。');}
});
document.addEventListener('input',e=>{const form=e.target.closest('form[data-kind]');if(!form)return;const k=form.dataset.kind;if(k==='profile'){captureProfile(form);const count=document.querySelector('.target-count');if(count)count.textContent=linksDraft.length;}else drafts[k]=Object.fromEntries(new FormData(form));});
document.addEventListener('change',e=>{if(e.target.name==='guardian_link'){captureProfile($('profile-form'));if(profileDraft.guardian_link==='1:1'){profileDraft.family_id='1';profileDraft.display_name='見本 さくら';}render();}else if(e.target.name==='family_id'){captureProfile($('profile-form'));render();}});
document.addEventListener('submit',e=>{
  const form=e.target.closest('form[data-kind]');if(!form)return;e.preventDefault();const kind=form.dataset.kind;
  if(kind==='profile'){captureProfile(form);confirmation(kind,{profile:structuredClone(profileDraft),childIds:[...linksDraft]});return;}
  const values=Object.fromEntries(new FormData(form));values.decision=e.submitter?.value||'';
  if(!String(values.reason||'').trim()){feedback('操作理由を入力してください。',true);return;}
  confirmation(kind,values);
});
$('execute').addEventListener('click',()=>execute());$('back-to-form').addEventListener('click',()=>{pending=null;$('confirmation').close();});$('confirmation').addEventListener('cancel',()=>{pending=null;});
function reset(){state=initialState($('scenario').value);profileDraft=structuredClone(state.profile);linksDraft=[...state.childIds];drafts={};pending=null;retry=null;$('confirmation').close();$('feedback').hidden=true;$('review-result').textContent='通常の再開はパスワードを維持します。過去のログイン状態・通知登録は復活しません。';render();}
$('scenario').addEventListener('change',reset);$('reset').addEventListener('click',reset);$('actor').addEventListener('change',()=>{pending=null;$('confirmation').close();render();});$('input-mode').addEventListener('change',()=>{drafts={};pending=null;retry=null;$('confirmation').close();$('feedback').hidden=true;render();});
$('simulate-login').addEventListener('click',()=>{$('review-result').textContent=canLogin(state)?`再ログイン成功の想定です。現在のパスワードで園児${state.childIds.length}人にアクセスできます。停止前のセッションは無効のままです。`:`ログインは拒否されます。利用状態：${statusOf(state)}。`;});
$('complete-password').addEventListener('click',()=>{state=transition(state,'complete',{reason:'受信者が新しいパスワード設定を完了（モック）'});render();feedback('本人によるパスワード設定完了を再現しました。再ログインできます。');});
$('show-candidates').addEventListener('click',()=>{page='audit';render();window.scrollTo({top:0});});
render();
