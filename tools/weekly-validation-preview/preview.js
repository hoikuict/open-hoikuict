/* This file and the adapter hooks are used only by the offline prototype. */
(() => {
  'use strict';
  const config=JSON.parse(document.getElementById('preview-data').textContent),q=s=>document.querySelector(s),all=s=>[...document.querySelectorAll(s)];
  const copy=x=>structuredClone(x),date=s=>new Date(s+'T12:00:00Z'),iso=d=>d.toISOString().slice(0,10),add=(s,n)=>{const d=date(s);d.setUTCDate(d.getUTCDate()+n);return iso(d);};
  const short=s=>`${Number(s.slice(5,7))}/${Number(s.slice(8))}`,key=(age,month)=>`weekly-validation-preview-v1:${age}:${month}`;
  const storageRead=(age,month)=>JSON.parse(sessionStorage.getItem(key(age,month))||'null');
  const recordsKey=age=>`weekly-validation-preview-v1:records:${age}`;
  const store=c=>{sessionStorage.setItem(key(c.age,c.month),JSON.stringify(c));const records=JSON.parse(sessionStorage.getItem(recordsKey(c.age))||'{}');for(const r of c.records)if(r.document_id)records[r.week_start]=copy(r);sessionStorage.setItem(recordsKey(c.age),JSON.stringify(records));};
  const labelStatus=r=>r.status==='in_review'?'レビュー待ち':r.document_id?'下書き':'未作成';
  const query=new URLSearchParams(location.search),initialMonth=query.get('month')||'2026-11';
  let ready=false,checked=false,saving=false,failure=false,reviewFailure=false,saveCount=0,checkedAction='save';
  const workspaceKey='weekly-validation-preview-r2:working';
  const uiStatus=text=>{if(q('#preview-status'))q('#preview-status').textContent=text;};
  function context(age,month) {
    if(!/^\d{4}-(0[1-9]|1[0-2])$/.test(month)||Number(month.slice(0,4))<1900||Number(month.slice(0,4))>2199)throw Error('表示月を正しく選択してください。入力内容は保持しています。');
    const saved=storageRead(age,month),records=JSON.parse(sessionStorage.getItem(recordsKey(age))||'{}');if(saved){saved.records=saved.records.map(r=>records[r.week_start]||r);return saved;}
    const c=copy(config.contexts[age]),d=date(month+'-01'),end=new Date(d);end.setUTCMonth(end.getUTCMonth()+1);end.setUTCDate(0);
    d.setUTCDate(d.getUTCDate()-((d.getUTCDay()+6)%7));const starts=[];while(d<=end){starts.push(iso(d));d.setUTCDate(d.getUTCDate()+7);}
    c.month=month;c.records=starts.map(start=>records[start]||({...copy(c.records[0]),week_start:start,document_id:null,lock_version:0,status:'empty',status_label:'未作成',editable:true}));
    c.selected_week=starts.includes(query.get('week'))?query.get('week'):starts[2]||starts[0];return c;
  }
  const response=(value,code=200)=>new Response(JSON.stringify(value),{status:code,headers:{'Content-Type':'application/json'}});
  window.fetch=async(path,options={})=>{
    const u=new URL(path,location.href);
    if(!u.pathname.startsWith('/plans/weekly-library/'))throw Error('この確認画面は外部に接続しません。');
    if(u.pathname.endsWith('/context')){try{return response(context(u.searchParams.get('age'),u.searchParams.get('month')));}catch(e){return response({detail:e.message},422);}}
    if(u.pathname.endsWith('/candidates')) {
      const age=Number(u.searchParams.get('age')||q('[name=age_class]')?.value||config.age),month=Number(u.searchParams.get('month')||11),words=(u.searchParams.get('keyword')||'').trim().split(/\s+/);
      const sample={id:'fictional-week',title:'落ち葉で遊ぶ（架空の文例）',age,month,aim:'秋の自然に親しむ。',activity:'落ち葉の色や形を楽しむ。',support_preparation:'落ち葉を用意し、発見に耳を傾ける。',source_label:'確認用の架空文例',days:Array.from({length:6},()=>({activity:'落ち葉を集める。',support:'発見に寄り添う。',preparation:'かご'}))};
      return response({items:words.every(w=>JSON.stringify(sample).includes(w))?[sample]:[]});
    }
    if(u.pathname.endsWith('/save')) {
      if(failure){failure=false;return response({detail:'通信を確認して、もう一度保存してください。入力した内容はこの画面に残っています。'},503);}
      const payload=JSON.parse(options.body),c=context(payload.age,payload.month);
      for(const item of payload.items) {
        const r=c.records.find(r=>r.week_start===item.week_start);Object.assign(r,copy(item),{document_id:r.document_id||10000+payload.age*100+c.records.indexOf(r),lock_version:r.lock_version+1,status:'draft',status_label:'下書き',editable:true});
      }
      c.selected_week=api.adapter.current().selected_week;store(c);saveCount++;uiStatus(`このタブ内で${payload.items.length}週を仮保存しました。上部の「保存した文書・承認状況」と週案カレンダーでも確認できます。`);return response(c);
    }
    throw Error('この操作の通信は確認用では実行しません。');
  };
  const api=window.WeeklyPreview={initial:boot=>{const c=context(boot.age,initialMonth);if(c.records.some(r=>r.week_start===query.get('week')))c.selected_week=query.get('week');return c;},changed:()=>{if(ready){updateReviewControls();if(checked)renderFeedback();}},notice:(text,error)=>{if(!saving)return false;message(error?'保存を完了できませんでした':'保存しました',text,error);return error;}};
  function focus(el){el?.scrollIntoView({block:'center'});el?.focus({preventScroll:true});}
  function reviewMissing(r){return r.owner_name.trim()?[]:[{selector:'[name=owner_name]',week:r.week_start,text:`${short(r.week_start)}からの週の作成者を入力してください。`}];}
  function updateReviewControls(){
    if(config.kind!=='editor'||!api.adapter)return;
    const c=api.adapter.current(),r=c.records.find(r=>r.week_start===c.selected_week),button=q('#weekly-review');
    button.disabled=saving||!r.editable;button.textContent=r.status==='in_review'?'レビュー依頼済み':'レビュー依頼';
    q('#weekly-review-target').textContent=`レビュー対象：${short(r.week_start)}〜${short(add(r.week_start,6))}の週${r.status==='in_review'?'（レビュー待ち）':' ／ この週だけを保存して依頼します。'}`;
  }
  function missing() {
    const list=[];
    for(const [selector,name] of [['#weekly-month','表示月'],['[name=target_week]','対象週']]){
      const el=q(selector);if(!el.value||!el.validity.valid)list.push({selector,text:`${name}を正しく選択してください。`});
    }
    const c=api.adapter.current(),records=checkedAction==='review'?[c.records.find(r=>r.week_start===c.selected_week)]:api.adapter.pending();
    for(const r of records)list.push(...reviewMissing(r));
    return list;
  }
  function clearInvalid(){all('[data-preview-invalid]').forEach(el=>{el.removeAttribute('aria-invalid');el.removeAttribute('aria-describedby');delete el.dataset.previewInvalid;});}
  function renderFeedback(focusBox=false) {
    if(!ready||!api.adapter)return;
    const box=q('#weekly-save-feedback'),list=missing(),c=api.adapter.current();clearInvalid();
    const action=checkedAction==='review'?'レビュー依頼':'下書きを保存',sig=JSON.stringify([checkedAction,list]);box.hidden=false;box.dataset.error=String(!!list.length);box.setAttribute('role',list.length?'alert':'status');
    if(box.dataset.signature!==sig){box.dataset.signature=sig;box.replaceChildren();const title=document.createElement('strong');title.textContent=list.length?`まだ${checkedAction==='review'?'レビュー依頼':'保存'}できません（確認が必要な項目 ${list.length}件）`:`入力がそろいました。もう一度「${action}」を押してください。`;box.append(title);
      if(list.length){const ul=document.createElement('ul');for(const item of list){const li=document.createElement('li'),a=document.createElement('a');a.href='#weekly-form';a.textContent=item.text;a.addEventListener('click',event=>{event.preventDefault();if(item.week)api.adapter.select(item.week);renderFeedback();focus(q(item.selector));});li.append(a);ul.append(li);}box.append(ul);}}
    for(const item of list)if(!item.week||item.week===c.selected_week){const el=q(item.selector);el.setAttribute('aria-invalid','true');el.setAttribute('aria-describedby','weekly-save-feedback');el.dataset.previewInvalid='true';}
    if(focusBox){box.focus({preventScroll:true});q('#weekly-save').closest('.form-actions').scrollIntoView({block:'center'});}
  }
  function message(title,text,error=false){const box=q('#weekly-save-feedback')||q('#weekly-detail-feedback');if(!box)return;delete box.dataset.signature;box.hidden=false;box.dataset.error=String(error);box.setAttribute('role',error?'alert':'status');box.replaceChildren();const h=document.createElement('strong'),p=document.createElement('p');h.textContent=title;p.textContent=text;box.append(h,p);box.focus({preventScroll:true});}
  async function save(){if(saving)return;checkedAction='save';checked=true;renderFeedback(true);if(missing().length)return;checked=false;saving=true;updateReviewControls();try{await api.adapter.save();}finally{saving=false;updateReviewControls();}}
  function requestReview(fromEditor){
    if(saving)return;
    const c=fromEditor?api.adapter.current():currentSaved(),r=c.records.find(r=>r.week_start===c.selected_week);
    if(!r.editable||r.status==='in_review')return;
    if(fromEditor){checkedAction='review';checked=true;renderFeedback(true);if(missing().length)return;}
    else if(reviewMissing(r).length){message('まだレビュー依頼できません',reviewMissing(r)[0].text+'「修正」から入力してください。',true);return;}
    checked=false;saving=true;if(fromEditor)updateReviewControls();
    try{
      if(failure||reviewFailure){failure=false;reviewFailure=false;throw Error('通信を確認して、もう一度「レビュー依頼」を押してください。入力内容は保持しています。');}
      const saved=context(c.age,c.month),index=saved.records.findIndex(x=>x.week_start===r.week_start);
      const reviewed={...copy(r),document_id:r.document_id||10000+c.age*100+index,lock_version:r.lock_version+1,status:'in_review',status_label:'レビュー待ち',editable:false};
      saved.records[index]=reviewed;saved.selected_week=r.week_start;store(saved);
      if(fromEditor)api.adapter.acceptReviewed(reviewed);else detail();
      message('レビューを依頼しました',`${short(r.week_start)}〜${short(add(r.week_start,6))}の週を保存し、レビュー待ちにしました。`);
      if(fromEditor){const a=document.createElement('a');a.href=destination('detail',c);a.textContent='保存した文書・承認状況を確認';a.addEventListener('click',e=>{e.preventDefault();navigate('detail');});q('#weekly-save-feedback').append(a);}
      uiStatus('確認用の仮依頼が完了しました。ほかの週は依頼していません。');
    }catch(e){message('レビュー依頼を完了できませんでした',e.message,true);}
    finally{saving=false;if(fromEditor)updateReviewControls();}
  }
  function loadState(initial=false){
    const age=api.adapter.current().age,month=api.adapter.current().month,state=q('#preview-state').value;
    if(initial!==true){sessionStorage.removeItem(workspaceKey);Object.keys(sessionStorage).filter(k=>k.startsWith(key(age,''))||k===recordsKey(age)).forEach(k=>sessionStorage.removeItem(k));}const c=context(age,month);c.selected_week=initial===true&&c.records.some(r=>r.week_start===query.get('week'))?query.get('week'):c.records[2]?.week_start||c.records[0].week_start;
    const selectedIndex=c.records.findIndex(r=>r.week_start===c.selected_week);
    let baseline=copy(c);
    c.records.forEach((r,i)=>{
      const fill=['filled','error','review-error','saved-owner'].includes(state)||i===selectedIndex&&['partial','owner','other-week'].includes(state);
      if(fill){r.sheet.aim='身近な自然を見つけて楽しむ。';r.sheet.activity='落ち葉を集め、色や形を見比べる。';r.sheet.support_preparation='かごを用意し、発見を受け止める。';r.sheet.days.forEach(d=>Object.assign(d,{activity:'落ち葉を集める。',support:'発見に寄り添う。',preparation:'かご'}));r.sheet.context.current_children_snapshot='友達の発見にも興味を向けている。';}
    });
    if(state==='owner')c.records[2].owner_name='';
    if(state==='other-week')c.records[0].owner_name='';
    if(state==='saved-owner'){c.records[2].owner_name='見本 あおい';c.records[2].document_id=10000+age*100+2;c.records[2].status='draft';c.records[2].status_label='下書き';baseline=copy(c);store(c);}
    checked=false;failure=state==='error';reviewFailure=state==='review-error';clearInvalid();q('#weekly-save-feedback').hidden=true;api.adapter.reset(c,baseline);
    if(state==='dates'){q('#weekly-month').value='';q('[name=target_week]').value='';}
    q('#weekly-message').hidden=true;uiStatus('見本を切り替えました。「下書きを保存」または「レビュー依頼」を試せます。');
  }
  const destination=(kind,c,week=c.selected_week)=>`${kind}-${c.age}.html?`+new URLSearchParams({month:c.month,week});
  async function navigate(kind){const c=api.adapter.current();if(kind==='detail'){sessionStorage.setItem(workspaceKey,JSON.stringify(api.adapter.checkpoint()));go(kind,c);return;}if(api.adapter.dirty()){
    const dialog=q('#weekly-confirm');q('#weekly-confirm-text').textContent='保存していない変更があります。変更を破棄して移動しますか？';dialog.showModal();q('#weekly-confirm-no').onclick=()=>dialog.close();q('#weekly-confirm-yes').onclick=()=>{dialog.close();go(kind,c);};
  }else go(kind,c);}
  function go(kind,c){if(kind==='calendar')sessionStorage.removeItem(workspaceKey);api.adapter.reset(context(c.age,c.month));location.href=destination(kind,c);}
  function resumeWorking(){
    const snapshot=JSON.parse(sessionStorage.getItem(workspaceKey)||'null');if(!snapshot)return false;
    const entry=snapshot.entries.find(e=>e.data.age===config.age&&e.data.month===initialMonth);if(!entry)return false;
    for(const cached of snapshot.entries){const saved=context(cached.data.age,cached.data.month);for(const version of [cached.data,cached.saved])for(const r of version.records){const actual=saved.records.find(x=>x.week_start===r.week_start);if(actual?.document_id&&actual.document_id===r.document_id)for(const f of ['status','status_label','editable','lock_version'])r[f]=actual[f];}}
    snapshot.current=`${entry.data.classroom_id}|${entry.data.month}|${entry.data.age}`;snapshot.selected=query.get('week')||snapshot.selected;api.adapter.resume(snapshot);sessionStorage.removeItem(workspaceKey);return true;
  }
  function currentSaved(){const c=context(config.age,initialMonth);c.selected_week=c.records.some(r=>r.week_start===query.get('week'))?query.get('week'):c.selected_week;return c;}
  function detail(){
    const c=currentSaved(),r=c.records.find(r=>r.week_start===c.selected_week);if(!r.document_id){uiStatus('この週は仮保存されていません。入力画面から保存してください。');q('#review-status').hidden=true;}
    else q('#review-status').outerHTML=config.review_panels[r.status==='in_review'?'in_review':'draft'];
    q('#weekly-detail-feedback')?.remove();const feedback=document.createElement('section');feedback.id='weekly-detail-feedback';feedback.className='weekly-feedback';feedback.tabIndex=-1;feedback.hidden=true;const action=q('#review-status button[name=status]');if(action)action.before(feedback);else q('#review-status').append(feedback);
    all('[data-preview-value]').forEach(el=>{const field=el.dataset.previewValue;el.textContent=field.startsWith('day_')?r.sheet.days[Number(field.split('_')[1])][field.split('_').slice(2).join('_')]:field.startsWith('context_')?r.sheet.context[field.slice(8)]||'':r.sheet[field]||'';if(field.startsWith('context_'))el.closest('section').hidden=!el.textContent;});
    q('.document-header h1').textContent=`${c.selected_week}週 週案（${c.classroom_name}・${c.age}歳児）`;
    q('.document-header .lead').textContent=`園: 見本保育園 / クラス: ${c.classroom_name} / 作成者: ${r.owner_name}`;
    q('.document-header .status').textContent=labelStatus(r);
    q('.weekly-report>p').textContent=`${c.classroom_name}・${c.age}歳児 ／ ${c.selected_week}週 ／ 記入者：${r.owner_name}`;
    all('.weekly-print-table tbody tr').forEach((row,i)=>{if(c.age>=3){row.hidden=i===5&&!r.sheet.include_saturday;row.querySelector('th').textContent=`${short(add(c.selected_week,i))}（${'月火水木金土'[i]}）`;}else row.querySelector('th').firstChild.textContent=c.selected_week+'週';});
    all('.document-header a').forEach(a=>{if(a.textContent.trim()==='修正')a.hidden=!r.editable;});
    all('.weekly-report a[data-original-href]').filter(a=>a.dataset.originalHref.includes('/monthly-library')).forEach(a=>a.parentElement.hidden=!r.sheet.parent_document_id);
    q('#preview-editor').href=destination('edit',c);uiStatus('このタブで仮保存した内容を表示しています。レビュー操作も架空データ内だけで試せます。');
  }
  function calendar(){
    const c=currentSaved();q('.calendar-filters [name=month]').value=c.month;q('.calendar-filters [name=age]').value=c.age;
    q('#preview-business>h2').textContent=`${c.month}・${c.classroom_name}・${c.age}歳児`;
    const list=q('.week-list'),template=list.firstElementChild.cloneNode(true);list.replaceChildren();
    for(const r of c.records){const card=template.cloneNode(true);card.dataset.period=r.week_start;const range=`${short(r.week_start)}〜${short(add(r.week_start,6))}`;card.querySelector('h3').textContent=range;card.querySelector('.calendar-days-scroll').setAttribute('aria-label',range+'の活動');card.querySelector('.status').textContent='自園の帳票 · '+labelStatus(r);const a=card.querySelector('.calendar-card-heading a');a.textContent=r.document_id?'自園の帳票を開く':'自園の帳票で作成';a.href=destination('edit',c,r.week_start);a.removeAttribute('data-original-href');card.querySelector(':scope>p').textContent='ねらい：'+(r.sheet.aim||'未入力');if(c.age<3&&r.document_id){const p=document.createElement('p');p.textContent='今週の活動：'+(r.sheet.activity||'未入力');const note=document.createElement('small');note.textContent='週全体の計画です。各日への割り当てはありません。';p.append(document.createElement('br'),note);card.querySelector('.calendar-days-scroll').before(p);}const days=card.querySelectorAll('.calendar-days>div');days.forEach((day,i)=>{day.querySelector('strong').textContent=short(add(r.week_start,i));day.classList.toggle('outside',add(r.week_start,i).slice(0,7)!==c.month);day.querySelector('p').textContent=i<(r.sheet.include_saturday?6:5)&&c.age>=3?r.sheet.days[i].activity||'—':'—';});list.append(card);}
    all('.calendar-filters a').forEach(a=>{const d=date(c.month+'-01');d.setUTCMonth(d.getUTCMonth()+(a.textContent.includes('前')?-1:1));a.href=`calendar-${c.age}.html?month=${iso(d).slice(0,7)}`;a.removeAttribute('data-original-href');});
    q('#preview-editor').href=destination('edit',c);
  }
  document.addEventListener('submit',event=>{if(!event.target.closest('#preview-business'))return;event.preventDefault();event.stopImmediatePropagation();
    if(config.kind==='editor')save();
    else if(config.kind==='calendar'){const form=event.target;location.href=`calendar-${form.elements.age.value}.html?month=${encodeURIComponent(form.elements.month.value)}`;}
    else {const c=currentSaved(),r=c.records.find(r=>r.week_start===c.selected_week),status=event.submitter?.value;if(!['draft','in_review'].includes(status)||!r.document_id)return;if(status==='in_review'){requestReview(false);return;}r.status=status;r.status_label=labelStatus(r);r.editable=true;store(c);detail();message('レビュー依頼を取り下げました','下書きに戻りました。「修正」から編集できます。');}
  },true);
  document.addEventListener('change',event=>{if(config.kind!=='editor'||!ready)return;const el=event.target;
    if(el.matches('#weekly-month,[name=target_week]')&&(!el.value||!el.validity.valid)){event.stopImmediatePropagation();checked=true;renderFeedback();}
    else if(checked)queueMicrotask(()=>renderFeedback());
  },true);
  document.addEventListener('input',event=>{if(ready&&config.kind==='editor'&&checked&&event.target.closest('#weekly-form'))queueMicrotask(()=>renderFeedback());});
  document.addEventListener('click',event=>{
    const button=event.target.closest('button'),a=event.target.closest('#preview-business a');
    if(button?.id==='weekly-save'){event.preventDefault();event.stopImmediatePropagation();save();return;}
    if(button?.id==='weekly-review'){event.preventDefault();event.stopImmediatePropagation();requestReview(true);return;}
    if(button?.id==='weekly-cancel'){event.preventDefault();event.stopImmediatePropagation();navigate('calendar');return;}
    if(config.kind==='detail'&&button?.textContent.trim()==='印刷'){event.preventDefault();uiStatus('印刷は今回の試用対象外です。業務画面の印刷機能は従来どおり維持する予定です。');return;}
    if(!a)return;
    if(!a.dataset.originalHref&&a.getAttribute('href')!=='#'&&!a.id.match(/^(weekly-document-link|parent-link)$/))return;
    event.preventDefault();event.stopImmediatePropagation();const href=a.dataset.originalHref||a.href;
    if(href.includes('monthly')||href==='/plans/'||href==='/plans/documents/'){uiStatus('この試用は週案が対象です。ほかの帳票・一覧への移動は従来の導線を維持する予定です。');return;}
    const kind=a.id==='weekly-document-link'?'detail':href.includes('/edit')||href.includes('/weekly-library')?'edit':href.includes('/weekly-plans')?'calendar':null;
    if(!kind)return;
    if(config.kind==='editor')navigate(kind);else{const c=currentSaved();if(config.kind==='calendar'&&href.includes('/weekly-plans')){const u=new URL(href,location.href);c.month=u.searchParams.get('month')||c.month;c.age=Number(u.searchParams.get('age')||c.age);}location.href=destination(kind,c);}
  },true);
  document.addEventListener('DOMContentLoaded',()=>{
    ready=true;q('#preview-editor').href=`edit-${config.age}.html`;
    q('#preview-jump').hidden=config.kind!=='editor';q('#preview-state').closest('label').hidden=config.kind!=='editor';q('#preview-reset').hidden=config.kind!=='editor';
    if(config.kind==='editor'){
      q('#preview-state').onchange=loadState;q('#preview-reset').onclick=loadState;q('#preview-jump').onclick=()=>focus(q('#weekly-save'));
      if(resumeWorking())uiStatus('入力画面に戻りました。ほかの週の未保存の入力も保持しています。');else if(!storageRead(config.age,initialMonth)&&!api.adapter.current().records.some(r=>r.document_id))loadState(true);else uiStatus('このタブに仮保存した内容を開きました。');
      updateReviewControls();
    }else if(config.kind==='detail')detail();else calendar();
  });
})();
