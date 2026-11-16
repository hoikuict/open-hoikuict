'use strict';
// This mock has no fetch, API, database, notification or persistent storage.
const $ = (selector) => document.querySelector(selector);
const esc = (value) => String(value ?? '').replace(/[&<>"']/g, (c) => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const CHILDREN = [{id:'a',name:'園児A',classroom:'くるみ'},{id:'b',name:'園児B',classroom:'くるみ'},{id:'c',name:'園児C',classroom:'うめ'}];
const AS_OF = '2026-11-01';
const datasets = new Map();
let view = 'personal', activeRow = null, toastTimer;
const selection = () => ({month:$('#month').value, child:$('#child').value});
const keyOf = (row) => `${row.childId}/${row.date}`;
const dateLabel = (day) => `${Number(day.slice(5,7))}月${Number(day.slice(8))}日`;
const childFor = (id) => CHILDREN.find((child) => child.id === id);
const minutes = (time) => Number(time.slice(0,2))*60+Number(time.slice(3));
const timeText = (row) => `登園 ${row.arrival || '未打刻'} ／ 降園 ${row.departure ? (row.nextDay ? '翌日 ' : '') + row.departure : '未打刻'}`;
const availableChildren = () => CHILDREN.filter((child) => $('#classroom').value === 'all' || child.classroom === $('#classroom').value);

function makeMonth(childId, month, scene) {
  const [year, number] = month.split('-').map(Number);
  const length = new Date(year, number, 0).getDate();
  return Array.from({length}, (_,index) => {
    const day = index+1, date = `${month}-${String(day).padStart(2,'0')}`, weekday = new Date(year,number-1,day).getDay();
    const future = date > AS_OF, off = weekday===0 || (weekday===6 && day!==17), absent = !off && [7,12].includes(day), unknown = scene!=='filled' && !off && day===19;
    const expected = !off && !absent && !future;
    const row = {childId,date,weekday,future,off,visual:future?'未確認':off?'利用予定なし':absent?(day===7?'病欠':'私用休み'):unknown?'未確認':'出席',contact:future?'未提出':off?'利用予定なし':absent?(day===7?'病欠連絡':'私用休みの連絡'):unknown?'連絡なし':'登園の連絡',arrival:expected&&!unknown?'08:30':'',departure:expected&&!unknown?'17:00':'',nextDay:false,planned:expected&&!unknown?'17:00':'',person:expected&&!unknown?'母':'',actual:expected&&!unknown?'母':'',snack:false,snackConfirmed:expected&&!unknown,fee:expected&&!unknown?'0円':'—',feeMinutes:expected&&!unknown?'0分':'—',feeStatus:expected&&!unknown?'未確定':'—',locked:false,history:[]};
    if (scene==='empty' && expected) {row.arrival='';row.departure='';row.actual='';row.fee='—';row.feeMinutes='—';row.feeStatus='未計算';}
    if (scene==='partial' && expected && !unknown) {
      const shift=childId==='b'?1:childId==='c'?2:0;
      if ([2+shift,22+shift].includes(day)) {row.departure='';row.actual='';}
      if (day===14+shift) row.arrival='';
      if (day===9+shift) {row.arrival='';row.departure='';row.actual='';}
      if (!row.arrival || !row.departure) {row.fee='—';row.feeMinutes='—';row.feeStatus='未計算';}
    }
    if (day===23 && row.arrival && row.departure) {row.feeStatus='請求転送済み';row.locked=true;}
    return row;
  });
}
function records(childId, month) {
  const key = `${childId}/${month}`;
  if (!datasets.has(key)) datasets.set(key,makeMonth(childId,month,$('#scene').value));
  return datasets.get(key);
}
function category(row) {
  if (row.future) return 'future';
  if ((!row.arrival || !row.departure) && (row.visual==='出席' || row.arrival || row.departure)) return 'missing';
  if (!row.arrival && !row.departure && row.visual==='未確認' && !row.off) return 'unknown';
  return 'other';
}
function badge(row) {
  const type=category(row);
  if (type==='future') return '<span class="muted">未来の日付</span>';
  if (type==='missing') return `<span class="badge warning">${!row.arrival&&!row.departure?'両方未打刻':!row.arrival?'登園未打刻':'降園未打刻'}</span>`;
  if (type==='unknown') return '<span class="badge neutral">出欠を要確認</span>';
  if (row.history.length) return '<span class="badge success">補記・修正済み</span>';
  return esc(row.departure?'降園済み':row.visual==='出席'?'出席':row.visual);
}
function populateChildren(preferred) {
  const children=availableChildren();
  $('#child').innerHTML=children.map((child)=>`<option value="${child.id}">${child.name}（${child.classroom}）</option>`).join('');
  if (children.some((child)=>child.id===preferred)) $('#child').value=preferred;
}
function render() {
  const {month,child}=selection();
  if (!/^2026-(0[1-9]|1[0-2])$/.test(month)) return;
  const selectedChild=childFor(child), allRows=view==='personal'?records(child,month):availableChildren().flatMap((item)=>records(item.id,month));
  const onlyMissing=view==='missing'||$('#only-missing').checked;
  const visible=allRows.filter((row)=>!onlyMissing||['missing','unknown'].includes(category(row))).sort((a,b)=>a.date.localeCompare(b.date)||a.childId.localeCompare(b.childId));
  document.body.classList.toggle('class-view',view==='missing');
  $('#child-field').hidden=view==='missing'; $('#child-navigation').hidden=view==='missing';
  $('#personal-tab').setAttribute('aria-pressed',String(view==='personal')); $('#missing-tab').setAttribute('aria-pressed',String(view==='missing'));
  $('#only-missing').disabled=view==='missing';
  $('#record-title').textContent=view==='personal'?`${selectedChild.name} の ${Number(month.slice(0,4))}年${Number(month.slice(5))}月`:`${$('#classroom').value==='all'?'全クラス':$('#classroom').value} · ${Number(month.slice(5))}月の打刻漏れ`;
  $('#record-caption').textContent=view==='personal'?`${selectedChild.classroom} ／ 月初から月末まで ${allRows.length}日分を表示できます。`:'出席確認や打刻を手がかりにした候補と、出欠が分からない日を表示します。';
  $('#missing-count').textContent=`${allRows.filter((row)=>category(row)==='missing').length}件`;
  $('#unknown-count').textContent=`${allRows.filter((row)=>category(row)==='unknown').length}件`;
  $('#corrected-count').textContent=`${allRows.filter((row)=>row.history.length).length}件`;
  $('#row-count').textContent=`${visible.length}${view==='personal'?'日':'件'}`;
  const children=availableChildren(), position=children.findIndex((item)=>item.id===child);
  $('#previous-child').disabled=position<=0; $('#next-child').disabled=position>=children.length-1;
  $('#rows').innerHTML=visible.length?visible.map((row)=>{
    const child=childFor(row.childId), type=category(row), missing=type==='missing';
    const timeCell=(value,isDeparture)=>value?`${esc(value)}${isDeparture&&row.nextDay?'<small>翌日</small>':''}`:missing?'<span class="blank">未打刻</span>':'<span class="muted">—</span>';
    return `<tr class="${type} ${row.off?'off':''}" data-record="${keyOf(row)}"><td class="date-cell"><strong class="${row.weekday===0?'sun':row.weekday===6?'sat':''}">${Number(row.date.slice(5,7))}/${Number(row.date.slice(8))}（${'日月火水木金土'[row.weekday]}）</strong></td><td class="class-mode">${child.name}<small>${child.classroom}</small></td><td>${esc(row.visual)}<small>${esc(row.contact)}</small></td><td class="time">${timeCell(row.arrival,false)}</td><td class="time">${timeCell(row.departure,true)}</td><td>${badge(row)}${row.history.length&&missing?'<small>補記・修正履歴あり</small>':''}</td><td class="fee-column">${esc(row.feeMinutes)} · ${esc(row.fee)}<small>${esc(row.feeStatus)}</small></td><td>${row.planned?`${esc(row.planned)} · ${esc(row.person||'未入力')}`:'—'}<small>実際：${esc(row.actual||'未記録')}</small></td><td><button data-edit="${keyOf(row)}" ${row.future?'disabled':''} class="${missing?'edit-missing':''}">${row.locked?'詳細（料金確定済み）':missing?'補記する':type==='unknown'?'確認・補記':'詳細・修正'}</button></td></tr>`;
  }).join(''):'<tr><td colspan="9">打刻漏れ・要確認の記録はありません。</td></tr>';
}
function showError(message) {$('#form-error').textContent=message;$('#form-error').hidden=false;$('#form-error').focus();}
function toast(message) {clearTimeout(toastTimer);$('#toast').textContent=message;$('#toast').hidden=false;toastTimer=setTimeout(()=>{$('#toast').hidden=true;},5000);}
function details(row) {
  return [['お迎え予定時刻',row.planned||'未入力'],['お迎え予定者',row.person||'未入力'],['補食',row.snackConfirmed?(row.snack?'必要':'不要'):'未確認'],['実際のお迎えの人',row.actual||'未記録'],['延長分数',row.feeMinutes],['延長料金',row.fee],['延長料金の状態',row.feeStatus]].map(([label,value])=>`<dt>${label}</dt><dd>${esc(value)}</dd>`).join('');
}
function openEditor(key) {
  const [childId,date]=key.split('/'); activeRow=records(childId,date.slice(0,7)).find((row)=>row.date===date);
  const row=activeRow, child=childFor(row.childId);
  $('#editor-child').textContent=`${child.name} ／ ${child.classroom}`;
  $('#editor-title').textContent=`${row.date.slice(0,4)}年${dateLabel(row.date)}の登降園記録`;
  $('#editor-context').innerHTML=`<strong>出欠確認：${esc(row.visual)}</strong><br>保護者連絡：${esc(row.contact)}${row.visual!=='出席'&&!row.arrival&&!row.departure?'<p>実際に登園していたか確認してから補記してください。</p>':''}`;
  $('#arrival').value=row.arrival;$('#departure').value=row.departure;$('#departure-day').value=row.nextDay?'1':'0';$('#reason').value='';$('#cancel-reason').value='';
  $('#before-times').textContent=`保存前：${timeText(row)}`;
  $('#existing-details').innerHTML=details(row);$('#form-error').hidden=true;
  $('#locked-notice').hidden=!row.locked;
  $('#locked-notice').textContent='請求転送済みの料金があります。このモックでは打刻の補記・修正・取消を止めています。確定後の扱いは仕様確認が必要です。';
  $('#time-fields').disabled=row.locked;$('#reason-fields').disabled=row.locked;$('#save').disabled=row.locked;
  $('#fee-notice').textContent='時刻を保存した後、延長料金の再確認が必要です。モックでは「再計算待ち」と表示します。';
  $('#cancellation').hidden=row.locked||!(row.arrival||row.departure);$('#cancellation').open=false;
  $('#cancel-operation').options[0].disabled=!row.departure;$('#cancel-operation').value=row.departure?'check_out':'all';
  $('#history').innerHTML=row.history.length?row.history.slice().reverse().map((item)=>`<article><strong>${esc(item.action)}</strong><p>${esc(item.before)} → ${esc(item.after)}</p><p>理由：${esc(item.reason)}</p>${item.effect?`<p>${esc(item.effect)}</p>`:''}<small>見本 はなこ ／ ${esc(item.at)}</small></article>`).join(''):'<p class="muted">補記・修正・取消の履歴はありません。</p>';
  if (!$('#editor').open) $('#editor').showModal();
}
function simulatedError() {
  if (!$('#fail-next').checked) return false;
  $('#fail-next').checked=false;showError('保存できませんでした（試用設定の保存エラー）。入力は残っています。内容を確認して再度保存してください。');return true;
}
function appendHistory(row, action, before, reason, effect='') {
  row.history.push({action,before,after:timeText(row),reason,effect,at:new Intl.DateTimeFormat('ja-JP',{dateStyle:'short',timeStyle:'medium',timeZone:'Asia/Tokyo'}).format(new Date())});
}
$('#edit-form').addEventListener('submit',(event)=>{
  event.preventDefault();const row=activeRow;if(!row||row.locked)return;
  const arrival=$('#arrival').value, departure=$('#departure').value, nextDay=departure&&$('#departure-day').value==='1', reason=$('#reason').value.trim();
  if(!arrival&&!departure) return showError('登園・降園の少なくとも一方を入力してください。打刻を消す場合は「誤った打刻を取り消す」を使ってください。');
  if((row.arrival&&!arrival)||(row.departure&&!departure)) return showError('登録済みの打刻を空欄にはできません。「誤った打刻を取り消す」を使ってください。');
  if(nextDay&&minutes(departure)>180) return showError('翌日の降園は03:00までの時刻を入力してください。');
  if(arrival&&departure&&minutes(departure)+(nextDay?1440:0)<=minutes(arrival)) return showError('降園時刻は登園時刻より後にしてください。翌日の場合は降園の日付を切り替えてください。');
  if(arrival===row.arrival&&departure===row.departure&&Boolean(nextDay)===row.nextDay) return showError('時刻が変更されていません。変更せず閉じることもできます。');
  if(!reason||reason.length>500) return showError('補記・修正理由を500文字以内で入力してください。');
  if(simulatedError())return;
  const before=timeText(row), action=(!row.arrival&&arrival)||(!row.departure&&departure)?'打刻を補記':'打刻時刻を修正';
  row.arrival=arrival;row.departure=departure;row.nextDay=Boolean(nextDay);row.fee='—';row.feeMinutes='—';row.feeStatus='再計算待ち';
  appendHistory(row,action,before,reason);$('#editor').close();render();toast(`${childFor(row.childId).name}・${dateLabel(row.date)}の記録を保存しました（モック）。`);
});
$('#cancel-punch').addEventListener('click',()=>{
  const row=activeRow, reason=$('#cancel-reason').value.trim(), all=$('#cancel-operation').value==='all';
  if(!row||row.locked)return;
  if(!reason||reason.length>500)return showError('取消理由を500文字以内で入力してください。');
  if(!all&&!row.departure)return showError('取り消せる降園打刻がありません。');
  if(simulatedError())return;
  const before=timeText(row);row.departure='';row.nextDay=false;row.actual='';
  if(all){row.arrival='';row.planned='';row.person='';row.snack=false;row.snackConfirmed=false;}
  row.fee='—';row.feeMinutes='—';row.feeStatus='未計算';
  appendHistory(row,all?'登園・降園とお迎え予定を取消':'降園打刻を取消',before,reason,all?'お迎え予定・補食確認・実際のお迎えの記録も取消。':'実際のお迎えの記録も取消。');
  $('#editor').close();render();toast(`${dateLabel(row.date)}の打刻を取り消しました（モック）。`);
});
$('#rows').addEventListener('click',(event)=>{const button=event.target.closest('[data-edit]');if(button)openEditor(button.dataset.edit);});
document.querySelectorAll('[data-reason]').forEach((button)=>button.addEventListener('click',()=>{$('#reason').value=button.dataset.reason;$('#reason').focus();}));
$('#close-editor').addEventListener('click',()=>$('#editor').close());$('#discard').addEventListener('click',()=>$('#editor').close());
$('#personal-tab').addEventListener('click',()=>{view='personal';render();});$('#missing-tab').addEventListener('click',()=>{view='missing';render();});
$('#classroom').addEventListener('change',()=>{populateChildren($('#child').value);render();});$('#child').addEventListener('change',render);
$('#month').addEventListener('change',()=>{if(!/^2026-(0[1-9]|1[0-2])$/.test($('#month').value)){$('#month').value='2026-10';toast('モックの対象月は2026年1月〜12月です。');}render();});
$('#only-missing').addEventListener('change',render);$('#show-fees').addEventListener('change',()=>document.body.classList.toggle('hide-fees',!$('#show-fees').checked));
function moveChild(delta){const children=availableChildren(),index=children.findIndex((child)=>child.id===$('#child').value);$('#child').value=children[index+delta].id;render();}
$('#previous-child').addEventListener('click',()=>moveChild(-1));$('#next-child').addEventListener('click',()=>moveChild(1));
function reset(){datasets.clear();$('#fail-next').checked=false;render();toast('架空データを初期状態に戻しました。');}
$('#scene').addEventListener('change',reset);$('#reset').addEventListener('click',reset);
$('#spec').addEventListener('click',()=>$('#spec-dialog').showModal());$('#close-spec').addEventListener('click',()=>$('#spec-dialog').close());
populateChildren('a');render();
