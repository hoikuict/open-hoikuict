/* Shared monthly review validation; the server checks the same fields under lock. */
(() => {
  'use strict';
  const missing = context => [
    ...((context.owner_name || '').trim() ? [] : [{key:'@owner',label:'担任名'}]),
    ...(context.review_fields || []).filter(item=>!(context.sheet.fields[item.key]?.body || '').trim()),
  ];
  const editLink = (id,key) => '/plans/monthly-library?'+new URLSearchParams({document_id:id,field:key});
  function renderMissing(box,items,documentId=null) {
    const signature=JSON.stringify([items,documentId]);
    box.hidden=false;box.dataset.error=String(!!items.length);box.setAttribute('role',items.length?'alert':'status');
    if(box.dataset.signature===signature)return;
    box.dataset.signature=signature;box.replaceChildren();
    const title=document.createElement('strong');
    title.textContent=items.length ? `まだレビュー依頼できません（未記入 ${items.length}件）` : '入力がそろいました。もう一度「レビュー依頼」を押してください。';
    box.append(title);
    if(!items.length)return;
    const note=document.createElement('p');note.textContent='計画欄を入力してください。評価・反省、行事・活動は空欄でも依頼できます。';
    const list=document.createElement('ul');
    for(const item of items) {
      const li=document.createElement('li'),link=document.createElement('a');
      link.textContent=item.label+'を入力してください。';
      link.href=documentId ? editLink(documentId,item.key) : '#monthly-owner';
      link.dataset.reviewField=item.key;li.append(link);list.append(li);
    }
    box.append(note,list);
  }
  function message(box,title,body) {
    delete box.dataset.signature;box.hidden=false;box.dataset.error='true';box.setAttribute('role','alert');box.replaceChildren();
    const heading=document.createElement('strong'),text=document.createElement('p');
    heading.textContent=title;text.textContent=body;box.append(heading,text);
  }
  async function request(id,status,version,data=null) {
    const payload=data || new FormData();payload.set('status',status);payload.set('lock_version',version);
    const token=document.querySelector('meta[name="csrf-token"]')?.content || '';
    const response=await fetch(`/plans/documents/${id}/status`,{method:'POST',body:payload,credentials:'same-origin',headers:{'Accept':'application/json','X-CSRF-Token':token}});
    if(response.redirected)throw new Error('職員のログインを確認してから、文書を再表示してください。');
    const result=await response.json().catch(()=>null);
    if(!response.ok) {
      const error=new Error(typeof result?.detail==='string' ? result.detail : '依頼の完了を確認できませんでした。文書を再表示して状態を確認してください。');
      error.detail=result?.detail;throw error;
    }
    if(result?.document_id!==id || result?.status!==status)throw new Error('応答を確認できませんでした。文書を再表示して状態を確認してください。');
    return result;
  }
  function openDetail(id) {
    const destination=`/plans/documents/${id}`;
    if(location.pathname===destination) {history.replaceState(null,'',destination+'#review-status');window.location.reload();}
    else window.location.assign(destination+'#review-status');
  }
  window.MonthlyReview={missing,renderMissing,message,request,openDetail};
  const box=document.getElementById('monthly-review-feedback'),form=box?.closest('form');
  if(!form)return;
  const context=JSON.parse(document.getElementById('monthly-library-boot').textContent);
  let sending=false;
  const focus=()=>{box.focus({preventScroll:true});form.scrollIntoView({block:'center'});};
  form.addEventListener('submit',async event=>{
    const button=event.submitter;
    if(!button || !['in_review','draft'].includes(button.value))return;
    event.preventDefault();if(sending)return;
    const items=missing(context);
    if(button.value==='in_review' && items.length) {renderMissing(box,items,context.document_id);focus();return;}
    const buttons=[...form.querySelectorAll('button')],disabled=buttons.map(b=>b.disabled);
    sending=true;buttons.forEach(b=>b.disabled=true);box.hidden=true;
    try {
      const data=new FormData(form);
      await request(context.document_id,button.value,data.get('lock_version'),data);
      openDetail(context.document_id);
    } catch(error) {
      if(error.detail?.kind==='monthly_review_incomplete')renderMissing(box,error.detail.missing,context.document_id);
      else {
        message(box,'「'+button.textContent.trim()+'」の完了を確認できませんでした',error instanceof TypeError ? '通信結果を確認できませんでした。文書を再表示して状態を確認してください。' : error.message);
        const reload=document.createElement('a');reload.href=location.pathname+'#review-status';reload.textContent='文書を再表示して状態を確認する';
        reload.addEventListener('click',event=>{event.preventDefault();window.location.reload();});box.append(reload);
      }
      focus();
    } finally {sending=false;buttons.forEach((b,i)=>b.disabled=disabled[i]);}
  });
})();
