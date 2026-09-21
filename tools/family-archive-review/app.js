'use strict';
(() => {
  const app = document.querySelector('#app');
  const e = value => String(value ?? '').replace(/[&<>"']/g, ch => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[ch]));
  const code = f => `F-${String(f.id).padStart(5, '0')}`;
  const label = f => `${f.name}（${code(f)}）`;
  const guardianFields = ['last_name','first_name','last_name_kana','first_name_kana','relationship','parent_account_id','email','phone','workplace','workplace_address','workplace_phone'];
  const initial = () => [
    {id:101,name:'整理見本家',address:'架空市見本町1-1',phone:'',children:[],accounts:[],guardians:[{last_name:'整理',first_name:'はる',relationship:'母',email:'sample@example.invalid',workplace:'見本事業所'}],survey:1,enrollment:1,pending:0,note:'',reason:'',history:[]},
    {id:102,name:'見本家',address:'架空市見本町2-1',phone:'',children:[{id:201,name:'見本 ひなた',status:'在園'}],accounts:[],guardians:[],survey:0,enrollment:0,history:[]},
    {id:103,name:'保護者利用家',address:'架空市見本町3-1',phone:'',children:[],accounts:[{id:301,name:'見本 はる',status:'有効'}],guardians:[{last_name:'見本',first_name:'はる',email:'guardian@example.invalid',parent_account_id:301}],survey:1,enrollment:1,history:[]},
    {id:104,name:'保存見本家',address:'架空市保存町1-1',phone:'',children:[{id:202,name:'確認 あお',status:'卒園'}],accounts:[],guardians:[{last_name:'確認',first_name:'なつ',relationship:'父'}],survey:2,enrollment:1,archived:true,reason:'使用終了',note:'卒園後の記録を保管',archivedAt:'2026/09/20 10:00',history:[{text:'アーカイブ',at:'2026/09/20 10:00',reason:'使用終了',note:'卒園後の記録を保管'}]},
    {id:105,name:'入力途中家',address:'',phone:'',children:[],accounts:[],guardians:[{last_name:'入力',first_name:'',relationship:'',email:''}],survey:0,enrollment:0,history:[]},
    {id:106,name:'依頼見本家',address:'架空市依頼町1-1',phone:'',children:[],accounts:[],guardians:[],survey:0,enrollment:1,pending:1,history:[]},
    {id:107,name:'未使用見本家',address:'',phone:'',children:[],accounts:[],guardians:[],survey:0,enrollment:0,history:[]},
    {id:108,name:'保存見本家',address:'架空市別町2-2',phone:'',children:[],accounts:[],guardians:[],survey:0,enrollment:0,history:[]},
  ];
  let families = initial(), filter = 'active', query = '', currentId = null, returnTo = '#list';
  let saveError = false, csvMode = 'id', csvExcluded = false, csvValidated = false, csvDone = false, toastTimer;
  let importHistory = [];
  const find = id => families.find(f => f.id === Number(id));
  const now = () => new Date().toLocaleString('ja-JP', {hour12:false});
  const continuing = f => [
    f.children.some(c => c.status === '在園') && '在園中の園児がいます。',
    f.accounts.some(a => a.status === '有効') && '有効な保護者アカウントがあります。',
    f.pending && '保護者の初回入力依頼が進行中です。',
  ].filter(Boolean);
  const hasRecords = f => f.children.length || f.accounts.length || f.survey || f.enrollment;
  function toast(message) {
    clearTimeout(toastTimer);
    const el = document.querySelector('#toast');
    el.textContent = message; el.hidden = false;
    toastTimer = setTimeout(() => { el.hidden = true; }, 6500);
  }
  function go(hash) { if(location.hash === hash) render(); else location.hash = hash; }
  function reset() {
    families = initial(); filter = 'active'; query = ''; saveError = false; csvMode = 'id';
    csvExcluded = false; csvValidated = false; csvDone = false; returnTo = '#list'; importHistory = [];
    document.querySelector('#toast').hidden = true;
  }
  function actions(f, includeArchive = true) {
    if(f.archived) return `<a class="button" href="#records:${f.id}">内容・記録を見る</a><a class="button" href="#edit:${f.id}">編集</a><a class="button primary" href="#restore:${f.id}">元に戻す</a>`;
    return `<a class="button" href="#edit:${f.id}">編集</a><a class="button" href="#choices">この家族に園児追加</a>${includeArchive ? `<a class="button" href="#archive:${f.id}" aria-label="${code(f)}をアーカイブ">アーカイブ</a>` : ''}<a class="button danger" href="#delete:${f.id}">削除</a>`;
  }
  function card(f, detailed = false, withActions = false) {
    return `<section class="card" data-family="${f.id}">
      <div class="card-head"><div><h2>${e(f.name)} <small>${code(f)}</small></h2>
      <div class="badges"><span class="badge ${f.archived?'amber':''}">${f.archived?'家庭一覧でアーカイブ済み':'通常表示'}</span><span class="badge gray">${f.children.length}人の園児</span><span class="badge gray">${f.accounts.length}人の保護者</span></div></div>${withActions ? `<div class="actions">${actions(f)}</div>`:''}</div>
      <p>住所: ${e(f.address || '未登録')}</p><p>電話: ${e(f.phone || '未登録')}</p>
      <p>園児: ${e(f.children.map(c=>c.name + (detailed ? `（${c.status}）`:'')).join('、') || '未登録')}</p>
      <p>保護者: ${e(f.accounts.map(a=>a.name + (detailed ? `（${a.status}）`:'')).join('、') || '未登録')}</p>
      <p>保護者連絡先: ${f.guardians.length ? '' : '未登録'}</p>
      ${f.guardians.map(g=>`<div class="pl-4"><p>${e([g.last_name,g.first_name].filter(Boolean).join(' '))}${g.relationship?`（${e(g.relationship)}）`:''} — メール: ${e(g.email||'未登録')}${g.parent_account_id?'<span class="badge">アカウントと紐づけ済み</span>':''}</p>${detailed ? `<p>電話: ${e(g.phone||'未登録')}</p><p>勤務先: ${e(g.workplace||'未登録')}</p><p>勤務先住所: ${e(g.workplace_address||'未登録')}</p><p>勤務先電話: ${e(g.workplace_phone||'未登録')}</p>`:''}</div>`).join('')}
      ${f.archived?`<div class="notice warning small">${e(f.archivedAt)} ／ 操作者: 見本 管理者<br>理由: ${e(f.reason||'未記入')}${f.note?`<br>メモ: ${e(f.note)}`:''}</div>`:''}
    </section>`;
  }
  function dependencies(f) {
    return `<section class="review-section"><h2>この家族に紐づくデータ</h2><dl class="dependency">${[
      ['園児（卒園・退園を含む）',f.children.length,'人'],['保護者アカウント（停止済みを含む）',f.accounts.length,'人'],
      ['請求設定',0,'件'],['請求記録',0,'件'],['引落データ・請求設定変更履歴',0,'件'],['アンケート回答',f.survey,'件'],
      ['家族に結びつく写真',0,'件'],['保護者の初回入力依頼・記録',f.enrollment,'件']
    ].map(([name,n,u])=>`<div><dt>${name}</dt><dd>${n}${u}</dd></div>`).join('')}</dl></section>`;
  }
  const back = () => `<a class="back" href="${returnTo}">← ${returnTo === '#csv' ? 'CSVの確認へ戻る' : '家族一覧へ戻る'}</a>`;
  function list() {
    const matches = families.filter(f=>(filter==='all'||!!f.archived===(filter==='archived')) &&
      [f.name,code(f),...f.children.map(c=>c.name),...f.accounts.map(a=>a.name),...f.guardians.map(g=>`${g.last_name||''} ${g.first_name||''}`)].join(' ').includes(query));
    app.innerHTML = `<div class="page-head"><div><h1>家族一覧</h1><p>園児と保護者を家族単位で一元管理します。</p></div><a class="button primary" href="#edit:new">家族を追加</a></div>
      <div class="notice small">アーカイブは家庭一覧の整理に使います。紐づいている園児・保護者の利用や、進行中の入力依頼はそのまま続きます。</div>
      <div class="tabs" aria-label="家族の表示範囲">${[['active','通常表示'],['archived','アーカイブ済み'],['all','すべて']].map(([key,name])=>`<button type="button" data-filter="${key}" aria-pressed="${filter===key}">${name} <span class="small">${families.filter(f=>key==='all'||!!f.archived===(key==='archived')).length}</span></button>`).join('')}</div>
      <form class="search" id="search"><label class="field">家族・園児・保護者を検索<input name="q" placeholder="家族名・園児名・保護者名・家族番号" value="${e(query)}"></label><button class="primary">検索</button>${query?'<button type="button" id="clear-search">解除</button>':''}</form>
      <p class="muted small mb-3">${matches.length}家族${filter==='active'?' ／ アーカイブ済みは表示していません。':''}</p>
      ${filter==='archived'?'<div class="notice">記録と紐づけを保管しています。編集や園児・保護者の利用は続けられます。「元に戻す」で通常の家庭一覧に再表示します。</div>':''}
      ${matches.map(f=>card(f,false,true)).join('')||'<div class="card empty">該当する家族はありません。</div>'}`;
    app.querySelectorAll('[data-filter]').forEach(b=>b.onclick=()=>{filter=b.dataset.filter;list();});
    app.querySelector('#search').onsubmit=event=>{event.preventDefault();query=event.currentTarget.q.value.trim();list();};
    app.querySelector('#clear-search')?.addEventListener('click',()=>{query='';list();});
  }
  function archive(f, restoring = false) {
    if(!f) return missing();
    if(!!f.archived !== restoring) { toast('この家族の状態は変更済みです。一覧で確認してください。'); go('#list'); return; }
    const ongoing = continuing(f);
    app.innerHTML = `${back()}<div class="page-head"><div><h1>${restoring?'家庭を通常の一覧に戻す':'家族のアーカイブ'}</h1><p>家族名と家族番号、関連する記録を確認してください。</p></div></div>${card(f,true)}${dependencies(f)}
      <div class="notice"><strong>${restoring?'家庭を通常の一覧に再表示します。':'紐づけを残したまま、家庭の一覧を整理します。'}</strong><p>${restoring?'園児・保護者の状態や進行中の依頼は、そのまま引き継ぎます。':'家庭は「アーカイブ済み」タブに移ります。園児・保護者の利用、編集、入力依頼、通知・請求は続きます。家庭の選択やIDを指定したCSV更新もできます。'}</p></div>
      ${ongoing.length?`<div class="notice warning"><strong>このまま利用が続くデータ</strong><ul>${ongoing.map(s=>`<li>${s}</li>`).join('')}</ul><p>紐づけを外す作業は不要です。このまま${restoring?'一覧に戻せます':'アーカイブできます'}。</p></div>`:''}
      <form id="archive-form" class="card"><div id="save-error" role="alert"></div>
      ${restoring?'':`<div class="two-cols"><label class="field">アーカイブ理由（任意）<select name="reason"><option value="">選択してください</option>${['整理中・判断を保留','テスト登録','使用終了','重複の確認中','その他'].map(s=>`<option>${s}</option>`).join('')}</select></label><div></div></div>`}
      <label class="field mt-4">${restoring?'復帰時のメモ':'メモ'}（任意）<textarea name="note" maxlength="500" placeholder="${restoring?'例：再びこの家庭を使うため':'例：取込内容を確認するまで保留'}"></textarea></label>
      <p class="hint">${restoring?'「通常の一覧に戻す」':'「アーカイブする」'}を押した時点で保存します。「取消」では変更しません。</p>
      <div class="form-actions"><a class="button" href="${returnTo}">取消</a><button class="primary" type="submit">${restoring?'通常の一覧に戻す':'アーカイブする'}</button></div></form>`;
    app.querySelector('#archive-form')?.addEventListener('submit',event=>{
      event.preventDefault();
      const form=event.currentTarget;
      if(saveError) { saveError=false; form.querySelector('#save-error').innerHTML='<div class="notice error"><strong>保存できませんでした。</strong><p>家族の状態は変更していません。入力内容を残していますので、もう一度保存してください。（試用用エラー）</p></div>'; form.querySelector('#save-error').scrollIntoView({block:'center'}); return; }
      const values=new FormData(form), at=now();
      f.archived=!restoring;
      if(!restoring) {f.reason=values.get('reason'); f.note=values.get('note').trim(); f.archivedAt=at;}
      f.history.push({text:restoring?'通常の一覧に戻しました':'アーカイブ',at,reason:restoring?'':f.reason,note:values.get('note').trim()});
      csvValidated=false;
      if(returnTo!=='#csv') filter=restoring?'active':'archived';
      toast(`${label(f)}を${restoring?'通常の一覧に戻しました。':'アーカイブしました。紐づけと利用状態はそのままです。'}`); go(returnTo);
    });
  }
  function records(f) {
    if(!f) return missing();
    app.innerHTML=`${back()}<div class="page-head"><div><h1>家族の内容・記録</h1><p>アーカイブ後も、保存した記録を確認できます。</p></div><div class="actions">${f.archived?`<a class="button primary" href="#restore:${f.id}">元に戻す</a>`:`<a class="button" href="#archive:${f.id}">アーカイブ</a>`}</div></div>${card(f,true)}${dependencies(f)}
    <section class="card"><h2>保存されている記録</h2>${f.survey?`<details class="mt-4"><summary>アンケート回答（${f.survey}件）</summary><p>架空アンケート「連絡先確認」／回答済み</p><p>回答内容：登録した連絡先に変更ありません。</p></details>`:''}${f.enrollment?`<details class="mt-4"><summary>保護者の初回入力依頼・記録（${f.enrollment}件）</summary><p>${f.pending?'初回入力を依頼中（架空）':'初回入力を受付・反映済み（架空）'}</p><p>当時の登録内容と処理履歴を保管しています。</p></details>`:''}${!f.survey&&!f.enrollment?'<p>このモックで用意した回答・初回入力の記録はありません。</p>':''}</section>
    <section class="card"><h2>アーカイブ・復帰の履歴</h2>${f.history.map(h=>`<div class="history">${e(h.at)} ／ 見本 管理者 ／ ${e(h.text)}${h.reason?`<br>理由: ${e(h.reason)}`:''}${h.note?`<br>メモ: ${e(h.note)}`:''}</div>`).join('')||'<p>履歴はありません。</p>'}</section>`;
  }
  function deletion(f) {
    if(!f) return missing();
    app.innerHTML=`${back()}<h1 class="mb-4">家族の削除条件</h1>${card(f,true)}${dependencies(f)}
    ${hasRecords(f)?'<div class="notice error"><strong>この家族は削除できません。</strong><p>関連データが残っています。登録内容を確認し、必要な記録を保持してください。</p></div>':'<div class="notice warning">関連記録がないため、現行機能の削除対象です。このモックではアーカイブの操作を確認します。</div>'}
    <div class="notice"><strong>記録を残して一覧を整理する場合は、アーカイブできます。</strong><p>在園児や利用中の保護者などがいる場合は、アーカイブ確認画面でお知らせします。</p></div><div class="actions"><a class="button" href="${returnTo}">一覧へ戻る</a><a class="button primary" href="#archive:${f.id}">アーカイブを確認</a></div>`;
  }
  function edit(f) {
    const isNew=!f;
    app.innerHTML=window.REVIEW_TEMPLATES.form;
    const form=app.querySelector('form');
    if(f?.archived)form.insertAdjacentHTML('beforebegin','<div class="notice">家庭一覧でアーカイブ済みです。編集してもアーカイブ状態は維持されます。紐づく園児・保護者への反映は通常どおりです。</div>');
    const field=(name)=>form.elements.namedItem(name);
    if(isNew) {app.querySelector('h1').textContent='家族を追加';form.querySelector('button[type=submit]').textContent='家族を追加';}
    if(f) {
      field('family_name').value=f.name;field('home_phone').value=f.phone;field('home_address').value=f.address;
      for(let n=1;n<=2;n++) for(const key of guardianFields) field(`g${n}_${key}`).value=f.guardians[n-1]?.[key]||'';
      form.querySelectorAll('[name=child_ids]').forEach(el=>el.checked=f.children.some(c=>c.id===Number(el.value)));
      form.querySelectorAll('[name=parent_account_ids]').forEach(el=>el.checked=f.accounts.some(a=>a.id===Number(el.value)));
    }
    // Archiving organizes the family list; associations remain available.
    for(const [name,key] of [['child_ids','children'],['parent_account_ids','accounts']]) {
      form.querySelectorAll(`[name=${name}]`).forEach(el=>{
        const owner=families.find(x=>x[key].some(item=>item.id===Number(el.value)));
        const hint=el.closest('label').querySelector('.text-xs');
        if(hint)hint.textContent=owner ? owner.name+(owner.archived?'（アーカイブ済み）':'') : '家族未設定';
      });
    }
    // Give unchanged production controls explicit labels and sandbox file inputs.
    form.querySelectorAll('input:not([type=checkbox]),select').forEach((el,i)=>{if(!el.id)el.id=`edit-field-${i}`;const lab=el.parentElement.querySelector('label');if(lab)lab.htmlFor=el.id;});
    form.querySelectorAll('input[type=file]').forEach(el=>{el.disabled=true;el.insertAdjacentHTML('afterend','<p class="small muted">写真欄の位置確認用です。モックではファイルを読み込みません。</p>');});
    form.querySelectorAll('select[name$="_parent_account_id"]').forEach(el=>el.addEventListener('change',()=>{
      if(el.value==='301'){const prefix=el.name.slice(0,2);for(const [key,value] of Object.entries({last_name:'見本',first_name:'はる',email:'guardian@example.invalid'}))field(`${prefix}_${key}`).value=value;}
    }));
    form.addEventListener('submit',event=>{
      event.preventDefault();
      let entry=f;
      if(!entry){entry={id:Math.max(...families.map(x=>x.id))+1,children:[],accounts:[],guardians:[],history:[],survey:0,enrollment:0};families.push(entry);}
      entry.name=field('family_name').value.trim();entry.phone=field('home_phone').value;entry.address=field('home_address').value;
      const childPool=initial().flatMap(x=>x.children),accountPool=initial().flatMap(x=>x.accounts);
      const childIds=[...form.querySelectorAll('[name=child_ids]:checked:not(:disabled)')].map(el=>Number(el.value));
      const accountIds=[...form.querySelectorAll('[name=parent_account_ids]:checked:not(:disabled)')].map(el=>Number(el.value));
      families.filter(x=>x!==entry).forEach(x=>{x.children=x.children.filter(c=>!childIds.includes(c.id));x.accounts=x.accounts.filter(a=>!accountIds.includes(a.id));});
      entry.children=childPool.filter(c=>childIds.includes(c.id));entry.accounts=accountPool.filter(a=>accountIds.includes(a.id));
      entry.guardians=[1,2].map((n)=>{const values={...entry.guardians[n-1]};for(const key of guardianFields){const value=field(`g${n}_${key}`).value;if(value)values[key]=value;}return values;}).filter(g=>Object.values(g).some(Boolean));
      if(entry.archived)filter='archived';
      csvValidated=false;toast('モック内の家族情報を保存しました。アーカイブ状態は変えていません。');go('#list');
    });
  }
  function choices() {
    app.innerHTML=`<div class="page-head"><div><h1>家庭の選択候補を確認</h1><p>選択候補への影響だけを確認する補助画面です。園児登録画面そのものではありません。</p></div></div><section class="card"><label class="field">紐づける家庭<select id="family-choice"><option value="">選択してください</option>${families.map(f=>`<option value="${f.id}">${e(label(f))}${f.archived?'（家庭一覧でアーカイブ済み）':''}</option>`).join('')}</select></label><p class="mt-4">家庭の一覧を整理しても、園児・保護者の紐づけ先として選べます。既存の紐づけも保持します。</p><a href="#list" class="button mt-4">家族一覧へ</a></section>`;
  }
  function usage() {
    app.innerHTML=`<div class="page-head"><div><h1>園児・保護者の利用を確認</h1><p>今回の変更による利用状態を確認する補助画面です。実際のログイン・通知・請求処理には接続しません。</p></div></div>
      <section class="card"><h2>園児</h2>${families.flatMap(f=>f.children.map(c=>`<p>${e(c.name)} ／ ${e(c.status)} ／ ${e(label(f))}${f.archived?'（家庭一覧でアーカイブ済み）':''}</p>`)).join('')}</section>
      <section class="card"><h2>保護者アカウント</h2>${families.flatMap(f=>f.accounts.map(a=>`<p>${e(a.name)} ／ ${e(a.status)} ／ ${e(label(f))}${f.archived?'（家庭一覧でアーカイブ済み）':''}</p>`)).join('')}</section>
      <section class="card"><h2>進行中の初回入力依頼</h2>${families.filter(f=>f.pending).map(f=>`<p>${e(label(f))} ／ 依頼中${f.archived?'（家庭一覧でアーカイブ済み）':''}</p>`).join('')||'<p>ありません。</p>'}</section>
      <div class="notice">家庭をアーカイブしても、これらの一覧・利用状態は維持します。通知・請求も、現在の設定に従って続きます。</div><a class="button" href="#list">家族一覧へ</a>`;
  }
  function csv() {
    app.innerHTML=window.REVIEW_TEMPLATES.transfers;
    const importForm=app.querySelector('[data-import-form]');
    importForm.querySelector('[name=file]').disabled=true;
    importForm.querySelector('[name=file]').required=false;
    importForm.insertAdjacentHTML('afterbegin',`<div class="notice warning small">ファイル送信は行いません。次の架空CSVサンプルで事前検証を試せます。</div><label class="field mb-4">架空CSVサンプル<select id="csv-sample"><option value="id" ${csvMode==='id'?'selected':''}>IDあり：保存見本家を更新</option><option value="name" ${csvMode==='name'?'selected':''}>IDなし：同名の保存見本家がある</option></select></label><details class="mb-4"><summary>サンプルの内容（2行）</summary><p class="small">2行目：${csvMode==='id'?'ID 104':'ID空欄'} ／ 保存見本家 ／ 住所を更新<br>3行目：ID 101 ／ 整理見本家 ／ 住所を更新</p></details>`);
    importForm.insertAdjacentHTML('afterend','<div id="csv-result" class="mt-6"></div>');
    const exportForm=app.querySelector('#filtered-export-form');
    const exportScope=exportForm.elements.archive_scope;
    exportScope.querySelector('[value=active]').textContent='通常表示のみ';
    exportForm.elements.dataset.addEventListener('change',()=>{exportScope.disabled=exportForm.elements.dataset.value!=='families';});
    app.querySelectorAll('[data-dataset-toggle]').forEach(el=>el.addEventListener('change',()=>{
      let selected=[...app.querySelectorAll('[data-dataset-toggle]:checked')].map(x=>x.value);
      if(!selected.length){el.checked=true;selected=[el.value];}
      app.querySelectorAll('[data-dataset-row]').forEach(row=>row.hidden=!selected.includes(row.dataset.datasetRow));
      app.querySelectorAll('select[name=dataset]').forEach(select=>{[...select.options].forEach(opt=>{opt.disabled=!selected.includes(opt.value);opt.hidden=opt.disabled;});if(!selected.includes(select.value))select.value=selected[0];});
    }));
    app.querySelector('#csv-sample').onchange=event=>{csvMode=event.target.value;csvExcluded=false;csvValidated=false;csvDone=false;csv();};
    importForm.onsubmit=event=>{event.preventDefault();if(importForm.elements.dataset.value!=='families'){toast('このモックでの事前検証は「家庭」を選んでください。');return;}csvValidated=true;csvDone=false;csvResult();};
    importForm.elements.dataset.addEventListener('change',()=>{csvValidated=false;csvDone=false;csvResult();});
    exportForm.onsubmit=event=>{event.preventDefault();if(exportForm.elements.dataset.value!=='families'){toast('家庭のアーカイブ対象範囲を確認するモックです。');return;}exportMessage(exportScope.value);};
    app.querySelector('form[action="#"]:not(#filtered-export-form):not([data-import-form])')?.addEventListener('submit',event=>{event.preventDefault();toast('帳票の入力欄は現行画面の位置確認用です。');});
    // Existing non-family file controls remain visible, but no real file is read.
    app.querySelectorAll('input[type=file]').forEach(el=>{el.disabled=true;el.required=false;});
    renderImportHistory();
    csvResult();
  }
  function renderImportHistory() {
    if(!importHistory.length)return;
    const tbody=app.querySelector('section.mt-6 table tbody');
    if(tbody)tbody.innerHTML=importHistory.map(h=>`<tr><td>${e(h.at)}</td><td>家庭</td><td>成功（モック）</td><td>0</td><td>${h.count}</td><td>0</td><td>見本 管理者</td></tr>`).join('');
  }
  function exportMessage(scope) {
    const n=families.filter(f=>scope==='all'||!!f.archived===(scope==='archived')).length;
    toast(`模擬出力：${scope==='all'?'アーカイブ済みを含む':scope==='archived'?'アーカイブ済みのみ':'通常表示のみ'} ${n}家族。実ファイルは作成しません。`);
  }
  function csvResult() {
    const result=app.querySelector('#csv-result');if(!result)return;
    if(!csvValidated){result.innerHTML='<p class="muted small">架空サンプルを選び、「事前検証」を押してください。復帰や編集の後も、再度検証します。</p>';return;}
    if(csvDone){result.innerHTML='<div class="notice success" role="status">モック内のインポートが完了しました。</div>';return;}
    const targets=[find(104),find(101)];
    const errors=targets.map((f,i)=>({f,row:i+2,problem:i===0&&csvMode==='name'?'ambiguous':''})).filter(x=>x.problem && !(csvExcluded&&x.row===2));
    const count=csvExcluded?1:2;
    result.innerHTML=`<h3>検証結果 <span class="badge gray">家庭</span></h3><div class="stats"><div>対象行<strong>${count}</strong></div><div>新規<strong>0</strong></div><div>更新<strong>${count-errors.length}</strong></div><div>要確認<strong class="${errors.length?'bad':''}">${errors.length}</strong></div></div>
    ${csvExcluded?'<p class="small mb-3">2行目は今回の取込から外しています。元のファイルは変更しません。</p>':''}
    ${errors.length?`<div class="table-wrap"><table class="errors"><thead><tr><th>行</th><th>家庭</th><th>内容</th></tr></thead><tbody>${errors.map(x=>`<tr><td>${x.row}</td><td>${e(x.f.name)}</td><td>同名の家庭が2件あります（F-00104・F-00108）。対象の家庭IDを指定して再検証してください。</td></tr>`).join('')}</tbody></table></div><div class="notice warning small">同名の家庭が複数あるため、IDの指定が必要です。アーカイブだけで別の家庭と判断することはありません。</div>`:
    `<details open class="card"><summary>変更する内容（${count}項目）</summary>${targets.filter((_,i)=>!(csvExcluded&&i===0)).map(f=>`<p>${e(label(f))}${f.archived?' ／ アーカイブ状態を維持':''} ／ 住所<br>${e(f.address||'未登録')} → 架空市更新町9-9</p>`).join('')}</details>`}
    <label class="flex gap-2 items-center mt-4"><input type="checkbox" id="exclude-row" ${csvExcluded?'checked':''}>2行目を今回の取込から外す</label><p id="recheck-hint" role="status" class="small muted"></p><button type="button" id="csv-recheck" class="mt-4">対象行を再検証</button><button type="button" id="csv-commit" class="primary w-full mt-4" ${errors.length?'disabled':''}>インポート実行（モック内）</button>`;
    result.querySelector('#exclude-row').onchange=()=>{result.querySelector('#csv-commit').disabled=true;result.querySelector('#recheck-hint').textContent='対象行を変更しました。「対象行を再検証」を押してください。';};
    result.querySelector('#csv-recheck').onclick=()=>{csvExcluded=result.querySelector('#exclude-row').checked;csvResult();};
    result.querySelector('#csv-commit').onclick=()=>{
      if(errors.length)return;
      targets.filter((_,i)=>!(csvExcluded&&i===0)).forEach(f=>f.address='架空市更新町9-9');
      importHistory.unshift({at:now(),count});renderImportHistory();csvDone=true;csvResult();toast('架空データへの取込を試しました。本番データは変更されません。');
    };
  }
  function missing(){app.innerHTML='<h1>家族が見つかりません</h1><a class="button mt-4" href="#list">一覧へ戻る</a>';}
  function render() {
    const [page,id]=(location.hash.slice(1)||'list').split(':');currentId=id;
    if(page==='list')returnTo='#list';
    document.querySelectorAll('[data-nav]').forEach(a=>a.classList.toggle('active',a.dataset.nav===(['csv','choices','usage'].includes(page)?page:'list')));
    if(page==='list')list();else if(page==='archive')archive(find(id));else if(page==='restore')archive(find(id),true);
    else if(page==='records')records(find(id));else if(page==='delete')deletion(find(id));else if(page==='edit')edit(find(id));
    else if(page==='choices')choices();else if(page==='usage')usage();else if(page==='csv')csv();else missing();
    window.scrollTo({top:0});app.focus({preventScroll:true});
  }
  // All navigation stays within this static mock, including baseline fragment links.
  document.addEventListener('click',event=>{
    const anchor=event.target.closest('a');if(!anchor)return;
    const href=anchor.getAttribute('href')||'';
    if(anchor.hasAttribute('data-csv-restore'))returnTo='#csv';
    if(href.startsWith('#'))return;
    event.preventDefault();
    if(href==='/families/')go('#list');
    else if(href.startsWith('/data-transfers/export/families.'))exportMessage('active');
    else if(href.startsWith('/data-transfers/export/'))toast('このモックでは家庭の出力範囲を確認できます。');
    else if(href.startsWith('/data-transfers/templates/'))toast('テンプレートの位置確認用です。このモックでは架空CSVサンプルを使用します。');
    else if(href.startsWith('/data-transfers'))go('#csv');
    else toast('このリンクは現行画面の位置確認用です。');
  });
  document.addEventListener('submit',event=>event.preventDefault());
  document.querySelector('#reset').onclick=()=>{reset();document.querySelector('#scenario').value='list';go('#list');toast('架空データを初期状態に戻しました。');};
  document.querySelector('#scenario').onchange=event=>{
    const value=event.target.value;reset();
    if(value==='error')saveError=true;
    if(value==='continued'){
      [102,103,106].forEach(id=>{const f=find(id);f.archived=true;f.archivedAt=now();f.reason='整理中・判断を保留';f.note='紐づけと利用を続けたまま整理';});
      go('#usage');return;
    }
    if(value.startsWith('csv-')){csvMode=value==='csv-name'?'name':'id';csvValidated=true;go('#csv');return;}
    const routes={list:'#list',ready:'#archive:101',empty:'#edit:new',partial:'#edit:105',child:'#archive:102',parent:'#archive:103',pending:'#archive:106',restore:'#restore:104',error:'#archive:101'};
    go(routes[value]);
  };
  addEventListener('hashchange',render);render();
})();
