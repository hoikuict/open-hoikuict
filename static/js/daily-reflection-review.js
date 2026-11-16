(() => {
  'use strict';
  const form=document.getElementById('daily-reflection-form');if(!form)return;
  const body=form.elements.reflection_body,version=form.elements.reflection_version,status=document.getElementById('daily-reflection-status');
  let saved=body.value,timer=null,queue=Promise.resolve(),leaving=false,submitting=false;
  const report=(text,error=false)=>{status.textContent=text;status.setAttribute('role',error?'alert':'status');};
  async function save(){
    const text=body.value;
    const response=await fetch(`/plans/documents/${form.dataset.documentId}/reflections`,{method:'POST',credentials:'same-origin',
      headers:{'Content-Type':'application/json','X-CSRF-Token':document.querySelector('meta[name=csrf-token]')?.content||''},
      body:JSON.stringify({entries:[{period:-1,version:Number(version.value),values:[text]}]})});
    if(response.redirected||!response.headers.get('content-type')?.includes('application/json'))throw new Error('ログイン状態を確認してください。入力内容は保持しています。');
    const data=await response.json();
    if(!response.ok)throw new Error(typeof data.detail==='string'?data.detail:'保存できませんでした。入力内容は保持しています。');
    version.value=data['-1'].version;saved=text;report('振り返りの下書きを保存しました。');
  }
  function enqueue(){queue=queue.catch(()=>{}).then(save);return queue;}
  body.addEventListener('input',()=>{
    clearTimeout(timer);report('未保存の変更があります。');
    timer=setTimeout(()=>{if(!submitting)enqueue().catch(e=>report(e.message,true));},1200);
  });
  form.addEventListener('submit',async e=>{
    e.preventDefault();if(submitting)return;submitting=true;clearTimeout(timer);
    const review=e.submitter?.value==='submit';
    if(review&&!body.value.trim()){report('振り返りを入力してください。',true);submitting=false;return;}
    form.querySelectorAll('button').forEach(b=>b.disabled=true);body.readOnly=true;
    try{await enqueue();if(review){leaving=true;location.assign(`/plans/documents/${form.dataset.documentId}/reflections/-1/confirm`);}}
    catch(error){report(error.message,true);}
    finally{form.querySelectorAll('button').forEach(b=>b.disabled=false);body.readOnly=false;submitting=false;}
  });
  window.addEventListener('beforeunload',e=>{if(!leaving&&body.value!==saved){e.preventDefault();e.returnValue='';}});
})();
