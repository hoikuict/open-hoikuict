/* Keep monthly review request/withdrawal failures beside the operation. */
(() => {
  'use strict';
  const box=document.getElementById('monthly-review-feedback');
  if(!box)return;
  const form=box.closest('form');
  let sending=false;
  form.addEventListener('submit',async event=>{
    const button=event.submitter;
    if(!button || !['in_review','draft'].includes(button.value))return;
    event.preventDefault();
    if(sending)return;
    const data=new FormData(form);data.set(button.name,button.value);
    const buttons=[...form.querySelectorAll('button')], disabled=buttons.map(b=>b.disabled);
    sending=true;buttons.forEach(b=>b.disabled=true);box.hidden=true;
    try {
      const token=document.querySelector('meta[name="csrf-token"]')?.content || '';
      const response=await fetch(form.action,{method:'POST',body:data,credentials:'same-origin',headers:{'X-CSRF-Token':token}});
      const destination=new URL(response.url), expected=new URL(form.action);
      if(response.ok && response.redirected && destination.origin===expected.origin && destination.pathname===expected.pathname.replace(/\/status$/,'')) {
        destination.hash='review-status';
        if(destination.pathname===location.pathname && destination.search===location.search) {
          history.replaceState(null,'',destination.href);window.location.reload();
        } else window.location.assign(destination.href);
        return;
      }
      let message='応答を確認できませんでした。文書を再表示して状態を確認してください。';
      if(response.redirected)message='職員のログインを確認してから、文書を再表示してください。';
      else {
        const result=await response.json().catch(()=>null);
        if(typeof result?.detail==='string')message=result.detail;
      }
      throw new Error(message);
    } catch(error) {
      box.replaceChildren();box.hidden=false;box.dataset.error='true';box.setAttribute('role','alert');
      const title=document.createElement('strong');title.textContent='「'+button.textContent.trim()+'」の完了を確認できませんでした';
      const text=document.createElement('p');text.textContent=error instanceof TypeError ? '通信結果を確認できませんでした。文書を再表示して状態を確認してください。' : error.message;
      const reload=document.createElement('a');reload.href=location.pathname+'#review-status';reload.textContent='文書を再表示して状態を確認する';
      reload.addEventListener('click',event=>{event.preventDefault();window.location.reload();});
      box.append(title,text,reload);box.focus({preventScroll:true});form.scrollIntoView({block:'center'});
    } finally {
      sending=false;buttons.forEach((b,i)=>b.disabled=disabled[i]);
    }
  });
})();
