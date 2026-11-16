/* Local proposal only: network and native form submissions are never used. */
(() => {
  'use strict';
  const config=JSON.parse(document.getElementById('mock-fixture').textContent),copy=structuredClone;
  const adapters={};let state='partial',failed=false,last=null,saved=null,initial=null,ready=false,dirty=false;
  const q=s=>document.querySelector(s),qa=(s,r=document)=>[...r.querySelectorAll(s)];
  const status=text=>{if(q('#mock-status'))q('#mock-status').textContent=text;};
  const monthlyKey=age=>'form-validation-monthly-r1-2:'+age;
  function readMonthly(age){try{return JSON.parse(sessionStorage.getItem(monthlyKey(age))||'null');}catch{return null;}}
  function writeMonthly(entry){sessionStorage.setItem(monthlyKey(entry.context.age),JSON.stringify(entry));}
  function monthlyLabel(entry){return entry.review_status==='in_review'?'レビュー待ち':'下書き';}
  function monthlyEntry(){return readMonthly(config.data.age)||{context:copy(initial),review_status:'draft'};}
  function renderMonthlyDetail(){
    const entry=monthlyEntry(),data={...copy(entry.context),editable:false,status:monthlyLabel(entry),edit_reason:'閲覧中です。修正は月案の編集画面から行います。'};
    adapters.monthly.reset(data);
    q('#review-status').outerHTML=config.data.review_panels[entry.review_status==='in_review'?'in_review':'draft'];
    const badge=q('.document-header .status');badge.textContent=data.status;badge.className='status status--'+entry.review_status;
    const lead=q('.document-header .lead');lead.textContent=lead.textContent.replace(/作成者:.*$/,'作成者: '+data.owner_name);
    const edit=qa('.document-header a').find(a=>a.textContent.trim()==='修正');
    if(edit){edit.hidden=entry.review_status==='in_review';edit.removeAttribute('data-original-href');edit.href=`monthly-${data.age}.html?preview=r1-2`;}
    const link=q('#document-link');link.href='#review-status';link.hidden=false;
    writeMonthly(entry);register();
  }
  window.FormMock={adapters,navigate:()=>leave(),config};
  const json=value=>new Response(JSON.stringify(value),{status:200,headers:{'Content-Type':'application/json'}});
  window.fetch=async (path,options={})=>{
    const u=new URL(String(path),location.href),data=options.body?JSON.parse(options.body):{};
    if(u.pathname.includes('/monthly-library/')){
      const c=copy(config.data.contexts?.[u.searchParams.get('age')||q('#age')?.value||'0']);
      if(u.pathname.endsWith('/context'))return json(c);
    if(u.pathname.endsWith('/presence'))return json({editable:config.kind!=='monthly-detail',peers:[],server_time:'2026-11-15T09:00:00+09:00'});
      if(u.pathname.endsWith('/history'))return json({months:['2026-10','2026-09','2026-08'].map(month=>({month,records:[],legacy:[]}))});
      if(u.pathname.endsWith('/candidates'))return json({items:[{kind:'original',text:'落ち葉の色や形を見比べ、発見を友達と伝え合う。',year:2026,age:c.age,month:11,relative_path:'確認用の架空文例',sheet:'見本',section:'保育内容',ryoiki:'環境',item:'活動',phrase_id:1,cell_id:1}],has_more:false,total:1});
      if(u.pathname.endsWith('/generate'))return json({items:[],candidates:[],reason:'確認用では外部生成を行いません。'});
      if(u.pathname.endsWith('/save'))return json(c);
    }
    if(u.pathname.includes('/weekly-library/')){
      const age=u.searchParams.get('age')||q('[name=age_class]')?.value||'0';
      if(u.pathname.endsWith('/context'))return json(copy(config.data.contexts[age]));
      if(u.pathname.endsWith('/candidates')){
        const a=Number(age),sample={id:'fictional-week',title:'落ち葉で遊ぶ（架空の文例）',age:a,month:11,aim:'秋の自然に親しむ。',activity:'落ち葉の色や形を楽しむ。',support_preparation:'落ち葉を用意し、発見に耳を傾ける。',source_label:'確認用の架空文例',days:Array.from({length:6},()=>({activity:'落ち葉を集める。',support:'発見に寄り添う。',preparation:'かご'}))};
        return json({items:[sample]});
      }
    }
    if(u.pathname.includes('/annual-library/')){
      const id=u.searchParams.get('classroom_id')||q('#annual-classroom')?.value||'1';
      return json(copy(config.data.contexts[id]));
    }
    if(u.pathname.endsWith('/reflections'))return json((data.entries||[]).map(e=>({...e,locked:false,label:'下書き（確認用）',review_id:null,updated_at:'2026-11-15 09:00'})));
    throw new Error('この操作は確認用の画面内では接続しません。');
  };
  // Renderer errors are recorded for local verification, never sent anywhere.
  window.mockErrors=[];
  window.addEventListener('error',e=>window.mockErrors.push(e.message));
  window.addEventListener('unhandledrejection',e=>window.mockErrors.push(String(e.reason)));
  const known='#weekly-save,#annual-save,#save,#reflection-save,#reflection-review,[data-progress-save-go],#save-btn';
  const isAction=b=>b&&b.closest('#mock-business')&&(b.matches(known)||(b.form&&b.form.method!=='get'&&b.type==='submit'));
  const fields=root=>qa('input,select,textarea',root||q('#mock-business')).filter(e=>e.type!=='hidden'&&!e.disabled&&!e.readOnly);
  function label(el){
    if(!el)return '入力内容';
    if(el.getAttribute('aria-label'))return el.getAttribute('aria-label');
    const l=el.labels?.[0]||el.closest('label')||el.parentElement?.querySelector('label');
    if(l){const n=l.cloneNode(true);n.querySelectorAll('input,select,textarea,option,.mock-field-error,.text-xs,p,small').forEach(e=>e.remove());const text=n.textContent.replace(/\s+/g,' ').replace(/[＊*]|[（(]必須[）)]/g,'').trim().replace(/\s+必須$/,'');if(text)return text.slice(0,75);}
    return ({void_reason:'無効化理由',body:'コメント',checked_at:'測定日',allergen_name:'アレルゲン名',note:'確認コメント',comment:'差戻しコメント',owner_name:'作成者'})[el.name]||el.placeholder||el.name||'入力内容';
  }
  function giveId(el){if(!el.id)el.id='mock-field-'+(++giveId.n);return el.id;}giveId.n=0;
  function jump(el){if(!el)return;el.closest('details')?.setAttribute('open','');el.scrollIntoView({block:'center'});el.focus({preventScroll:true});}
  function buttons(){return qa('#mock-business button').filter(b=>isAction(b)&&!b.disabled);}
  function operation(){return buttons().find(b=>b.dataset.mockAction===q('#mock-operation').value)||buttons()[0];}
  function register(){
    buttons().forEach((b,i)=>{b.dataset.mockAction=b.id||'operation-'+i;});
    const select=q('#mock-operation'),value=select.value;select.replaceChildren();
    buttons().forEach(b=>{const o=document.createElement('option');o.value=b.dataset.mockAction;o.textContent=b.textContent.trim();select.append(o);});
    if([...select.options].some(o=>o.value===value))select.value=value;
    qa('#mock-business form').forEach(f=>f.noValidate=true);
  }
  function zone(button){
    if(button.parentElement.classList.contains('mock-action-zone'))return button.parentElement;
    let parent=button.parentElement;
    if(parent.matches('form')||parent.querySelectorAll('textarea,input,select').length){
      const z=document.createElement('div');z.className='mock-action-zone';button.before(z);z.append(button);return z;
    }
    parent.classList.add('mock-action-zone');return parent;
  }
  function box(button){const z=zone(button);let e=z.querySelector(':scope > .mock-feedback');if(!e){e=document.createElement('section');e.className='mock-feedback';e.tabIndex=-1;e.hidden=true;z.prepend(e);}return e;}
  function errors(button){
    const root=button.form||q('#mock-business'),result=[];
    if(config.kind==='meeting'&&button.id==='save-btn')return result;
    const push=(el,message,extra={})=>{if(!result.some(r=>r.el===el&&r.message===message))result.push({el,message,...extra});};
    const required=el=>{if(el&&(!el.value.trim()||(el.type==='file'&&!el.files.length)))push(el,`${label(el)}を${el.tagName==='SELECT'||['date','month','week','file'].includes(el.type)?'選択':'入力'}してください。`);};
    const skip=button.value==='draft'||button.id==='reflection-save';
    if(!skip)fields(root).filter(el=>el.required&&!(config.kind==='weekly'&&el.name==='owner_name')).forEach(required);
    if(config.kind==='weekly'&&button.id==='weekly-save'){
      const c=adapters.weekly.current();
      c.records.forEach((r,i)=>{if(r.editable&&!r.owner_name.trim()&&(r.week_start===c.selected_week||JSON.stringify(r.sheet)!==JSON.stringify(initial.records[i]?.sheet))){
        const el=q('[name=owner_name]');push(el,`${r.week_start.slice(5).replace('-','/')}からの週の作成者を入力してください。`,{week:r.week_start});
      }});
    }
    if(config.kind==='annual'){
      if(button.id==='annual-save')required(q('#annual-owner'));
      if(button.id==='reflection-review'){
        const period=q('#reflection-review-period').value;
        const entries=qa('[data-reflection]').filter(e=>e.dataset.reflection.startsWith(period+':'));
        if(!entries.some(e=>e.value.trim()))push(entries[0],'選択した期の反省が未入力です。いずれかの欄に記入してください。');
      }
    }
    if(config.kind==='monthly'&&button.id==='save')required(q('[data-owner]'));
    if(config.kind==='document-decision'&&button.value==='returned')required(root.querySelector('[name=note]'));
    if(config.kind==='reflection-decision'&&button.value==='return')required(root.querySelector('[name=comment]'));
    if(config.kind==='reflection-request'&&['empty','partial'].includes(state))push(q('.reflection-review-values'),'振り返りが未入力です。入力画面へ戻って記入してください。',{route:'daily-reflection.html'});
    if(config.kind==='health'&&root.dataset.originalAction?.includes('/check-records')){
      required(root.querySelector('[name=checked_at]'));
      required(root.querySelector('[name=correction_reason]'));
      for(const [name,min,max]of [['height_cm',30,200],['weight_kg',1,100],['temperature',30,45],['heart_rate',1,300],['respiratory_rate',1,150]]){
        const e=root.querySelector(`[name=${name}]`);if(e?.value.trim()&&(!Number.isFinite(Number(e.value))||Number(e.value)<min||Number(e.value)>max))push(e,`${label(e)}は${min}〜${max}の範囲で入力してください。`);
      }
    }
    if(config.kind==='allergy'&&root.querySelector('[name=allergen_name]'))required(root.querySelector('[name=allergen_name]'));
    if(config.kind==='institutional'){
      if(root.querySelector('[name=origin]')?.value==='retrospective')required(root.querySelector('[name=fiscal_year]'));
      const included=root.querySelector('[name=include_initial_link]')?.checked;
      if(root.querySelector('[name=visibility]')?.value==='linked_targets'&&!included)push(root.querySelector('[name=include_initial_link]'),'限定公開ではリンク先を指定してください。');
      if(included){const type=root.querySelector('[name=initial_target_type]');required(type);required(root.querySelector(type.value.includes('external')?'[name=initial_target_label]':'[name=initial_target_id]'));}
    }
    if(config.kind==='meeting'&&root.querySelector('[name=series_id]')?.value)required(root.querySelector('[name=fiscal_year]'));
    fields(root).forEach(el=>{if(el.value&& !el.validity.valid&&!el.validity.valueMissing)push(el,`${label(el)}の形式・範囲を確認してください。`);});
    return result;
  }
  function clearFields(){qa('.mock-field-error').forEach(e=>e.remove());qa('[data-mock-invalid]').forEach(e=>{e.removeAttribute('aria-invalid');e.removeAttribute('data-mock-invalid');e.removeAttribute('aria-describedby');});}
  function show(button,list,focus){
    clearFields();const e=box(button);e.replaceChildren();e.hidden=false;e.dataset.error=String(list.length>0);e.setAttribute('role',list.length?'alert':'status');
    const strong=document.createElement('strong');strong.textContent=list.length?`まだ${/依頼|提出|進む/.test(button.textContent)?'進めません':'保存できません'}（確認が必要な項目 ${list.length}件）`:'入力がそろいました。もう一度、操作ボタンを押してください。';e.append(strong);
    if(list.length){const ul=document.createElement('ul');list.forEach(item=>{const li=document.createElement('li'),a=document.createElement('a');a.href='#'+giveId(item.el);a.textContent=item.message;a.addEventListener('click',ev=>{ev.preventDefault();if(item.route){location.href=item.route;return;}if(item.week)adapters.weekly.select(item.week);jump(item.week?q('[name=owner_name]'):item.el);});li.append(a);ul.append(li);
        if(item.el?.matches('input,select,textarea')&&(!item.week||item.week===adapters.weekly.current().selected_week)&&!item.el.dataset.mockInvalid){item.el.setAttribute('aria-invalid','true');item.el.dataset.mockInvalid='true';const help=document.createElement('span');help.id=giveId(item.el)+'-error';help.className='mock-field-error';help.textContent=item.message;item.el.after(help);item.el.setAttribute('aria-describedby',help.id);}
      });e.append(ul);}
    if(focus){e.focus({preventScroll:true});zone(button).scrollIntoView({block:'center'});}
  }
  function snapshot(){return fields().map(el=>({id:giveId(el),name:label(el),value:el.type==='checkbox'||el.type==='radio'?el.checked:el.type==='file'?[...el.files].map(f=>f.name).join('、'):el.value}));}
  function save(button){
    qa('.mock-feedback').forEach(e=>e.hidden=true);
    last=button;const list=errors(button);if(list.length){show(button,list,true);return;}
    if(state==='error'&&!failed){failed=true;const e=box(button);e.hidden=false;e.dataset.error='true';e.setAttribute('role','alert');e.textContent=(config.kind==='monthly-detail'?`「${button.textContent.trim()}」を完了できませんでした`:'保存できませんでした')+'（確認用の通信エラー）。入力は残っています。同じボタンでもう一度試せます。';e.focus({preventScroll:true});zone(button).scrollIntoView({block:'center'});return;}
    clearFields();box(button).hidden=true;saved={fields:snapshot(),dynamic:adapters[config.kind]?.current?.()};dirty=false;
    if(config.kind==='monthly'&&saved.dynamic){
      saved.dynamic.document_id ||= 7000+saved.dynamic.age;saved.dynamic.status='下書き';
      writeMonthly({context:copy(saved.dynamic),review_status:'draft'});
    }
    if(saved.dynamic)adapters[config.kind].saved?.(saved.dynamic);
    const actionLabel=button.textContent.trim();
    if(config.kind==='monthly-detail'){
      const entry=monthlyEntry();entry.review_status=button.value;writeMonthly(entry);renderMonthlyDetail();last=null;
    }
    const result=q('#mock-result');result.querySelector('h2').textContent=/進む/.test(button.textContent)?'承認前の確認（見本）':'操作結果（見本）';
    result.querySelector('p').textContent=`「${actionLabel}」を確認用の画面内で受け付けました。本番の保存・通知は行っていません。`;
    q('#mock-monthly-detail-link')?.remove();
    if(config.kind==='monthly'){
      const a=document.createElement('a');a.id='mock-monthly-detail-link';a.className='button button--primary';a.href=`monthly-review-${saved.dynamic.age}.html?preview=r1-2#review-status`;a.textContent='承認・文書情報へ（レビュー依頼）';result.querySelector('p').after(a);
    }
    const dl=result.querySelector('dl');dl.replaceChildren();saved.fields.filter(f=>f.value!==''&&f.value!==false).forEach(f=>{const dt=document.createElement('dt'),dd=document.createElement('dd');dt.textContent=f.name;dd.textContent=String(f.value);dl.append(dt,dd);});
    result.showModal();result.querySelector('h2').focus();status('仮保存済み。入力・修正へ戻って続けられます。');
  }
  function setValue(el,v){el.value=v;el.dispatchEvent(new Event('input',{bubbles:true}));}
  function fillValue(el){
    if(el.type==='date')return '2026-11-16';if(el.type==='month')return '2026-11';if(el.type==='week')return '2026-W47';if(el.type==='datetime-local')return '2026-11-16T10:00';
    if(el.type==='number')return el.name.includes('year')?'2026':String(el.min||'1');
    const numbers={height_cm:'105',weight_kg:'17',temperature:'36.5',heart_rate:'80',respiratory_rate:'22',fiscal_year:'2026',initial_target_id:'1'};
    return numbers[el.name]||(/owner|doctor|observer/.test(el.name)||el.id==='annual-owner'||el.hasAttribute('data-owner')?'見本 はなこ':'架空の入力例です。');
  }
  function loadState(){
    if(!ready)return;state=q('#mock-state').value;failed=false;last=null;clearFields();qa('.mock-feedback').forEach(e=>e.hidden=true);
    if(config.kind==='monthly-detail'){renderMonthlyDetail();status('保存した月案の内容を確認し、レビュー依頼・取り下げを試してください。');return;}
    if(config.kind==='monthly'&&state==='saved'){
      const entry=readMonthly(initial.age);
      if(entry){const data={...copy(entry.context),editable:entry.review_status!=='in_review',status:monthlyLabel(entry)};adapters.monthly.reset(data);saved={fields:snapshot(),dynamic:data};register();status('同じタブ内で保存した月案を表示しています。');return;}
    }
    if(adapters[config.kind]){
      let data=copy(initial);const fill=state==='filled'||state==='error';
      if(config.kind==='weekly')data.records.forEach((r,i)=>{if(state==='owner-cleared')r.owner_name='';for(const key of ['aim','activity','support_preparation','reflection'])r.sheet[key]=fill||['partial','owner-cleared'].includes(state)&&i<2?'架空の週案です。':'';r.sheet.days.forEach(d=>Object.keys(d).forEach(k=>d[k]=fill?'架空の活動です。':''));});
      if(config.kind==='monthly'){sessionStorage.removeItem(monthlyKey(data.age));if(state==='owner-cleared')data.owner_name='';data.sheet.fields={};Object.keys(data.definitions).forEach((k,i)=>{if(fill||['partial','owner-cleared'].includes(state)&&i%3===0)data.sheet.fields[k]={body:'架空の月案です。',origins:[]};});}
      if(config.kind==='annual'){data.owner_name=fill?'見本 はなこ':'';Object.values(data.sheet.fields).forEach((f,i)=>{f.body=fill||state==='partial'&&i%3===0?'一人ひとりの気持ちを受け止める、架空の年案の文章です。':'';});data.reflection=Array.from({length:4},(_,i)=>[fill||state==='partial'&&i===0?'架空の振り返りです。':'',fill?'架空の振り返りです。':'']);}
      adapters[config.kind].reset(data);
    }else{
      fields().forEach((el,i)=>{
        if(['checkbox','radio'].includes(el.type)||el.matches('[data-progress-period] input')||el.id==='progress-target-month')return;
        if(el.tagName==='SELECT'){if(el.required)el.value=state==='empty'||state==='partial'?'':([...el.options].find(o=>o.value&&!o.disabled)?.value||'');return;}
        if(el.type==='file'){const dt=new DataTransfer();if(['filled','error'].includes(state))dt.items.add(new File(['確認用の架空ファイルです。'],'sample.csv',{type:'text/csv'}));el.files=dt.files;return;}
        setValue(el,['filled','error'].includes(state)||state==='partial'&&!el.required&&i%3===0?fillValue(el):'');
      });
      if(config.kind==='reflection-request')qa('.reflection-review-values p').forEach(e=>e.textContent=['filled','error'].includes(state)?'架空の振り返りです。':'未入力');
    }
    if(state==='empty'&&config.kind==='weekly'){q('#weekly-month').value='';q('[name=target_week]').value='';}
    register();saved=null;dirty=false;status('状態を切り替えました。操作ボタンを押して案内を確認してください。');
  }
  function restore(){if(!saved){loadState();return;}if(saved.dynamic)adapters[config.kind].reset(copy(saved.dynamic));else saved.fields.forEach(f=>{const el=document.getElementById(f.id);if(!el||el.type==='file')return;if(['radio','checkbox'].includes(el.type))el.checked=f.value;else setValue(el,f.value);});clearFields();qa('.mock-feedback').forEach(e=>e.hidden=true);dirty=false;status('この画面内で最後に仮保存した内容へ戻しました。');}
  function leave(){q('#mock-leave').showModal();}
  document.addEventListener('submit',e=>{if(e.target.closest('#mock-business')){e.preventDefault();e.stopImmediatePropagation();if(e.target.method==='get'){if(e.target.matches('[data-progress-period]')){q('[data-progress-unsaved]').hidden=false;q('[data-progress-unsaved]').scrollIntoView({block:'center'});}else status('表示条件の変更は画面内の見本です。実データは検索しません。');return;}save(e.submitter||e.target.querySelector('button'));}},true);
  document.addEventListener('click',e=>{
    const b=e.target.closest('button');
    if(isAction(b)){e.preventDefault();e.stopImmediatePropagation();save(b);return;}
    if(b?.matches('#weekly-revert,#revert')){e.preventDefault();e.stopImmediatePropagation();restore();return;}
    if(b?.matches('#weekly-cancel')){e.preventDefault();e.stopImmediatePropagation();leave();return;}
    const a=e.target.closest('#mock-business a');
    if(config.kind==='monthly'&&a?.id==='document-link'){
      e.preventDefault();e.stopImmediatePropagation();const data=adapters.monthly.current();
      location.href=`monthly-review-${data.age}.html?preview=r1-2#review-status`;return;
    }
    if(a?.matches('[data-progress-navigation]')){e.preventDefault();e.stopImmediatePropagation();q('[data-progress-unsaved]').hidden=false;q('[data-progress-unsaved]').scrollIntoView({block:'center'});return;}
    if(a&&!a.closest('.mock-feedback')&&(a.dataset.originalHref||/^(\/|https?:)/.test(a.getAttribute('href')||''))){e.preventDefault();e.stopImmediatePropagation();if(/戻|取消|カレンダー|一覧/.test(a.textContent))leave();else status('移動先は確認用の対象一覧から選べます。本番ページには移動しません。');}
    if(b?.matches('#print-monthly,#excel-monthly,#annual-print,[data-meeting-export],#meeting-print')){e.preventDefault();e.stopImmediatePropagation();status('このモックでは入力とエラー案内を確認します。出力処理には接続しません。');}
  },true);
  document.addEventListener('input',e=>{
    if(!e.target.closest('#mock-business')||!ready)return;dirty=true;
    if(last&&box(last).dataset.error==='true'&&!failed)show(last,errors(last),false);
    if(config.kind==='daily-detail'&&e.target.name==='reflection_body')status('自動保存の見本：入力はこの画面内に保持しています。承認依頼はまだ行いません。');
  });
  document.addEventListener('change',e=>{
    if(e.target.name==='sensitivity'||e.target.name==='visibility'){const el=q('[data-restricted-recipients]');if(el)el.hidden=!(q('[name=visibility]:checked')?.value==='shared'&&q('[name=sensitivity]')?.value==='restricted');}
    if(last&&e.target.closest('#mock-business'))setTimeout(()=>show(last,errors(last),false),0);
  });
  window.addEventListener('DOMContentLoaded',()=>{
    initial=adapters[config.kind==='monthly-detail'?'monthly':config.kind]?.current?.();ready=true;
    if(['weekly','monthly'].includes(config.kind)){const option=document.createElement('option');option.value='owner-cleared';option.textContent=config.kind==='weekly'?'作成者を消した場合':'担任名を消した場合';q('#mock-state').append(option);}
    if(config.kind==='monthly'&&readMonthly(initial.age)){const option=document.createElement('option');option.value='saved';option.textContent='保存した月案';q('#mock-state').append(option);q('#mock-state').value='saved';}
    if(config.kind==='child-progress'){const p=q('[data-progress-unsaved]');if(p)p.hidden=false;}
    if(config.kind==='document-request')q('#mock-business details').open=true;
    if(config.kind==='meeting'){
      q('#note-title').readOnly=false;
      const body=document.createElement('textarea');body.name='meeting_body';body.setAttribute('aria-label','議事録の本文（簡易編集の見本）');body.style.cssText='width:100%;min-height:28rem;padding:20px';q('#editor').append(body);
      q('#save-btn').disabled=false;q('#sync-status').textContent='確認用・同期しません';q('#save-status').textContent='この画面内の見本';
      const take=q('#mark-selection-btn');take.disabled=false;take.addEventListener('click',()=>{const selected=body.value.slice(body.selectionStart,body.selectionEnd)||window.getSelection().toString();if(selected)setValue(q('#highlight-excerpt'),selected);else status('本文の文章を選択してから取り込んでください。');});
    }
    q('#mock-state').addEventListener('change',loadState);q('#mock-reset').addEventListener('click',loadState);
    q('#mock-jump').addEventListener('click',()=>{const b=operation();if(b){b.closest('details')?.setAttribute('open','');zone(b).scrollIntoView({block:'center'});b.focus({preventScroll:true});}});
    q('#mock-edit').addEventListener('click',()=>{q('#mock-result').close();last?.focus();});
    if(config.kind==='monthly-detail')q('#mock-edit').textContent='月案の確認へ戻る';
    q('[data-stay]').addEventListener('click',()=>q('#mock-leave').close());q('[data-discard]').addEventListener('click',()=>{q('#mock-leave').close();loadState();location.href='index.html';});
    q('[data-progress-stay]')?.addEventListener('click',()=>q('[data-progress-unsaved]').hidden=true);
    q('[data-progress-discard]')?.addEventListener('click',leave);
    loadState();
    window.FormMock.inspect=()=>({key:config.key,fields:fields().length,operations:buttons().length,errors:[...window.mockErrors],state,dirty,submittedToProduction:0});
  });
})();
