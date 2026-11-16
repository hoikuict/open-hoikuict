(() => {
 'use strict';
 const $=s=>document.querySelector(s),copy=x=>JSON.parse(JSON.stringify(x));
 const esc=x=>String(x??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
 let requests=[],next=1,confirmation=null,visible='annual';
 const latest=key=>requests.filter(r=>r.key===key).at(-1);
 const pending=()=>requests.filter(r=>r.status==='pending');
 const labels={pending:'承認待ち',approved:'承認済み',returned:'差戻し',withdrawn:'取下げ済み',revising:'修正中・再承認が必要'};
 function publish(){
  $('#admin-notification-count').textContent=pending().length;
  window.dispatchEvent(new Event('reflection-review-updated'));
  $('#daily-preview-frame').contentWindow?.postMessage({kind:'reflection-review-updated'},location.origin);
 }
 function show(view){
  visible=view;
  for(const name of ['annual','daily','admin'])$('#'+name+'-view').hidden=name!==view;
  $('#review-workflow').hidden=view!=='review';
  document.querySelectorAll('.workflow-preview-nav button').forEach(button=>button.setAttribute('aria-pressed',String(button.dataset.previewView===view)));
  if(view==='daily'&&!$('#daily-preview-frame').getAttribute('src'))$('#daily-preview-frame').src=$('#daily-preview-frame').dataset.src;
  if(view==='admin')renderAdmin();
  window.scrollTo({top:0,behavior:'instant'});
 }
 function contents(data){return `<div class="workflow-card"><p class="workflow-meta">${esc(data.meta)}</p><div class="workflow-summary">${data.columns.map((label,i)=>`<section><h3>${esc(label)}</h3><div class="workflow-body">${esc(data.values[i].trim()||'未入力')}</div></section>`).join('')}</div></div>`;}
 function openConfirmation(data){
  if(latest(data.key)?.status==='pending'){openRequest(latest(data.key).id,false);return;}
  confirmation=copy(data);show('review');
  $('#review-workflow').innerHTML=`<p class="workflow-kicker">承認依頼の確認</p><h1>${esc(data.title)}</h1><p class="workflow-meta">下書きを保存しました。内容を確認して、管理者へ承認を依頼してください。</p>${contents(data)}<div class="workflow-card"><p>依頼先：この園の管理者</p><p class="workflow-meta">確定すると管理者の「すべての承認待ち」と帳票通知に表示されます。</p><p id="review-confirm-error" class="workflow-error" role="alert"></p><div class="workflow-actions"><button data-workflow-action="back">入力へ戻る</button><button class="primary" data-workflow-action="submit">管理者へ承認を依頼</button></div></div>`;
  $('#review-workflow h1').tabIndex=-1;$('#review-workflow h1').focus();
 }
 function openRequest(id,admin=false){
  const r=requests.find(r=>r.id===id);if(!r)return;
  if(admin)r.read=true;
  show('review');
  $('#review-workflow').innerHTML=`<p class="workflow-kicker">${admin?'管理者の承認確認':'反省の承認状況'}</p><h1>${esc(r.title)}</h1><p class="workflow-state">${labels[r.status]}</p><p class="workflow-meta">依頼者：${esc(r.requester)} / 依頼日時：${r.requestedAt} / 第${r.version}版</p>${contents(r)}${r.comment?`<div class="workflow-card"><strong>${r.status==='returned'?'差戻し理由':'管理者のコメント'}</strong><p class="workflow-body">${esc(r.comment)}</p></div>`:''}<div class="workflow-card">${admin&&r.status==='pending'?'<label for="review-decision-comment">承認コメント・差戻し理由（差戻し時は必須）</label><textarea id="review-decision-comment" class="workflow-comment" maxlength="1000"></textarea>':''}<p id="review-decision-error" class="workflow-error" role="alert"></p><div class="workflow-actions"><button data-workflow-action="${admin?'admin-home':'input'}" data-id="${r.id}">${admin?'管理者の通知へ戻る':'入力画面へ戻る'}</button>${admin&&r.status==='pending'?`<button class="primary" data-workflow-action="approve" data-id="${r.id}">反省を承認する</button><button class="return-action" data-workflow-action="return" data-id="${r.id}">差し戻す</button>`:''}${!admin&&r.status==='pending'?`<button data-workflow-action="withdraw" data-id="${r.id}">承認依頼を取り下げて修正</button><button class="primary" data-workflow-action="admin-open" data-id="${r.id}">管理者の通知を試す</button>`:''}${!admin&&r.status==='approved'?`<button data-workflow-action="revise" data-id="${r.id}">修正して再依頼する</button>`:''}</div></div>`;
  publish();
 }
 function renderAdmin(){
  const rows=pending(),unread=rows.filter(r=>!r.read).length;
  $('#admin-view').innerHTML=`<p class="workflow-kicker">管理者画面の見本</p><h1>職員ポータル</h1><p class="workflow-meta">反省の承認依頼を、既存の承認待ち・帳票通知と同じ場所で確認します。</p><section class="admin-queue"><h2>すべての承認待ち <span class="notification-count">${rows.length}件</span></h2><div class="notification-grid">${rows.map(r=>`<article class="notification-card"><div class="notification-tags"><span>${r.kind==='annual'?'年間指導計画反省':'日案の振り返り'}</span>${!r.read?'<strong>未読</strong>':''}</div><h3>${esc(r.title)}</h3><p>${esc(r.requester)}さんから承認依頼が届いています。</p><button class="primary" data-workflow-action="open-admin-request" data-id="${r.id}">内容を確認</button></article>`).join('')||'<p class="notification-empty">現在、承認待ちの依頼はありません。</p>'}</div></section><section class="workflow-card"><h2>計画文書・児童票の通知 <span class="notification-count">未読 ${unread}件</span></h2>${rows.map(r=>`<article class="notification-card"><div class="notification-tags"><span>反省の承認依頼</span>${!r.read?'<strong>未読</strong>':'既読'}</div><h3>${esc(r.title)}</h3><p>${esc(r.requester)}さんから承認依頼が届いています。</p><button data-workflow-action="open-admin-request" data-id="${r.id}">帳票を確認</button></article>`).join('')||'<p class="notification-empty">新しい承認依頼の通知はありません。</p>'}</section>${requests.some(r=>['approved','returned'].includes(r.status))?`<section class="workflow-card"><h2>入力した職員への結果通知（見本）</h2>${requests.filter(r=>['approved','returned'].includes(r.status)).map(r=>`<p>${esc(r.title)}：${labels[r.status]}${r.comment?' / '+esc(r.comment):''}</p>`).join('')}</section>`:''}`;
 }
 document.addEventListener('click',async event=>{
  const viewButton=event.target.closest('[data-preview-view]');
  if(viewButton){event.preventDefault();show(viewButton.dataset.previewView);if(viewButton.getAttribute('href')==='#annual-reflection-editor')$('#annual-reflection-editor')?.scrollIntoView();return;}
  const button=event.target.closest('[data-workflow-action]');if(!button)return;
  const action=button.dataset.workflowAction,r=requests.find(r=>r.id===Number(button.dataset.id));
  if(action==='back'){show(confirmation.origin);return;}
  if(action==='submit'){
   if(button.disabled)return;
   button.disabled=true;
   await new Promise(resolve=>setTimeout(resolve,180));
   if(window.AnnualMock.reviewError?.()){$('#review-confirm-error').textContent='承認依頼を送れませんでした。内容は保持されています。もう一度お試しください。（確認用のエラー）';button.disabled=false;return;}
   let request=latest(confirmation.key);
   if(request?.status!=='pending'){
    request={...copy(confirmation),id:next++,version:(request?.version||0)+1,status:'pending',read:false,comment:'',requester:'見本の保育士',requestedAt:'2026-10-11 09:30'};requests.push(request);
   }
   openRequest(request.id,false);return;
  }
  if(action==='admin-home'||action==='admin-open'){show('admin');return;}
  if(action==='open-admin-request'){openRequest(r.id,true);return;}
  if(action==='input'){show(r.origin);return;}
  if(action==='approve'||action==='return'){
   if(r?.status!=='pending')return;
   const comment=$('#review-decision-comment').value.trim();
   if(action==='return'&&!comment){$('#review-decision-error').textContent='差戻し理由を入力してください。';return;}
   r.status=action==='approve'?'approved':'returned';r.comment=comment;publish();openRequest(r.id,true);return;
  }
  if(action==='withdraw'||action==='revise'){
   if(!confirm(action==='withdraw'?'この承認依頼を取り下げて、反省を修正しますか？':'修正後は再度承認が必要です。修正を始めますか？'))return;
   r.status=action==='withdraw'?'withdrawn':'revising';publish();show(r.origin);
  }
 });
 window.addEventListener('message',event=>{
  if(event.origin!==location.origin||event.source!==$('#daily-preview-frame').contentWindow)return;
  if(event.data.kind==='daily-preview-height')$('#daily-preview-frame').style.height=Math.max(500,Math.min(30000,event.data.height))+'px';
 });
 window.ReflectionReview={openConfirmation,openRequest:(key)=>{const r=latest(key);if(r)openRequest(r.id,false);},
  status:key=>latest(key)?.status||'draft',label:key=>labels[latest(key)?.status]||'下書き',
  isLocked:key=>['pending','approved'].includes(latest(key)?.status),
  inspect:()=>copy(requests),show,
  reset(){requests=[];confirmation=null;publish();if(visible==='admin')renderAdmin();if(visible==='review')show('annual');}
 };
})();
