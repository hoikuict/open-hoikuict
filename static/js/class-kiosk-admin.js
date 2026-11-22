'use strict';
(() => {
 const $ = s => document.querySelector(s);
 const esc = v => String(v ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
 let classes = [], devices = [], enrollments = [], view = 'overview', classId = null;
 let draft = {classId:'', name:''}, formError = '', stopId = null, codeId = null;
 let busy = false, refreshing = false, loaded = false, serverOffset = 0, toastTimer;
 // Registration secrets live only in this page's memory, never in local storage.
 const issued = new Map();
 const now = () => Date.now() + serverOffset;
 const name = id => classes.find(c => c.id === Number(id))?.name || '';
 const classDevices = id => devices.filter(d => d.classroom_id === id);
 const enabled = id => classes.find(c => c.id === Number(id))?.enabled;
 const fmt = value => new Intl.DateTimeFormat('ja-JP', {timeZone:'Asia/Tokyo',year:'numeric',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',hour12:false}).format(new Date(value));
 const tag = (text, type='') => `<span class="pill ${type}">${esc(text)}</span>`;
 const heading = (title, text='') => `<p class="breadcrumb">設定 / クラス用スマホ</p><div class="page-heading"><div><h1 tabindex="-1">${esc(title)}</h1>${text ? `<p class="muted">${esc(text)}</p>` : ''}</div></div>`;
 const back = (action='overview', label='クラス一覧に戻る') => `<button class="text-button back" data-action="${action}">${esc(label)}</button>`;
 const error = text => { $('#notice').textContent=text; $('#notice').hidden=!text; };
 function tell(text) { $('#toast').textContent=text; $('#toast').hidden=false; clearTimeout(toastTimer); toastTimer=setTimeout(()=>$('#toast').hidden=true,4000); }
 async function api(path, body) {
  const controller = new AbortController(), timeout = setTimeout(()=>controller.abort(),15000);
  try {
   const r = await fetch('/settings/class-kiosk/'+path, {method:body ? 'POST' : 'GET',cache:'no-store',credentials:'same-origin',signal:controller.signal,
    headers:body ? {'Content-Type':'application/json','X-CSRF-Token':$('meta[name="csrf-token"]').content} : {},body:body ? JSON.stringify(body) : undefined});
   if (r.redirected || r.status === 401) throw new Error('管理者のログインを確認するため、ページを再読み込みしてください。入力はこの画面に残っています。');
   const data = await r.json().catch(()=>null);
   if (!r.ok || !data) throw new Error(typeof data?.detail === 'string' ? data.detail : '処理を確認できませんでした。接続を確認して、もう一度お試しください。');
   if (data.time) serverOffset=Date.parse(data.time)-Date.now();
   return data;
  } catch (e) {
   if (e.name === 'AbortError' || e instanceof TypeError) throw new Error('通信できません。処理結果を確認できていません。接続を確認して、もう一度お試しください。');
   throw e;
  } finally { clearTimeout(timeout); }
 }
 function overview() {
  const active=devices.filter(d=>d.available), ready=classes.filter(c=>classDevices(c.id).some(d=>d.available)).length;
  return heading('クラス用スマホ','登録済みの全クラスから、共用スマホの準備を進めます。')+
   `<div class="metrics"><div class="metric"><span>端末登録済みのクラス</span><strong>${ready}<small>/ ${classes.length}クラス</small></strong></div><div class="metric"><span>利用できる端末</span><strong>${active.length}<small>台</small></strong></div><div class="metric attention"><span>通知が未設定の端末</span><strong>${active.filter(d=>!d.push_enabled).length}<small>台</small></strong></div></div>
   <section class="panel"><div class="panel-heading"><h2>全クラスの登録状況</h2><span class="muted">${classes.length}クラス</span></div>`+
   (classes.length ? `<table class="class-table"><thead><tr><th scope="col">クラス</th><th scope="col">利用できる端末</th><th scope="col">通知設定</th><th scope="col">操作</th></tr></thead><tbody>${classes.map(c=>{
    const all=classDevices(c.id), active=all.filter(d=>d.available), off=all.filter(d=>!d.active).length, unset=active.filter(d=>!d.push_enabled).length;
    return `<tr data-class="${c.id}"><td><span class="class-name">${esc(c.name)}</span><span class="sub">${!c.enabled?'クラス停止中':active.length?'登録済み':!all.length?'未登録':'解除済み'}</span></td><td>${active.length}台${off?`<span class="sub">解除済み ${off}台</span>`:''}</td><td>${active.length ? unset?tag(`未設定 ${unset}台`,'warn'):tag('すべて設定済み','ok') : '<span class="muted">登録後に設定</span>'}</td><td><button data-action="${all.length || !c.enabled?'class':'register'}" data-id="${c.id}" aria-label="${esc(c.name)}の${all.length || !c.enabled?'端末を管理':'端末を登録'}">${all.length || !c.enabled?'端末を管理':'端末を登録'}</button></td></tr>`;
   }).join('')}</tbody></table>` : '<div class="empty"><p>クラスが登録されていません。通常画面の「クラス管理」で登録してください。</p></div>')+
   '<div class="foot-note">通知の「設定済み」は登録された設定の状態です。画面を閉じたときに届くかは、各スマホで確認してください。</div></section><div class="help-row"><p>端末のないクラスも、準備できたタイミングで登録できます。</p><p>端末登録は管理者が解除するまで有効です。</p></div>';
 }
 function notificationGuide() {
  return '<details class="notifications"><summary>スマホで通知を設定・確認する手順</summary><div class="guide"><ol><li>登録したスマホでクラス連絡を開き、「端末」画面へ進みます。</li><li>「通知を有効にする」を押して、通知を許可します。</li><li>テスト通知を送り、画面を閉じた状態でも届くか確認します。</li><li>通知をタップし、登録先クラスの画面が開くことを確認します。</li></ol><p>通知欄・バイブ・画面上への表示を実機で確認してください。管理画面から通知の許可を変更することはできません。</p></div></details>';
 }
 function detail() {
  const list=classDevices(classId), pending=enrollments.filter(e=>e.classroom_id===classId && e.status!=='used');
  return back()+heading(name(classId)+'のスマホ','このクラスの端末登録と通知設定を確認できます。')+
   (enabled(classId)?`<div class="actions"><button class="primary" data-action="register" data-id="${classId}">端末を追加する</button></div>`:'<p class="info warn">このクラスアカウントは停止されています。</p>')+
   `<div class="device-list">${list.length?list.map(d=>`<article class="device-card" data-device="${d.id}"><div class="device-top"><h2>${esc(d.name)}</h2>${tag(!d.active?'解除済み':d.available?'登録中':'クラス停止中',d.available?'ok':'')}</div><dl class="device-meta"><div><dt>登録先クラス</dt><dd>${esc(name(classId))}</dd></div><div><dt>通知設定</dt><dd>${!d.available?'利用対象外':d.push_enabled?tag('設定済み','ok'):tag('未設定','warn')}</dd></div></dl><div class="actions device-actions">${!d.active && enabled(classId)?`<button data-action="reregister" data-id="${d.id}">再登録のQRを発行</button>`:'<span class="muted">通知の到着はスマホで確認</span>'}${d.active?`<button class="danger" data-action="stop" data-id="${d.id}">端末登録を解除</button>`:''}</div></article>`).join(''):'<div class="empty"><h2>登録された端末はありません</h2><p class="muted">共用スマホを手元に用意してから、登録QRを発行してください。</p></div>'}</div>`+
   pending.map(e=>`<div class="pending"><div><b>${esc(e.name)}</b><p>${Date.parse(e.expires_at)<=now()?'登録コードの期限切れ':'スマホでの登録待ち'} · ${fmt(e.expires_at)}まで</p></div><button data-action="${issued.has(e.id)?'code':'reissue'}" data-id="${e.id}">${issued.has(e.id)?'発行したコードを見る':'新しいQRを発行'}</button></div>`).join('')+
   (pending.some(e=>!issued.has(e.id))?'<p class="hint">別の画面で発行したコードは再表示できません。必要な場合は新しいQRを発行してください。</p>':'')+
   notificationGuide()+`<div class="info">出欠の入力・変更の確認は「${esc(name(classId))}」として記録されます。全クラスの変更履歴は閲覧できます。</div>`;
 }
 function form() {
  return back('class-return',name(classId)+'の端末管理に戻る')+heading('端末を登録','クラスと端末名を確認し、スマホを手元に用意してください。')+
   `<div class="steps"><span class="step current">端末情報</span><span class="step">QRを読み取る</span><span class="step">通知を設定</span></div><div class="form-grid"><form id="issue" class="panel form-panel" novalidate><h2>登録する端末</h2><div id="form-error" role="alert" class="error" ${formError?'':'hidden'}>${esc(formError)}</div><label for="classroom">クラス <small>必須</small></label><select id="classroom" name="classroom_id" required><option value="">選んでください</option>${classes.map(c=>`<option value="${c.id}" ${String(c.id)===draft.classId?'selected':''} ${c.enabled?'':'disabled'}>${esc(c.name)}${c.enabled?'':'（停止中）'}</option>`).join('')}</select><label for="device-name">端末名 <small>必須</small></label><input id="device-name" name="name" maxlength="80" required value="${esc(draft.name)}" placeholder="例：クラスのスマホ"><p class="hint">同じクラスに複数台ある場合は、名前で区別してください。</p><div class="info">登録コードは発行から10分間・一度だけ使えます。スマホで読み取ると、このクラスの端末として登録されます。</div><div class="actions"><button type="button" data-action="cancel-form">取消</button><button type="submit" class="primary">登録QRを発行</button></div></form><aside class="guide"><h2>登録前に準備すること</h2><ol><li>園の共用スマホを用意する</li><li>本番のクラス連絡へ接続できることを確認する</li><li>QRを読み取るカメラを開く</li></ol><p>端末登録に有効期限はありません。管理者が解除するまで利用できます。入力だけでは登録コードは発行されません。</p></aside></div>`;
 }
 function codePage() {
  const e=issued.get(codeId); if (!e) return overview();
  const used=e.status==='used', expired=e.status==='expired' || Date.parse(e.expires_at)<=now();
  return back('class-return',name(e.classroom_id)+'の端末管理に戻る')+heading(used?'スマホを登録しました':'登録QR',used?'続いて、登録したスマホで通知を設定してください。':'スマホで読み取って、端末の登録を完了します。')+
   `<div class="steps"><span class="step">端末情報</span><span class="step ${used?'':'current'}">QRを読み取る</span><span class="step ${used?'current':''}">通知を設定</span></div><section class="panel qr-panel">${!used&&!expired&&e.qr?`<div class="qr-visual"><img class="qr-image" src="${esc(e.qr)}" alt="端末登録用QR"><p class="qr-label">登録するスマホで読み取ってください</p></div>`:''}<div class="qr-info">${tag(used?'登録完了':expired?'コードの期限切れ':'スマホでの登録待ち',used?'ok':expired?'bad':'warn')}<h2>${esc(name(e.classroom_id))} · ${esc(e.name)}</h2>${!used&&!expired?`<p class="code">${esc(e.code)}</p><p class="muted">${fmt(e.expires_at)}まで有効 · 一度限り</p><p class="info">QR発行だけでは、端末登録は完了していません。${e.qr?'':'スマホのクラス連絡画面に登録コードを入力してください。'}</p>`:used?'<p>このコードは使用済みです。</p><p class="muted">管理者が端末登録を解除するまで利用できます。</p>':'<p>このコードは使えません。スマホを手元に用意して、もう一度発行してください。</p>'}<div class="actions">${expired&&!used?`<button class="primary" data-action="reissue" data-id="${e.id}">新しいコードを発行する</button>`:''}<button ${used?'class="primary"':''} data-action="class-return">端末の登録状況を見る</button></div></div></section>${used?notificationGuide():''}`;
 }
 function render() {
  $('#main').setAttribute('aria-busy','false');
  $('#main').innerHTML=view==='class'?detail():view==='form'?form():view==='code'?codePage():overview();
 }
 function go(next) { view=next; formError=''; render(); $('#main h1')?.focus({preventScroll:true}); window.scrollTo({top:0}); }
 function beginRegistration(id, deviceName) { classId=id; draft={classId:String(id),name:deviceName || name(id)+'のスマホ'}; go('form'); }
 async function refresh() {
  if (refreshing || busy || (loaded && view==='form') || $('#stop-dialog').open) return;
  refreshing=true;
  try {
   const data=await api('api');
   const changed=JSON.stringify([classes,devices,enrollments])!==JSON.stringify([data.classrooms,data.devices,data.enrollments]);
   classes=data.classrooms; devices=data.devices; enrollments=data.enrollments;
   let codeChanged=false;
   if (view==='code' && issued.has(codeId)) {
    const old=issued.get(codeId), current=await api('enrollments/'+codeId);
    codeChanged=current.status!==old.status;
    issued.set(codeId,{...old,...current});
   }
   // A request started before the user opened a form/dialog must not replace it.
   if (!busy && view!=='form' && !$('#stop-dialog').open && (changed || codeChanged || !loaded)) render();
   loaded=true; error('');
  } catch(e) { error(e.message); if (!loaded) $('#main').innerHTML=heading('クラス用スマホ')+'<button data-action="refresh">もう一度読み込む</button>'; }
  finally { refreshing=false; }
 }
 function setBusy(value) {
  busy=value;
  document.querySelectorAll('button, input, select').forEach(el=>el.disabled=value);
 }
 document.addEventListener('input',e=>{if(e.target.id==='device-name') {draft.name=e.target.value; e.target.removeAttribute('aria-invalid');}});
 document.addEventListener('change',e=>{
  if(e.target.id!=='classroom')return;
  const old=name(draft.classId)+'のスマホ'; draft.classId=e.target.value;
  if(!draft.name || draft.name===old) {draft.name=e.target.value?name(e.target.value)+'のスマホ':''; $('#device-name').value=draft.name;}
  e.target.removeAttribute('aria-invalid');
 });
 document.addEventListener('submit',async e=>{
  if(e.target.id!=='issue')return; e.preventDefault(); if(busy)return;
  formError=!draft.classId?'クラスを選んでください。':!draft.name.trim()?'端末名を入力してください。':draft.name.length>80?'端末名は80文字以内で入力してください。':'';
  if(formError) {$('#form-error').textContent=formError; $('#form-error').hidden=false; const field=!draft.classId?$('#classroom'):$('#device-name'); field.setAttribute('aria-invalid','true'); field.focus(); return;}
  setBusy(true);
  try {
   const data=await api('enrollments',{classroom_id:Number(draft.classId),name:draft.name.trim()});
   issued.set(data.id,data); codeId=data.id; classId=data.classroom_id; enrollments.unshift(data); go('code'); error('');
  } catch(err) {formError=err.message; $('#form-error').textContent=formError; $('#form-error').hidden=false;}
  finally {setBusy(false);}
 });
 $('#stop-dialog').addEventListener('cancel',e=>{if(busy)e.preventDefault();});
 document.addEventListener('click',async e=>{
  const b=e.target.closest('[data-action]'); if(!b || busy)return;
  const a=b.dataset.action, id=Number(b.dataset.id);
  if(a==='refresh') {await refresh(); return;}
  if(!loaded)return;
  if(a==='overview') {go('overview'); await refresh(); return;}
  if(a==='class') {classId=id; go('class'); await refresh(); return;}
  if(a==='class-return' || a==='cancel-form') {draft={classId:String(classId),name:name(classId)+'のスマホ'}; go('class'); await refresh(); return;}
  if(a==='register') {beginRegistration(id); return;}
  if(a==='reregister') {const d=devices.find(d=>d.id===id); if(d)beginRegistration(d.classroom_id,d.name); return;}
  if(a==='reissue') {const item=issued.get(id) || enrollments.find(e=>e.id===id); if(item)beginRegistration(item.classroom_id,item.name); return;}
  if(a==='code') {codeId=id; go('code'); await refresh(); return;}
  if(a==='stop') {
   const d=devices.find(d=>d.id===id); if(!d)return; stopId=id;
   $('#stop-copy').innerHTML=`<div class="dialog-target"><b>${esc(name(d.classroom_id))}</b><p>${esc(d.name)}</p></div>`;
   $('#stop-error').hidden=true; $('#stop-dialog').showModal(); return;
  }
  if(a==='cancel-stop') {$('#stop-dialog').close(); return;}
  if(a==='confirm-stop') {
   setBusy(true);
   try {
    await api('devices/'+stopId+'/revoke',{});
    const d=devices.find(d=>d.id===stopId); if(d) {d.active=false; d.available=false; d.push_enabled=false;}
    $('#stop-dialog').close(); render(); tell('端末登録を解除しました。'); error('');
   } catch(err) {$('#stop-error').textContent=err.message; $('#stop-error').hidden=false;}
   finally {setBusy(false);}
  }
 });
 document.addEventListener('visibilitychange',()=>{if(!document.hidden)refresh();});
 setInterval(()=>{if(!document.hidden)refresh();},5000);
 refresh();
})();
