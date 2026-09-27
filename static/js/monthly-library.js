(() => {
  'use strict';
  const root = document.getElementById('drive-monthly-plan');
  if (!root) return;
  const q = s => root.querySelector(s), all = s => [...root.querySelectorAll(s)];
  const clone = value => structuredClone(value);
  const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;', '<':'&lt;', '>':'&gt;', '"':'&quot;', "'":'&#39;'}[c]));
  const boot = JSON.parse(document.getElementById('monthly-library-boot').textContent);
  const cache = new Map();
  const scopeKey = c => `${c.classroom_id}/${c.target_month}/${c.age}`;
  const contents = c => JSON.stringify({fields:c.sheet.fields, owner:c.owner_name});
  function entry(context) {
    return {context, saved:clone(context), undo:[], child:context.sheet.children[0]?.ref || '',
      field:context.sheet.children[0] ? `${context.sheet.children[0].ref}:life` : 'common:goal', page:0};
  }
  let current = entry(boot);
  cache.set(scopeKey(boot), current);
  let before = null, showHistory = false, mode = 'original', keyword = '', saving = false, switching = false;
  let searchSequence = 0, historySequence = 0, searchTimer, candidateRows = [], searchController;
  let historyData = null;
  const aiCandidates = new Map();
  let aiJob = null;
  const aiKey = () => `${scopeKey(ctx())}/${current.field}`;
  const originKey = o => o.kind==='ai' ? `ai/${o.candidate_id}` : `${o.source_key}/${o.phrase_id}`;
  const ctx = () => current.context, individual = () => ctx().age < 3;
  const fields = () => ctx().sheet.fields;
  const dirty = item => contents(item.context) !== contents(item.saved);
  const editable = () => ctx().editable;
  const body = key => fields()[key]?.body || '';
  const label = key => ctx().definitions[key]?.label || '';
  const childName = ref => ctx().sheet.children.find(c => c.ref === ref)?.name || '';
  const selectedCell = () => all('[data-cell]').find(el => el.dataset.cell === current.field);
  const announce = (text, error = false) => { q('#message').textContent = text; q('#message').dataset.error = String(error); };
  const params = extra => new URLSearchParams({classroom_id:ctx().classroom_id,
    target_month:ctx().target_month, age:ctx().age,
    ...(ctx().document_id ? {document_id:ctx().document_id} : {}), ...extra});

  async function api(path, options = {}) {
    const response = await fetch(`/plans/monthly-library/${path}`, {credentials:'same-origin',
      ...options, headers:{...options.headers, 'Accept':'application/json'}});
    if (response.redirected) throw new Error('職員のログインを確認してください。入力内容は保持しています。');
    let data;
    try { data = await response.json(); } catch { throw new Error('応答を読み込めません。入力内容は保持しています。'); }
    if (!response.ok) throw new Error(typeof data.detail === 'string' ? data.detail : '入力内容を確認してください。保存は完了していません。');
    return data;
  }
  function remember(snapshot) {
    current.undo.push(snapshot || {fields:clone(fields()), owner:ctx().owner_name});
    if (current.undo.length > 30) current.undo.shift();
  }
  function commitEdit() {
    if (before && JSON.stringify(before) !== JSON.stringify({fields:fields(), owner:ctx().owner_name})) remember(before);
    before = null;
    status();
  }
  function status() {
    q('#undo').disabled = !editable() || !current.undo.length;
    q('#save').hidden = !editable();
    q('#save').disabled = saving;
    q('#save').textContent = saving ? '保存中…' : '下書きを保存';
    q('#revert').hidden = !editable() || !dirty(current);
    q('#save-state').textContent = dirty(current) ? '未保存の変更があります' : ctx().document_id ? '保存済み' : '未保存';
    q('#count').textContent = `${Object.values(fields()).filter(f => f.body?.trim()).length}欄に入力済み`;
    q('#document-status').textContent = ctx().status;
    q('#document-link').hidden = !ctx().document_id;
    q('#document-link').href = `/plans/documents/${ctx().document_id}`;
  }
  function autosize(el) { el.style.height = 'auto'; el.style.height = `${Math.max(el.scrollHeight, parseFloat(getComputedStyle(el).minHeight) || 0)}px`; }
  function cell(key) {
    const target = key.startsWith('child:') ? childName(key.split(':').slice(0,2).join(':')) : ctx().classroom_name;
    return `<textarea rows="1" class="cell" data-cell="${esc(key)}" aria-label="${esc(target+' / '+label(key))}" data-active="${key === current.field}" ${editable() ? '' : 'readonly'} spellcheck="false">${esc(body(key))}</textarea>`;
  }
  function common(keys) { return `<table class="common" aria-label="クラス共通欄"><thead><tr>${keys.map(k=>`<th>${esc(label(k))}</th>`).join('')}</tr></thead><tbody><tr>${keys.map(k=>`<td>${cell(k)}</td>`).join('')}</tr></tbody></table>`; }
  const monthLabel = () => `${ctx().target_month.slice(0,4)}年${Number(ctx().target_month.slice(5))}月`;
  function head() {
    return `<table class="head" aria-label="基本情報"><tbody><tr><td rowspan="2" class="title" style="width:30%"><small>${esc(monthLabel())}</small>${individual() ? '乳児指導計画' : '月 指導計画'}</td><th>クラス</th><th>担任</th><th>園長印</th><th>主任印</th>${individual()?'<th>行事</th>':''}</tr><tr><td>${esc(ctx().classroom_name)}</td><td><input class="meta" data-owner aria-label="担任名" maxlength="100" value="${esc(ctx().owner_name)}" ${editable()?'':'readonly'}></td><td></td><td></td>${individual()?`<td>${cell('common:events')}</td>`:''}</tr></tbody></table>`;
  }
  function personalHead(first) { return `<colgroup><col style="width:12%"><col style="width:23%"><col style="width:21%"><col style="width:22%"><col style="width:22%"></colgroup><thead><tr><th rowspan="2">${first}</th><th colspan="2">個人別保育計画</th><th rowspan="2">環境構成・<br>援助活動</th><th rowspan="2">評価・反省</th></tr><tr><th>生活・健康<small>食事・睡眠・排泄・清潔</small></th><th>あそび<small>あそび・ことば</small></th></tr></thead>`; }
  function pages() {
    const total = ctx().sheet.children.length, sizes = [], pattern = ctx().age === 0 ? [6] : ctx().age === 1 ? [7,8] : [7,8,7];
    let left = total, index = 0;
    while (left > 0) { const size = Math.min(left, pattern[index % pattern.length]); sizes.push(size); left -= size; index++; }
    return sizes.length ? sizes : [0];
  }
  function pageFor(ref) {
    const index = ctx().sheet.children.findIndex(c=>c.ref === ref);
    let n = 0;
    for (const [page,size] of pages().entries()) { n += size; if (index < n) return page; }
    return 0;
  }
  function roster() {
    const start = pages().slice(0,current.page).reduce((a,b)=>a+b,0);
    const children = ctx().sheet.children.slice(start,start+pages()[current.page]);
    return `<table class="roster" aria-label="個人別保育計画">${personalHead('名前')}<tbody>${children.map(c=>{
      const [y,m] = ctx().target_month.split('-').map(Number), birthday = c.birth_date.split('-').map(Number);
      const months = (y-birthday[0])*12 + m-birthday[1] - (birthday[2]>1 ? 1 : 0);
      return `<tr data-child-row="${esc(c.ref)}"><th class="name"><button type="button" data-child="${esc(c.ref)}">${esc(c.name)}<small>${Math.floor(Math.max(0,months)/12)}歳${Math.max(0,months)%12}か月</small></button></th>${ctx().personal.map(([k])=>`<td>${cell(c.ref+':'+k)}</td>`).join('')}</tr>`;
    }).join('') || '<tr><td colspan="5">このクラス・対象月に該当する園児がいません。</td></tr>'}</tbody></table>`;
  }
  function group() {
    const cols = ctx().columns;
    const rows = ctx().domains.map(([domain,title],i)=>`<tr>${i===0?'<th>養護</th>':i===1?'<th rowspan="5">教育</th>':''}<th>${esc(title)}</th>${cols.map(([col])=>`<td>${cell('group:'+domain+':'+col)}</td>`).join('')}</tr>`).join('');
    const [year,month] = ctx().target_month.split('-').map(Number), days = new Date(year,month,0).getDate();
    return `<div class="group-layout"><div class="group-main">${head()}${common(['common:goal','common:home'])}<table class="group-grid" aria-label="養護・教育・食育"><colgroup><col style="width:5%"><col style="width:9%">${cols.map(()=>'<col style="width:21.5%">').join('')}</colgroup><thead><tr><th colspan="2"></th>${cols.map(([,title])=>`<th>${esc(title)}</th>`).join('')}</tr></thead><tbody>${rows}<tr><th colspan="2">食育</th><td colspan="4">${cell('group:food')}</td></tr></tbody></table>${common(['common:review'])}</div><table class="calendar" aria-label="行事・活動"><colgroup><col style="width:20px"><col style="width:20px"><col></colgroup><thead><tr><th>日</th><th>曜日</th><th>行事・活動</th></tr></thead><tbody>${Array.from({length:days},(_,i)=>{const day=i+1,week=new Date(year,month-1,day).getDay();return `<tr><td>${day}</td><td>${'日月火水木金土'[week]}</td><td>${cell('event:'+day)}</td></tr>`;}).join('')}</tbody></table></div>`;
  }
  function highlight() {
    all('[data-cell]').forEach(el=>el.dataset.active=String(el.dataset.cell===current.field));
    all('[data-child]').forEach(el=>el.setAttribute('aria-pressed',String(el.dataset.child===current.child)));
    all('[data-past-field]').forEach(el=>el.dataset.active=String(current.field===`${current.child}:${el.dataset.pastField}`));
  }
  function paper() {
    q('#form').innerHTML = individual() ? head()+common(['common:goal','common:home','common:review'])+'<section id="past-plans" class="past-plans" hidden></section><div id="current-month" class="current-month" hidden></div>'+roster() : group();
    q('#template').textContent = '様式：'+ctx().template[1];
    q('#template').href = 'https://docs.google.com/spreadsheets/d/'+ctx().template[2]+'/edit';
    all('textarea.cell').forEach(autosize);
    renderHistory(); highlight();
  }
  function pickers() {
    q('#classroom').value=ctx().classroom_id; q('#month').value=ctx().target_month; q('#age').value=ctx().age;
    q('#scope').textContent=individual()?'個人別の様式':'集団の様式';
    q('#child-wrap').hidden=!individual();
    q('#child').innerHTML=ctx().sheet.children.map(c=>`<option value="${esc(c.ref)}">${esc(c.name)}</option>`).join('');
    q('#child').value=current.child;
    q('#page').innerHTML=pages().map((_,i)=>`<option value="${i}">${i+1} / ${pages().length}ページ</option>`).join('');
    q('#page').value=current.page;
  }
  function originHtml(o) {
    if(o.kind==='ai')return `<p>AI提案 · ${esc(o.model)}<br>${esc(o.created_at)}<br>${esc(o.age)}歳児 ${esc(o.month)}月 / ${esc(o.item)}<br>年齢・月・対象欄から生成（参考原文なし）<br>${esc(o.text)}</p>`;
    return `<p>原文 · ${esc(o.year)}年 ${esc(o.age)}歳児 ${esc(o.month)}月<br>${esc(o.relative_path)} / ${esc(o.sheet)}<br>${esc(o.section)} / ${esc(o.ryoiki || '')} / ${esc(o.item)}<br>文例 ${o.phrase_id}・元セルID ${o.cell_id}<br>${esc(o.text)}</p>`;
  }
  function origins() { const origins=fields()[current.field]?.origins || []; q('#origins').hidden=!origins.length; q('#origin-list').innerHTML=origins.map(originHtml).join(''); }
  function candidateMarks() {
    all('[data-candidate]').forEach(b=>{
      const used=body(current.field).includes(candidateRows[Number(b.dataset.candidate)].text);
      b.classList.toggle('is-added',used); b.setAttribute('aria-disabled',String(used)); b.querySelector('.used').hidden=!used;
    });
  }
  function displayCandidates() {
    q('#candidates').innerHTML=candidateRows.map((row,i)=>`<button type="button" class="candidate" data-candidate="${i}">${esc(row.text)}<span class="used" hidden>✓ 反映済み</span></button>`).join('') || '<p class="no-results">該当する候補がありません。</p>';
    q('#candidate-count').textContent=`${candidateRows.length}件表示`;
    q('#candidate-source-list').innerHTML=candidateRows.map(originHtml).join(''); candidateMarks();
  }
  function aiPanel() {
    const enabled=ctx().ai?.enabled && editable() && !!ctx().definitions[current.field]?.section;
    q('#generate').disabled=!enabled || !!aiJob;
    q('#generate').textContent=aiCandidates.has(aiKey())?'候補を再生成':'候補を生成';
    q('#ai-info').textContent=ctx().ai?.enabled
      ? `実機のOllama（${ctx().ai.model}）で生成します。送る情報は年齢・月・対象欄のみです。園児名・入力本文・過去の個人記録・原文は送りません。提案内容を確認して選んでください。評価・反省は振り返りの観点を提案します。`
      : 'AI提案は未接続です。';
    const cached=aiCandidates.get(aiKey());
    q('#ai-progress').textContent=aiJob ? (aiJob.key===aiKey()
      ? '候補を生成中です。初回はモデルの読み込みに1〜2分かかることがあります。入力は続けられます。'
      : '別の欄の候補を生成中です。') : cached?.error || '';
    const words=keyword.normalize('NFKC').toLowerCase().trim().split(/\s+/).filter(Boolean);
    candidateRows=(cached?.items || []).filter(row=>words.every(word=>row.text.normalize('NFKC').toLowerCase().includes(word)));
    if(cached?.items?.length)displayCandidates();
    else q('#candidates').textContent=enabled?'「候補を生成」を押すと、この欄の提案を作成します。':'';
  }
  async function generateAI() {
    if(aiJob || !editable() || !ctx().ai?.enabled)return;
    const key=aiKey(), controller=new AbortController();
    const payload={classroom_id:ctx().classroom_id,target_month:ctx().target_month,
      age:ctx().age,field:current.field,document_id:ctx().document_id};
    aiJob={key,controller}; aiPanel();
    const timeout=setTimeout(()=>controller.abort(),160000);
    try {
      const token=document.querySelector('meta[name="csrf-token"]')?.content || '';
      const data=await api('generate',{method:'POST',signal:controller.signal,
        headers:{'Content-Type':'application/json','X-CSRF-Token':token},body:JSON.stringify(payload)});
      aiCandidates.set(key,{items:data.items});
    } catch(error) {
      const previous=aiCandidates.get(key)?.items || [];
      aiCandidates.set(key,{items:previous,error:error.name==='AbortError'
        ? 'AI生成が時間切れになりました。入力は保持されています。しばらくして再試行してください。' : error.message});
    } finally {
      clearTimeout(timeout); aiJob=null;
      // Results remain with the requested field, even after a scope/tab change.
      if(mode==='ai')search();
    }
  }
  async function search(more=false) {
    clearTimeout(searchTimer);
    const sequence=++searchSequence;
    searchController?.abort(); searchController=new AbortController();
    q('#more').hidden=true;
    if (!more) { candidateRows=[]; q('#candidate-count').textContent=''; q('#candidate-source-list').textContent=''; }
    all('[data-mode]').forEach(b=>b.setAttribute('aria-pressed',String(b.dataset.mode===mode)));
    q('#ai-controls').hidden=mode!=='ai' || !editable() || !ctx().definitions[current.field]?.section;
    q('#candidates').removeAttribute('aria-busy');
    if (!editable()) { q('#candidates').innerHTML='<p class="no-results">閲覧中です。修正は月案の編集画面から行います。</p>'; return; }
    if (!ctx().definitions[current.field]?.section) { q('#candidates').innerHTML='<p class="no-results">この欄は直接入力してください。</p>'; return; }
    if (mode==='ai') { aiPanel(); return; }
    q('#candidates').setAttribute('aria-busy','true');
    if (!more) q('#candidates').innerHTML='<p class="no-results">文例を検索しています…</p>';
    try {
      const data=await api('candidates?'+params({field:current.field,keyword,offset:more?candidateRows.length:0}),{signal:searchController.signal});
      if(sequence!==searchSequence)return;
      candidateRows=more?candidateRows.concat(data.items):data.items;
      displayCandidates(); q('#more').hidden=!data.has_more;
    } catch(error) {
      if(sequence!==searchSequence || error.name==='AbortError')return;
      q('#candidates').innerHTML=`<p class="no-results">${esc(error.message)}</p>`;
    } finally { if(sequence===searchSequence)q('#candidates').removeAttribute('aria-busy'); }
  }
  function panel(load=true) {
    q('#target').textContent=current.field.startsWith('child:')?childName(current.child):ctx().classroom_name+'・クラス共通';
    q('#field-label').textContent=label(current.field); origins(); highlight();
    if(load)search();
    status();
  }
  function renderHistory() {
    const visible=individual() && showHistory && !!current.child, section=q('#past-plans');
    root.dataset.history=String(visible);
    q('#history-toggle').hidden=!individual() || !current.child;
    q('#history-toggle').setAttribute('aria-expanded',String(visible));
    q('#history-toggle').textContent=visible?'過去3か月を閉じる':'過去3か月を表示';
    q('#page-wrap').hidden=!individual() || visible || pages().length===1;
    all('[data-child-row]').forEach(row=>row.hidden=visible && row.dataset.childRow!==current.child);
    if(!section)return;
    section.hidden=!visible; q('#current-month').hidden=!visible;
    if(!visible)return;
    q('#current-month').textContent=monthLabel()+'の入力 · '+childName(current.child);
    if(!historyData) { section.textContent='過去の記録を読み込んでいます…'; return; }
    if(historyData.error) { section.textContent=historyData.error; return; }
    const rows=historyData.months.map(month=>{
      const name=esc(month.month), records=month.records;
      let html=records.length?records.map(record=>`<tr><th>${name}<small class="record-meta">${esc(record.classroom)} / ${record.age}歳児 / ${esc(record.status)}<br>最新保存版 <a href="/plans/documents/${record.document_id}" target="_blank" rel="noopener">文書</a></small></th>${ctx().personal.map(([key])=>`<td data-past-field="${key}"><p class="past-body">${esc(record.fields[key].body)}</p></td>`).join('')}</tr>`).join(''):`<tr><th>${name}</th><td colspan="4" class="past-empty">${month.legacy.length?'旧様式の記録があります（下に原文を表示）':'この月の記録はありません'}</td></tr>`;
      html+=month.legacy.map(record=>`<tr><th>${name}<small>旧様式</small></th><td colspan="4"><details class="past-legacy"><summary>${esc(record.title)} / ${esc(record.status)}</summary>${record.sections.map(s=>`<p><strong>${esc(s.title)}</strong><br>${esc(s.body)}</p>`).join('')}<a href="/plans/documents/${record.document_id}" target="_blank" rel="noopener">元の文書</a></details></td></tr>`).join('');
      return html;
    }).join('');
    section.innerHTML=`<div class="past-heading"><h3>${esc(childName(current.child))} · 過去3か月</h3><small>各文書の最新保存版（下書きを含む）・閲覧専用</small></div><table class="past-table" aria-label="過去3か月の個人計画と反省">${personalHead('月')}<tbody>${rows}</tbody></table>`;
    highlight();
  }
  async function loadHistory() {
    const sequence=++historySequence;
    historyData=null; renderHistory();
    if(!individual() || !showHistory || !current.child)return;
    try { const data=await api('history?'+params({child_ref:current.child})); if(sequence!==historySequence)return; historyData=data; }
    catch(error) { if(sequence!==historySequence)return; historyData={error:error.message}; }
    renderHistory();
  }
  function render() { pickers(); paper(); panel(); status(); }
  function selectChild(ref) {
    commitEdit(); current.child=ref; current.field=ref+':'+(current.field.startsWith('child:')?current.field.split(':')[2]:'life');
    current.page=pageFor(ref); pickers(); paper(); panel(); loadHistory(); selectedCell()?.focus({preventScroll:true});
  }
  async function switchScope() {
    if(saving || switching) { pickers(); return; }
    commitEdit();
    const desired={classroom_id:Number(q('#classroom').value),target_month:q('#month').value,age:Number(q('#age').value)};
    if(!/^\d{4}-\d{2}$/.test(desired.target_month)){pickers();return;}
    switching=true;
    all('#classroom,#month,#age').forEach(el=>el.disabled=true);
    searchSequence++; searchController?.abort(); historySequence++;
    try {
      const key=scopeKey(desired);
      let next=cache.get(key);
      if(!next) { next=entry(await api('context?'+new URLSearchParams(desired))); cache.set(key,next); }
      current=next; before=null; historyData=null;
      render(); loadHistory();
      announce([...cache.values()].some(dirty)?'未保存の入力は、この画面で対象を戻すと再表示できます。画面を閉じる前に保存してください。':'対象を切り替えました。');
    } catch(error) { pickers(); announce(error.message,true); panel(); }
    finally { switching=false; all('#classroom,#month,#age').forEach(el=>el.disabled=false); }
  }
  async function save() {
    if(saving || !editable())return;
    commitEdit();
    const item=current, snapshot=clone(ctx()), sentContents=contents(snapshot);
    const payload={document_id:snapshot.document_id,lock_version:snapshot.lock_version,
      classroom_id:snapshot.classroom_id,target_month:snapshot.target_month,age:snapshot.age,
      owner_name:snapshot.owner_name,fields:Object.fromEntries(Object.entries(snapshot.sheet.fields).map(([key,cell])=>[key,
        {body:cell.body,origins:(cell.origins||[]).map(o=>o.kind==='ai'?{kind:'ai',token:o.token}:{source_key:o.source_key,phrase_id:o.phrase_id})}]))};
    saving=true; status();
    try {
      const token=document.querySelector('meta[name="csrf-token"]')?.content || document.querySelector('input[name="csrf_token"]')?.value || '';
      const data=await api('save',{method:'POST',headers:{'Content-Type':'application/json','X-CSRF-Token':token},body:JSON.stringify(payload)});
      item.saved=clone(data);
      item.context.document_id=data.document_id; item.context.lock_version=data.lock_version; item.context.status=data.status;
      if(contents(item.context)===sentContents) item.context.sheet.fields=clone(data.sheet.fields);
      // Do not repaint input cells after asynchronous saves: newer keystrokes and
      // cursor positions must survive. The server snapshot is the restore point.
      announce(dirty(item)?'保存しました。保存中に入力した変更はまだ未保存です。':'下書きを保存しました。');
    } catch(error) { announce(error.message+' この画面の入力は残っています。',true); }
    finally { saving=false; status(); }
  }
  function exportMonthly(kind) {
    commitEdit();
    const snapshot=clone(ctx()), mode=snapshot.editable?'current':'saved';
    const payload={kind,mode,document_id:snapshot.document_id,lock_version:snapshot.lock_version,
      classroom_id:snapshot.classroom_id,target_month:snapshot.target_month,age:snapshot.age};
    if(mode==='current')Object.assign(payload,{owner_name:snapshot.owner_name,
      fields:Object.fromEntries(Object.entries(snapshot.sheet.fields).map(([k,v])=>[k,{body:v.body||''}]))});
    const token=document.querySelector('meta[name="csrf-token"]')?.content || document.querySelector('input[name="csrf_token"]')?.value || '';
    const form=document.createElement('form');
    form.method='POST';form.action='/plans/monthly-library/export-file';form.target='_blank';form.hidden=true;
    for(const [name,value] of Object.entries({csrf_token:token,snapshot:JSON.stringify(payload)})){
      const input=document.createElement('input');input.type='hidden';input.name=name;input.value=value;form.append(input);
    }
    document.body.append(form);form.submit();form.remove();
    announce(kind==='pdf'?'印刷確認を開いています。帳票の保存はしていません。':'Excelのダウンロードを開始しました。帳票の保存はしていません。');
  }
  document.querySelector('[data-monthly-print]')?.addEventListener('click',()=>exportMonthly('pdf'));
  root.addEventListener('click',event=>{
    const button=event.target.closest('button');
    if(!button)return;
    if(button.id==='print-monthly'){exportMonthly('pdf');return;}
    if(button.id==='excel-monthly'){exportMonthly('xlsx');return;}
    if(button.id==='save'){save();return;}
    if(button.id==='generate'){generateAI();return;}
    if(button.id==='history-toggle'){commitEdit();showHistory=!showHistory;loadHistory();return;}
    if(button.dataset.child){selectChild(button.dataset.child);return;}
    if(button.dataset.mode){mode=button.dataset.mode;search();return;}
    if(button.id==='more'){search(true);return;}
    if(button.dataset.candidate!==undefined && editable()){
      commitEdit(); const row=candidateRows[Number(button.dataset.candidate)],key=current.field;
      if(!row || body(key).includes(row.text))return;
      const ta=selectedCell(); if(!ta)return;
      remember(); const old=fields()[key] || {body:'',origins:[]};
      fields()[key]={body:(old.body.trim()?old.body.replace(/\s+$/,'')+'\n':'')+'○'+row.text,
        origins:[...old.origins.filter(o=>originKey(o)!==originKey(row)),clone(row)]};
      ta.value=body(key); autosize(ta); origins(); candidateMarks(); status();
      ta.focus({preventScroll:true});ta.setSelectionRange(ta.value.length,ta.value.length);
      announce('セルに反映しました。セル内で修正・削除できます。');return;
    }
    if(button.id==='undo' && editable()){
      commitEdit();const previous=current.undo.pop();if(!previous)return;
      ctx().sheet.fields=previous.fields;ctx().owner_name=previous.owner;paper();panel(false);candidateMarks();status();return;
    }
    if(button.id==='revert' && editable()){
      commitEdit();remember();ctx().sheet.fields=clone(current.saved.sheet.fields);ctx().owner_name=current.saved.owner_name;
      paper();panel(false);candidateMarks();status();announce('最後に保存した内容に戻しました。「ひとつ戻す」で取り消せます。');
    }
  });
  root.addEventListener('change',event=>{
    const el=event.target;
    if(['classroom','month','age'].includes(el.id))switchScope();
    else if(el.id==='child')selectChild(el.value);
    else if(el.id==='page'){
      const start=pages().slice(0,Number(el.value)).reduce((a,b)=>a+b,0);
      selectChild(ctx().sheet.children[start].ref);
    }
  });
  root.addEventListener('focusin',event=>{
    const el=event.target;
    if(el.dataset.cell){
      const previous=current.field, previousChild=current.child;
      current.field=el.dataset.cell;
      if(current.field.startsWith('child:')){current.child=current.field.split(':').slice(0,2).join(':');q('#child').value=current.child;}
      panel(previous!==current.field);
      if(previousChild!==current.child && showHistory)loadHistory();
      else highlight();
    }
    if(editable() && (el.dataset.cell || el.hasAttribute('data-owner')))before={fields:clone(fields()),owner:ctx().owner_name};
  });
  root.addEventListener('focusout',event=>{if(event.target.dataset.cell || event.target.hasAttribute('data-owner'))commitEdit();});
  root.addEventListener('input',event=>{
    const el=event.target;
    if(el.id==='keyword'){
      keyword=el.value; clearTimeout(searchTimer); searchSequence++; searchController?.abort();
      candidateRows=[];q('#candidates').textContent='検索しています…';q('#more').hidden=true;
      searchTimer=setTimeout(()=>search(),250);return;
    }
    if(!editable())return;
    if(el.dataset.cell){
      const key=el.dataset.cell,old=fields()[key] || {origins:[]};
      // Retain provenance after edits; remove it only when the entire cell is cleared.
      if(el.value)fields()[key]={...old,body:el.value};else delete fields()[key];
      autosize(el);candidateMarks();origins();status();
    }else if(el.hasAttribute('data-owner')){ctx().owner_name=el.value;status();}
  });
  window.addEventListener('beforeunload',event=>{
    if(saving || [...cache.values()].some(dirty)){event.preventDefault();event.returnValue='';}
  });
  // Direct browser printing also uses plain text, all roster pages and no application chrome.
  window.addEventListener('beforeprint',()=>{
    commitEdit();document.querySelector('#monthly-print-root')?.remove();
    const printRoot=document.createElement('div');printRoot.id='monthly-print-root';
    const oldPage=current.page;
    const paperPages=[];
    if(individual()) {
      for(let i=0;i<pages().length;i++) {
        current.page=i;
        paperPages.push(head()+common(['common:goal','common:home','common:review'])+roster());
      }
    } else paperPages.push(group());
    current.page=oldPage;
    printRoot.innerHTML=paperPages.map((html,i)=>`<section class="print-sheet">${html}<p class="print-footer">${i+1} / ${paperPages.length}</p></section>`).join('');
    printRoot.querySelectorAll('textarea').forEach(el=>{
      const text=document.createElement('div');text.className='print-text';text.textContent=body(el.dataset.cell);el.replaceWith(text);
    });
    printRoot.querySelectorAll('input').forEach(el=>{
      const text=document.createElement('div');text.className='print-text';text.textContent=el.value;el.replaceWith(text);
    });
    document.body.append(printRoot);
  });
  window.addEventListener('afterprint',()=>document.querySelector('#monthly-print-root')?.remove());

  render();
  new ResizeObserver(()=>all('textarea.cell').forEach(autosize)).observe(q('.paper'));
})();
