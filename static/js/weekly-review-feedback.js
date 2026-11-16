/* The editor and document detail use the same review endpoint and requirements. */
(() => {
  'use strict';
  const ownerError = name => (name || '').trim() ? '' : '作成者を入力してください。';
  function message(box, title, body, error=true) {
    delete box.dataset.signature;
    box.hidden=false;box.dataset.error=String(error);box.setAttribute('role',error?'alert':'status');
    const heading=document.createElement('strong'),text=document.createElement('p');
    heading.textContent=title;text.textContent=body;box.replaceChildren(heading,text);
  }
  async function request(id,status,version) {
    const data=new FormData();data.set('status',status);data.set('lock_version',version);
    const token=document.querySelector('meta[name="csrf-token"]')?.content || '';
    const response=await fetch(`/plans/documents/${id}/status`,{method:'POST',body:data,credentials:'same-origin',headers:{Accept:'application/json','X-CSRF-Token':token}});
    if(response.redirected)throw new Error('ログインを確認してから、文書の状態を確認してください。');
    const result=await response.json().catch(()=>null);
    if(!response.ok)throw new Error(typeof result?.detail==='string'?result.detail:'依頼の完了を確認できませんでした。文書の状態を確認してください。');
    if(result?.document_id!==id||result.status!==status||!Number.isInteger(result.lock_version))throw new Error('応答を確認できませんでした。文書の状態を確認してください。');
    return result;
  }
  window.WeeklyReview={ownerError,message,request};
  const box=document.getElementById('weekly-review-feedback'),form=box?.closest('form');
  if(!form)return;
  let sending=false;
  form.addEventListener('submit',async event=>{
    const button=event.submitter;
    if(!button||!['in_review','draft'].includes(button.value))return;
    event.preventDefault();if(sending)return;
    const missing=ownerError(box.dataset.ownerName);
    const show=()=>{box.focus({preventScroll:true});form.scrollIntoView({block:'center'});};
    if(button.value==='in_review'&&missing){
      message(box,'まだレビュー依頼できません',missing);
      const link=document.createElement('a');link.href='/plans/weekly-library?document_id='+box.dataset.documentId;link.textContent='週案を修正する';box.append(link);show();return;
    }
    const buttons=[...form.querySelectorAll('button')],disabled=buttons.map(b=>b.disabled);
    sending=true;buttons.forEach(b=>b.disabled=true);box.hidden=true;
    try {
      await request(Number(box.dataset.documentId),button.value,form.elements.lock_version.value);
      location.hash='review-status';location.reload();
    }catch(error){
      message(box,'「'+button.textContent.trim()+'」の完了を確認できませんでした',error instanceof TypeError?'通信結果を確認できませんでした。文書を再表示して状態を確認してください。':error.message);
      const link=document.createElement('a');link.href=location.pathname+'#review-status';link.textContent='文書を再表示して状態を確認する';link.addEventListener('click',event=>{event.preventDefault();location.reload();});box.append(link);show();
    }finally{sending=false;buttons.forEach((b,i)=>b.disabled=disabled[i]);}
  });
})();
