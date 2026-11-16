/* Disconnected proposal: all state lives in this page; no fetch or business requests. */
'use strict';
const {views, columns} = window.BILLING_PREVIEW;
const view = document.querySelector('#view');
const dialog = document.querySelector('#reopen-dialog');
const notice = document.querySelector('#notice');
let page = 'index', dirty = false, saved, extras, history, account = {}, state;
const labels = {created:'作成済み', submitted:'銀行提出済み', result_imported:'結果取込済み', canceled:'取消済み', superseded:'差し替え済み'};
const yen = value => `${Number(value).toLocaleString('ja-JP')}円`;
const sum = () => Object.values(saved).reduce((a,b)=>a+b,0) + extras.reduce((a,b)=>a+b.amount,0);
const active = () => history.find(row => ['created','submitted','result_imported'].includes(row.status));
const isEditable = () => state === 'reopened';
function notify(message) { notice.textContent=message; notice.hidden=false; }
function button(label, cls, action) { const b=document.createElement('button'); b.type='button'; b.textContent=label; b.className=cls; b.addEventListener('click',action); return b; }
function reset(scenario='created') {
  account={}; dirty=false; extras=[]; saved=Object.fromEntries(columns.map(c=>[c.code, c.code==='temp_photo'?300:0]));
  history=[{id:2,status:'created',amount:300,reason:''},{id:1,status:'superseded',amount:300,reason:''}];
  state=['submitted','result_imported'].includes(scenario)?scenario:'created'; history[0].status=state;
  if(['empty','partial','filled','error'].includes(scenario)) {
    state='reopened'; history[0].status='canceled'; history[0].reason='モックの修正状態を表示';
    if(scenario==='empty') saved.temp_photo=0;
    if(scenario==='filled') Object.assign(saved,{monthly_meal:4500,temp_material:500,temp_event:200,adjustment:-100});
  }
  notice.hidden=true; page=isEditable()?'table':'index'; render();
  if(scenario==='error') {
    view.querySelector('[name="amount_temp_photo_9001"]').value='300.5'; dirty=true;
    notify('金額を整数に直して「保存」を試してください。入力した値はエラー時も保持します。');
  }
}
function changePage(next) {
  if(dirty && !confirm('まだ保存していない入力があります。入力を破棄して移動しますか？')) return;
  dirty=false; page=next; notice.hidden=true; render(); window.scrollTo(0,0);
}
function openReopen() {
  const item=active();
  if(!item || item.status!=='created') { notify('銀行未提出の「作成済み」だけが、この修正操作の対象です。'); return; }
  document.querySelector('#export-summary').textContent=`2026-10 ／ 出力 #${item.id} ／ 1件 ／ ${yen(item.amount)}`;
  document.querySelector('#reason').value=''; document.querySelector('#unsubmitted').checked=false;
  document.querySelector('#dialog-error').hidden=true; dialog.showModal();
}
function render() {
  view.dataset.page=page;
  view.innerHTML=views[page==='index'?'index':`${page}-${Number(isEditable())}`];
  if(page==='index') renderIndex(); else renderInput();
}
function renderIndex() {
  const monthly = [...view.querySelectorAll('tbody')][0];
  const target=[...monthly.rows].find(r=>r.cells[0].textContent.trim()==='2026-10');
  target.cells[1].firstElementChild.textContent=isEditable()?'確定済み（修正可能）':state==='result_imported'?'結果取込済み':'出力済み';
  target.cells[4].textContent=yen(sum());
  const actions=target.cells[5].firstElementChild;
  if(isEditable()) actions.append(button('Zengin作成','primary-button',createExport));
  else if(active()?.status==='created') actions.append(button('取消して修正','reopen-button',openReopen));
  const body=[...view.querySelectorAll('tbody')][1]; const prototype=body.rows[0].cloneNode(true); body.replaceChildren();
  history.forEach(item=>{
    const row=prototype.cloneNode(true);
    row.cells[0].textContent=`#${item.id}`; row.cells[1].firstElementChild.textContent=labels[item.status];
    row.cells[3].textContent=yen(item.amount); row.cells[4].textContent=`mock-${item.id}-${item.amount}`;
    const actions=row.cells[5].firstElementChild; actions.replaceChildren();
    if(item.status!=='canceled') actions.append(button('ダウンロード','plain-button',()=>notify('モックでは銀行に提出できるファイルを作成しません。実装後は、この出力に記録された内容をダウンロードします。')));
    if(item.status==='created') {
      actions.append(button('銀行提出済みにする','plain-button',()=>{
        if(confirm('モックの状態を「銀行提出済み」にしますか？')) { item.status='submitted'; state='submitted'; render(); }
      }),button('取消して修正','reopen-button',openReopen));
    }
    if(item.status==='submitted') {
      const form=document.createElement('form'); form.method='dialog'; form.className='flex gap-1';
      const reason=document.createElement('input'); reason.placeholder='差し替え理由'; reason.name='reason'; reason.className='w-32 rounded border border-slate-300 px-2 py-1 text-xs';
      form.append(reason,button('差し替え','plain-button',()=>notify('銀行提出後の既存の差し替え操作は、今回の修正モックの対象外です。請求の編集ロックは解除しません。')));
      actions.append(form,button('全件振替済みで取込','plain-button',()=>{
        if(confirm('モックの状態を「結果取込済み」にしますか？')) { item.status='result_imported';state='result_imported';render(); }
      }));
    }
    if(item.status==='canceled') {
      const p=document.createElement('p');p.className='history-note';p.textContent=`取消理由：${item.reason} ／ 再ダウンロード・銀行提出・結果取込は不可`;
      actions.append(p);
    }
    body.append(row);
  });
  if(isEditable()) banner('旧出力は取消済みです。園児別入力で修正・保存した後に、Zenginを再作成してください。');
  else if(state!=='created') banner('この請求は銀行提出済みまたは結果取込済みです。今回の「取消して修正」の対象外です。');
}
function banner(message, reopen=false) {
  const box=document.createElement('div'); box.className='proposal-banner';box.textContent=message;
  if(reopen) box.append(button('取消して修正','reopen-button',openReopen));view.prepend(box);
}
function renderInput() {
  if(isEditable()) banner('同じ請求月の金額を修正できます。「保存」で変更を確定し、請求一覧からZenginを再作成してください。');
  else banner(active()?.status==='created'?'Zengin作成済みのため金額は編集できません。銀行提出前であれば、出力を取消して修正へ戻れます。':'銀行提出済みまたは結果取込済みのため、金額は編集できません。',active()?.status==='created');
  if(page==='table') {
    columns.forEach(c=>{const field=view.querySelector(`[name="amount_${c.code}_9001"]`);field.value=saved[c.code]||'';});
    const row=view.querySelector('#billing-child-9001');row.cells[2].textContent=yen(sum());row.cells[9].textContent=yen(sum());
    [...view.querySelectorAll('span')].filter(s=>s.textContent==='出力済み').forEach(s=>s.textContent=isEditable()?'確定済み':state==='result_imported'?'結果取込済み':'出力済み');
    populateLines(view.querySelectorAll('tbody')[1], false);
  } else {
    const summary=[...view.querySelectorAll('dt')].find(n=>n.textContent==='家族請求合計');summary.nextElementSibling.textContent=yen(sum());
    [...view.querySelectorAll('dt')].filter(n=>n.textContent==='請求状態').forEach(n=>n.nextElementSibling.textContent=isEditable()?'確定済み':'出力済み');
    populateLines(view.querySelector('tbody'),true);
    const form=view.querySelector('form[data-action$="/profile"]');
    Object.entries(account).forEach(([key,value])=>{if(form.elements[key])form.elements[key].value=value;});
  }
}
function populateLines(body, detail) {
  body.replaceChildren();
  const lines=columns.filter(c=>saved[c.code]).map(c=>({description:c.label,amount:saved[c.code],quantity:1,unit:'回'})).concat(extras);
  lines.forEach(line=>{
    const row=document.createElement('tr');
    const values=detail?[line.description,'2026-10-15',`${line.quantity}${line.unit}`,yen(line.amount),isEditable()?'確定済み':'出力済み']:
      ['見本 はる',line.description,'2026-10-15',yen(line.amount),isEditable()?'確定済み':'出力済み'];
    values.forEach(value=>{const cell=document.createElement('td');cell.className='px-5 py-3';cell.textContent=value;row.append(cell);});body.append(row);
  });
  if(!lines.length) { const row=body.insertRow();const cell=row.insertCell();cell.colSpan=5;cell.className='px-5 py-10 text-center text-slate-400';cell.textContent='入力済みの明細はありません。'; }
}
function createExport() {
  if(!isEditable()) return;
  if(sum()<=0) { notify('Zengin出力対象の請求がありません。園児別入力で金額を確認してください。');return; }
  history.unshift({id:Math.max(...history.map(x=>x.id))+1,status:'created',amount:sum(),reason:''});state='created';dirty=false;page='index';render();
  notify(`Zenginを再作成しました（モック）。出力 #${active().id} ／ ${yen(active().amount)}。提出には新しい出力を使用します。`);
}
document.querySelector('#reopen-form').addEventListener('submit',event=>{
  event.preventDefault();const reason=document.querySelector('#reason').value.trim(), checked=document.querySelector('#unsubmitted').checked;
  const error=document.querySelector('#dialog-error');
  if(!reason || !checked) {error.textContent=!reason?'取消理由を入力してください。':'銀行へ提出・アップロードしていないことを確認してください。';error.hidden=false;return;}
  const item=active();if(!item || item.status!=='created') {error.textContent='出力の状態が変わったため、修正へ戻せません。';error.hidden=false;return;}
  item.status='canceled';item.reason=reason;state='reopened';dirty=false;page='table';dialog.close();render();
  notify(`出力 #${item.id} を取消しました（モック）。請求金額は保持されています。`);window.scrollTo(0,0);
});
document.querySelector('#close-dialog').addEventListener('click',()=>dialog.close());
document.querySelector('#reset').addEventListener('click',()=>{document.querySelector('#scenario').value='created';reset();});
document.querySelector('#scenario').addEventListener('change',event=>reset(event.target.value));
document.querySelector('#nav-index').addEventListener('click',()=>changePage('index'));
view.addEventListener('input',event=>{if(event.target.closest('form'))dirty=true;});
view.addEventListener('click',event=>{
  const a=event.target.closest('a');if(!a)return;event.preventDefault();const href=a.dataset.href||'';
  if(href==='/billing/') changePage('index');
  else if(href==='/billing/cycles/9001/child-charges') changePage('table');
  else if(href.startsWith('/billing/cycles/9001/child-charges/9001')) {changePage('detail');if(href.includes('#'))view.querySelector('#account-profile').scrollIntoView();}
  else notify('この確認用モックは2026-10の請求修正が対象です。他の月・口座一覧への移動は実行しません。');
});
view.addEventListener('submit',event=>{
  event.preventDefault();const form=event.target, action=form.dataset.action||'';
  if(action.endsWith('/table')) {
    const next={};
    for(const c of columns) {const raw=form.elements[`amount_${c.code}_9001`].value;const value=Number(raw);
      if(!Number.isSafeInteger(value)) {notify(`${c.label}は整数で入力してください。入力内容はそのまま残っています。`);form.elements[`amount_${c.code}_9001`].focus();return;} next[c.code]=value;}
    saved=next;dirty=false;render();notify('請求金額を保存しました（モック）。請求一覧へ戻り「Zengin作成」で新しい出力を作成してください。');
  } else if(action.endsWith('/profile')) {
    account=Object.fromEntries(new FormData(form));dirty=false;notify('架空の口座情報を画面内に保存しました。再読込みで初期状態へ戻ります。');
  } else if(action==='/billing/cycles/9001/child-charges/9001') {
    const data=new FormData(form), amount=Number(data.get('amount')), quantity=Number(data.get('quantity'));
    if(!String(data.get('description')||'').trim() || !Number.isSafeInteger(amount) || !Number.isSafeInteger(quantity) || quantity<1) {notify('内容・整数の金額・1以上の数量を入力してください。');return;}
    extras.push({description:String(data.get('description')),amount:amount*quantity,quantity,unit:String(data.get('unit_label')||'')});dirty=false;render();notify('架空の明細を追加しました（モック）。');
  } else notify('この操作は既存画面の項目として表示しています。今回のモックでは2026-10の取消・修正・再作成を試せます。');
});
window.addEventListener('beforeunload',event=>{if(dirty){event.preventDefault();event.returnValue='';}});
reset();
