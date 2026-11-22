export function installMeetingLifecycle({noteId, initial, adapter}) {
  const $ = id => document.getElementById(id);
  let state=initial, busy=false, uncertain=false, action=null;
  const dialog=$('meeting-lifecycle-dialog');
  const names={archive:'アーカイブする',restore:'通常に戻す',trash:'ごみ箱へ移動',untrash:'アーカイブ済みに戻す'};
  const csrf=()=>document.querySelector('meta[name="csrf-token"]')?.content||'';
  const error=(text,inDialog=false)=>{const el=$(inDialog?'meeting-lifecycle-dialog-error':'meeting-lifecycle-error');el.textContent=text;el.hidden=false;};
  const date=value=>new Date(value).toLocaleString('ja-JP',{timeZone:'Asia/Tokyo',hour12:false})+' JST';
  function render() {
    $('meeting-state-label').textContent=state.label;
    $('meeting-state-help').textContent=state.status==='active'?'アーカイブすると、全職員の通常一覧から外れます。過去の記録として閲覧できます。':state.status==='archived'?'過去の参照用に保持しています。修正する場合は「通常に戻す」を選んでください。':'管理者のごみ箱に移動した議事録です。復元するとアーカイブ済みに戻ります。';
    const actions=$('meeting-lifecycle-actions');actions.replaceChildren();
    if(!uncertain)for(const name of state.allowed_actions){const b=document.createElement('button');b.type='button';b.dataset.lifecycleAction=name;b.textContent=names[name];if(name==='trash')b.className='text-rose-700';b.onclick=()=>confirm(name);actions.append(b);}
    $('meeting-relations-label').textContent='関連する記録：'+state.related.length+'件';
    const related=$('meeting-relations');related.replaceChildren();
    for(const r of state.related){const el=document.createElement(r.url?'a':'p');el.textContent=r.label;if(r.url)el.href=r.url;related.append(el);}
    if(!state.related.length)related.textContent='関連する記録はありません。';
    const history=$('meeting-action-history');history.replaceChildren();
    for(const h of state.history){const li=document.createElement('li');li.textContent=h.action+' / '+h.actor+' / '+date(h.at)+(h.reason?' — '+h.reason:'');history.append(li);}
    if(!state.history.length){const li=document.createElement('li');li.textContent='まだ状態を変更していません。';history.append(li);}
    $('meeting-lifecycle-unknown').hidden=!uncertain;
    $('meeting-lifecycle-recovery').hidden=!(adapter.dirty()&&state.status!=='active');
    $('meeting-resume-draft').hidden=!state.allowed_actions.includes('restore');
    adapter.lock(state.status!=='active'||uncertain||busy);
  }
  async function request(url,options={}) {
    const controller=new AbortController(),timeout=setTimeout(()=>controller.abort(),15000);
    try{const response=await fetch(url,{cache:'no-store',...options,signal:controller.signal});const data=await response.json();return {response,data};}finally{clearTimeout(timeout);}
  }
  async function refresh() {
    try{
      const {response,data}=await request(`/meeting-notes/api/${noteId}/lifecycle`);
      if(!response.ok){if(response.status===404||response.status===403){adapter.lock(true);error('この議事録は表示できません。管理者に確認してください。');$('meeting-lifecycle-actions').replaceChildren();return false;}throw new Error(data.detail||'状態を確認できませんでした。');}
      const changed=data.version!==state.version;
      state=data;uncertain=false;render();
      if(changed&&state.status==='active'&&!adapter.dirty())location.reload();
      return true;
    }catch(e){error('状態を確認できませんでした。接続を確認して再表示してください。');return false;}
  }
  function pendingMarkings(){return [...document.querySelectorAll('#markings input:not([type=hidden]):not([type=number]):not([type=date]),#markings textarea')].some(el=>el.value.trim());}
  function confirm(name) {
    if(busy||uncertain||!state.allowed_actions.includes(name))return;
    action=name;$('meeting-lifecycle-title').textContent=names[name]+'操作を確認';$('meeting-lifecycle-note').textContent=adapter.title()||'無題の議事録';
    const blocked=name==='trash'&&state.related.length>0;
    $('meeting-lifecycle-description').textContent=blocked?'関連する記録があるため、ごみ箱へ移動できません。参照元の議事録をアーカイブ済みのまま保持してください。':({archive:'未保存の本文を保存してからアーカイブします。全職員の通常一覧から外れ、閲覧専用になります。あとから通常に戻せます。',restore:'通常一覧に戻し、編集できるようにします。',trash:'管理者のごみ箱へ移動します。あとから復元できます。完全削除はしません。',untrash:'アーカイブ済み一覧に戻します。本文は閲覧専用のままです。'})[name];
    const list=$('meeting-lifecycle-related');list.replaceChildren();if(blocked)for(const r of state.related){const p=document.createElement('p');p.textContent=r.label;list.append(p);}
    $('meeting-reason-label').hidden=name!=='trash'||blocked;$('meeting-delete-reason').value='';$('meeting-lifecycle-dialog-error').hidden=true;
    $('meeting-lifecycle-confirm').hidden=Boolean(blocked);$('meeting-lifecycle-confirm').textContent=name==='archive'?'保存してアーカイブ':names[name];$('meeting-lifecycle-confirm').disabled=false;
    dialog.showModal();
  }
  async function execute(){
    if(busy||!action)return;
    const operation=action;
    if(operation==='archive'&&pendingMarkings()){error('入力途中のマーキング・コメント・昇格欄があります。キャンセルして各欄の処理を済ませてください。',true);return;}
    busy=true;$('meeting-lifecycle-confirm').disabled=true;$('meeting-lifecycle-cancel').disabled=true;
    let posted=false;
    try{
      if(operation==='archive')await adapter.save();
      adapter.lock(true);
      const expectedRevision=operation==='archive'?adapter.revision():state.revision;
      posted=true;
      const {response,data}=await request(`/meeting-notes/api/${noteId}/lifecycle/${operation}`,{method:'POST',headers:{'Content-Type':'application/json','X-CSRF-Token':csrf()},body:JSON.stringify({expected_version:state.version,expected_revision:expectedRevision,reason:$('meeting-delete-reason').value})});
      if(!response.ok){posted=false;throw new Error(typeof data.detail==='string'?data.detail:'操作に失敗しました。再表示して確認してください。');}
      state=data;busy=false;dialog.close();
      if(operation==='restore'&&adapter.dirty()){
        await adapter.resume(data);render();error('通常に戻しました。保持していた未保存の入力を確認して保存してください。');
      }else{location.assign(`/meeting-notes/?state=${encodeURIComponent(state.status)}`);}
    }catch(e){
      busy=false;
      if(posted){uncertain=true;dialog.close();render();}
      else{error(e.message||'保存できませんでした。入力を保持しています。',true);await refresh();}
    }finally{busy=false;$('meeting-lifecycle-confirm').disabled=false;$('meeting-lifecycle-cancel').disabled=false;}
  }
  $('meeting-lifecycle-confirm').onclick=execute;$('meeting-lifecycle-cancel').onclick=()=>dialog.close();dialog.addEventListener('cancel',e=>{if(busy)e.preventDefault();});
  $('meeting-check-state').onclick=refresh;$('meeting-resume-draft').onclick=()=>confirm('restore');$('meeting-download-draft').onclick=()=>adapter.download();
  render();
  // The socket notifies immediately; periodic reads also cover dropped sockets
  // and deployments with more than one worker. Never replace a pending draft.
  const timer=setInterval(()=>{if(!busy&&!uncertain&&document.visibilityState==='visible')refresh();},5000);
  window.addEventListener('pagehide',()=>clearInterval(timer),{once:true});
  return {refresh, changed(){adapter.lock(true);return refresh();}, locked:()=>state.status!=='active'||uncertain};
}
