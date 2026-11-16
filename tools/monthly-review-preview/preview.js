/* Offline prototype: no real API, database, notification or form submission. */
(() => {
  'use strict';
  const config=JSON.parse(document.getElementById('preview-data').textContent), copy=structuredClone;
  const q=s=>document.querySelector(s), all=s=>[...document.querySelectorAll(s)];
  const key=age=>'monthly-review-button-r1:'+age;
  const adapter=()=>window.MonthlyPreviewAdapter;
  let ready=false,state='partial',lastAction=null,failed=false,notice=null;
  const note=text=>{q('#preview-status').textContent=text;};
  function stored(age){try{return JSON.parse(sessionStorage.getItem(key(age))||'null');}catch{return null;}}
  function persist(context,status='draft') {
    const value=copy(context);value.document_id=9000+Number(value.age);value.status=status==='in_review'?'レビュー待ち':'下書き';value.editable=status!=='in_review';
    sessionStorage.setItem(key(value.age),JSON.stringify({context:value,status}));return value;
  }
  const requiredKeys=data=>['common:goal','common:home',...(data.age<3
    ?data.sheet.children.flatMap(c=>['life','play','help'].map(k=>c.ref+':'+k))
    :[...data.domains.flatMap(([domain])=>data.columns.map(([column])=>'group:'+domain+':'+column)),'group:food'])];
  function fieldLabel(data,key){
    if(key==='@owner')return '担任名';
    const child=key.startsWith('child:')?data.sheet.children.find(c=>c.ref===key.split(':').slice(0,2).join(':')):null;
    return (child?child.name+' ／ ':key.startsWith('common:')?'クラス共通 ／ ':'')+data.definitions[key].label;
  }
  function missing(data,action){
    const keys=[];
    if(!data.owner_name.trim())keys.push('@owner');
    if(action==='review')keys.push(...requiredKeys(data).filter(k=>!data.sheet.fields[k]?.body?.trim()));
    return keys;
  }
  function fixture(age) {
    const data=copy(config.contexts[age]),keys=requiredKeys(data);data.sheet.fields={};
    if(state!=='empty')for(const k of keys)data.sheet.fields[k]={body:'一人ひとりの気持ちを受け止め、安心して遊べる環境を整える。（確認用）',origins:[]};
    const later=data.age<3?data.sheet.children.at(-1).ref+':help':'group:expression:support';
    if(state==='partial'){delete data.sheet.fields['common:home'];delete data.sheet.fields[later];}
    if(state==='other-page')delete data.sheet.fields[later];
    if(state==='owner-cleared')data.owner_name='';
    return data;
  }
  const json=value=>new Response(JSON.stringify(value),{status:200,headers:{'Content-Type':'application/json'}});
  window.fetch=async(path)=>{
    const url=new URL(String(path),location.href),age=url.searchParams.get('age')||config.age;
    if(url.pathname.endsWith('/presence'))return json({editable:true,peers:[],server_time:'2026-11-15T09:00:00+09:00'});
    if(url.pathname.endsWith('/context'))return json(fixture(age));
    if(url.pathname.endsWith('/history'))return json({months:['2026-08','2026-09','2026-10'].map(month=>({month,records:[],legacy:[]}))});
    if(url.pathname.endsWith('/candidates'))return json({items:[{kind:'original',text:'【架空の文例】一人ひとりの発見や気持ちを受け止める。',year:2026,age:Number(age),month:11,relative_path:'確認用の架空文例',sheet:'見本',section:'計画',item:'活動',source_key:'fixture',phrase_id:1,cell_id:1}],has_more:false,total:1});
    throw new Error('確認用モックからは送信しません。');
  };
  window.previewErrors=[];
  addEventListener('error',e=>window.previewErrors.push(e.message));
  addEventListener('unhandledrejection',e=>window.previewErrors.push(String(e.reason)));

  function paintFields(keys){
    all('#drive-monthly-plan [aria-invalid]').forEach(el=>{el.removeAttribute('aria-invalid');el.removeAttribute('aria-describedby');});
    all('#drive-monthly-plan [data-cell],#drive-monthly-plan [data-owner]').forEach(el=>{
      if(keys.includes(el.hasAttribute('data-owner')?'@owner':el.dataset.cell)){
        el.setAttribute('aria-invalid','true');el.setAttribute('aria-describedby','monthly-review-missing');
      }
    });
  }
  function showMissing(action,focus=false){
    const data=adapter().read(),keys=missing(data,action),box=q('#monthly-review-missing');
    const scroll=box.querySelector('ul')?.scrollTop||0;
    box.replaceChildren();box.hidden=false;box.dataset.error=String(keys.length>0);box.setAttribute('role',keys.length?'alert':'status');
    const title=document.createElement('strong');title.textContent=keys.length
      ?`${action==='review'?'レビュー依頼':'下書き保存'}できません（未記入 ${keys.length}項目）`
      :`入力がそろいました。もう一度「${action==='review'?'レビュー依頼':'下書きを保存'}」を押してください。`;
    box.append(title);
    if(keys.length){
      const help=document.createElement('p');help.textContent=action==='review'?(config.kind==='detail'?'未記入の項目を選び、月案の編集画面で修正してください。':'未記入の項目を選ぶと、その欄へ移動します。下書きは途中でも保存できます。'):'担任名を入力してください。本文は途中でも保存できます。';box.append(help);
      const list=document.createElement('ul');
      for(const k of keys){
        const li=document.createElement('li'),a=document.createElement('a');a.textContent=fieldLabel(data,k);
        a.href=config.kind==='detail'?`edit-${data.age}.html?restore=1&field=${encodeURIComponent(k)}`:'#monthly-review-field';
        a.dataset.missingField=k;
        a.addEventListener('click',event=>{if(config.kind==='detail')return;event.preventDefault();adapter().jump(k);paintFields(missing(adapter().read(),action));});
        li.append(a);list.append(li);
      }
      box.append(list);list.scrollTop=scroll;
    }
    paintFields(keys);
    if(focus){box.focus({preventScroll:true});box.parentElement.scrollIntoView({block:'center'});}
    return keys;
  }
  function showNotice(text,error=false){
    const box=q('#monthly-review-missing');box.replaceChildren();box.textContent=text;box.hidden=false;box.dataset.error=String(error);box.setAttribute('role',error?'alert':'status');
    box.focus({preventScroll:true});box.parentElement.scrollIntoView({block:'center'});notice=text;
  }
  function clearFeedback(){q('#monthly-review-missing').hidden=true;paintFields([]);lastAction=null;notice=null;}
  function refreshControls(){
    if(!ready)return;
    const data=adapter().read(),link=q('#document-link');
    q('#preview-editor').href=`edit-${data.age}.html?restore=1`;
    if(link)link.href=`detail-${data.age}.html`;
    if(q('#request-monthly-review'))q('#request-monthly-review').disabled=!data.editable;
    if(lastAction&&!notice)showMissing(lastAction);
  }
  function saveDraft(){
    adapter().commit();lastAction='save';notice=null;
    if(showMissing('save',true).length)return;
    if(state==='error'&&!failed){failed=true;showNotice('下書きを保存できませんでした（確認用の通信エラー）。入力は残っています。もう一度お試しください。',true);return;}
    const value=persist(adapter().read());adapter().saved(value);clearFeedback();refreshControls();
    showNotice('下書きを保存しました。未記入の計画欄は、レビュー依頼時に確認します。');
    note('このタブ内だけに下書きを仮保存しました。本番には保存していません。');
  }
  function requestReview(){
    adapter().commit();lastAction='review';notice=null;
    if(showMissing('review',true).length)return;
    const draft=persist(adapter().read());adapter().saved(draft);
    if(state==='error'&&!failed){failed=true;showNotice('下書きは保存しましたが、レビュー依頼は完了していません（確認用の通信エラー）。もう一度「レビュー依頼」を押してください。',true);return;}
    const reviewed=persist(draft,'in_review');adapter().saved(reviewed);clearFeedback();
    location.href=`detail-${reviewed.age}.html#review-status`;
  }
  function renderDetail(){
    const entry=stored(config.age)||{context:fixture(config.age),status:'draft'};
    const data={...copy(entry.context),editable:false,edit_reason:'閲覧中です。修正は月案の編集画面から行います。'};
    adapter().reset(data);
    const badge=q('.document-header .status');badge.textContent=entry.status==='in_review'?'レビュー待ち':'下書き';badge.className='status status--'+entry.status;
    q('.report-sheet__approval strong').textContent=badge.textContent;
    const edit=all('.document-header a').find(e=>e.textContent.trim()==='修正');edit.href=`edit-${data.age}.html?restore=1`;edit.hidden=entry.status==='in_review';
    const button=q('#review-status button[name=status]');button.value=entry.status==='in_review'?'draft':'in_review';button.textContent=entry.status==='in_review'?'レビューを取り下げる':'レビュー依頼';
    button.className='button button--'+(entry.status==='in_review'?'secondary':'primary');
    q('.document-header .lead').textContent='園: 確認用の園 / クラス: '+data.classroom_name+' / 作成者: '+data.owner_name;
    q('#preview-state').disabled=true;q('#preview-reset').disabled=true;
    refreshControls();note(entry.status==='in_review'?'レビュー依頼を受け付けた見本です。取り下げてから「修正」へ戻れます。':'保存した下書きの見本です。未記入があれば、入力画面で修正してください。');
  }
  function reset(){
    state=q('#preview-state').value;failed=false;clearFeedback();
    const age=adapter().read().age;sessionStorage.removeItem(key(age));adapter().reset(fixture(age));refreshControls();
    note('「レビュー依頼」を押し、未記入の案内から修正する流れを試してください。');
  }
  document.addEventListener('click',event=>{
    const button=event.target.closest('button');
    if(button?.id==='save'||button?.id==='request-monthly-review'){
      event.preventDefault();event.stopImmediatePropagation();if(button.disabled)return;
      if(button.id==='save')saveDraft();else requestReview();return;
    }
    if(button?.matches('#print-monthly,#excel-monthly,[data-monthly-print]')){event.preventDefault();event.stopImmediatePropagation();note('このモックでは出力処理へ接続しません。');return;}
    const a=event.target.closest('#preview-business a');
    if(a?.id==='document-link'){event.preventDefault();event.stopImmediatePropagation();const data=adapter().read();location.href=`detail-${data.age}.html`;return;}
    if(a&&!a.hasAttribute('data-missing-field')&&(a.getAttribute('href')==='#'||/^(https?:|\/)/.test(a.getAttribute('href')||''))){event.preventDefault();event.stopImmediatePropagation();note('この確認画面では月案の保存・レビュー依頼を試します。外部ページには移動しません。');}
  },true);
  document.addEventListener('submit',event=>{
    event.preventDefault();event.stopImmediatePropagation();
    if(config.kind!=='detail')return;
    if(event.submitter?.value==='in_review'){requestReview();return;}
    if(event.submitter?.value==='draft'){persist(adapter().read());clearFeedback();renderDetail();}
  },true);
  document.addEventListener('input',event=>{
    if(ready&&event.target.closest('#drive-monthly-plan')&&lastAction&&!notice)showMissing(lastAction);
  });
  document.addEventListener('monthly-preview-render',()=>{if(ready)setTimeout(refreshControls,0);});
  document.addEventListener('DOMContentLoaded',()=>{
    ready=true;
    q('#preview-state').addEventListener('change',reset);q('#preview-reset').addEventListener('click',reset);
    q('#preview-jump').addEventListener('click',()=>{const b=q('#request-monthly-review')||q('#review-status button');b.scrollIntoView({block:'center'});b.focus({preventScroll:true});});
    if(config.kind==='detail')renderDetail();
    else {
      const previous=stored(config.age),params=new URLSearchParams(location.search);
      if(params.has('restore')&&previous){adapter().reset(previous.context);refreshControls();note('仮保存した内容を引き継いでいます。');}
      else reset();
      if(params.has('field')){lastAction='review';showMissing('review');adapter().jump(params.get('field'));paintFields(missing(adapter().read(),'review'));}
    }
  });
})();
