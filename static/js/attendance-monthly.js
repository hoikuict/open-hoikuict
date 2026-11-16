(() => {
  'use strict';
  const root = document.getElementById('attendance-monthly');
  if (!root) return;
  const state = JSON.parse(root.dataset.state);
  const $ = (s) => root.querySelector(s);
  const esc = (value) => String(value ?? '').replace(/[&<>"']/g, (c) => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const times = (item) => '登園 ' + (item.arrival || '未打刻') + ' ／ 降園 ' + (item.departure ? (item.next_day ? '翌日 ' : '') + item.departure : '未打刻');
  const auditTimes = (item) => item ? '登園 ' + (item.check_in_at || 'なし') + ' ／ 降園 ' + (item.check_out_at || 'なし') : '';
  const clockMinutes = (value) => Number(value.slice(0, 2)) * 60 + Number(value.slice(3));
  const sameDay = (value) => state.rows.find((row) => row.date === value);
  const storageKey = 'attendance-monthly-position';
  let currentDay = null, bulkReady = false;

  function savePosition() {
    try { sessionStorage.setItem(storageKey, JSON.stringify({query:location.search, y:window.scrollY, x:$('.am-scroll')?.scrollLeft || 0})); } catch (_) {}
  }
  function restorePosition() {
    try {
      const value = JSON.parse(sessionStorage.getItem(storageKey) || 'null');
      sessionStorage.removeItem(storageKey);
      const previous = new URLSearchParams(value?.query || '');
      if (!value || previous.get('month') !== state.month || Number(previous.get('child_id')) !== state.child_id) return;
      requestAnimationFrame(() => {window.scrollTo(0,value.y); if ($('.am-scroll')) $('.am-scroll').scrollLeft=value.x;});
    } catch (_) {}
  }
  document.querySelectorAll('.am [data-close]').forEach((button) => button.addEventListener('click', () => $('#'+button.dataset.close).close()));
  $('#missing-only')?.addEventListener('change', () => {
    root.querySelectorAll('#monthly-rows tr').forEach((row) => {row.hidden=$('#missing-only').checked && row.dataset.missing !== '1';});
  });
  $('#fees-toggle')?.addEventListener('change', () => {root.dataset.hideFees=String(!$('#fees-toggle').checked);});
  $('#class-select').addEventListener('change', () => {
    // Rebuild the child options on the server for the selected class.
    $('#child-select').disabled=true;
    $('#class-select').form.requestSubmit();
  });
  $('#child-select').addEventListener('change', () => $('#child-select').form.requestSubmit());

  function openDay(day, draft) {
    const row=sameDay(day);
    if (!row) return;
    currentDay=row;
    const editable=state.can_edit && row.allowed && !row.locked;
    $('#day-form').action='/attendance/monthly/'+state.child_id+'/day';
    $('#day-title').textContent=row.date+' の登降園記録';
    $('#day-date').value=row.date;
    $('#day-revision').value=draft?.revision || row.revision;
    $('#day-arrival').value=draft?.arrival ?? row.arrival;
    $('#day-departure').value=draft?.departure ?? row.departure;
    $('#day-offset').value=String(draft?.next_day ?? row.next_day);
    $('#day-reason').value=draft ? state.draft.reason : '';
    $('#day-fields').disabled=!editable;$('#day-save').disabled=!editable;
    $('#date-repair').hidden=!row.date_mismatch;
    $('#date-repair input').checked=Boolean(draft?.repair_dates);
    $('#day-before').textContent='保存済み：'+times(row)+(row.date_mismatch?' ／ 記録日：登園 '+(row.arrival_date||'なし')+'・降園 '+(row.departure_date||'なし'):'');
    $('#day-context').textContent='出欠：'+row.visual+' ／ 保護者連絡：'+row.contact+
      (row.locked?' ／ 料金が確定済みのため閲覧のみです。':!row.allowed?' ／ 未来日・在籍期間外のため閲覧のみです。':'');
    $('#day-error').hidden=!draft;
    $('#day-error').textContent=draft ? $('#server-error')?.textContent || '' : '';
    const fields=[['お迎え予定時刻',row.planned||'未入力'],['お迎え予定者',row.person||'未入力'],['補食',row.snack],['実際のお迎えの人',row.actual||'未記録'],['延長分数',row.fee_minutes===null?'未計算':row.fee_minutes+'分'],['延長料金',row.fee===null?'未計算':row.fee+'円'],['料金の状態',row.fee_status]];
    $('#day-details').innerHTML=fields.map(([label,value])=>'<dt>'+esc(label)+'</dt><dd>'+esc(value)+'</dd>').join('');
    $('#day-cancel-link').hidden=!state.can_edit || !row.record_id;
    $('#day-cancel-link').href='/attendance/'+state.child_id+'/correction?'+new URLSearchParams({date:row.date,return_to:'monthly',return_query:state.return_query});
    $('#day-history').innerHTML=row.history.length?row.history.map((item)=>'<article class="am-history"><strong>'+esc(item.label)+'</strong><p>'+esc(auditTimes(item.before))+(item.after?' → '+esc(auditTimes(item.after)):'')+'</p><p>理由：'+esc(item.reason)+'</p><small>'+esc(item.actor)+' ／ '+esc(item.at)+'</small></article>').join(''):'<p class="am-help">補記・修正・取消の履歴はありません。</p>';
    $('#day-editor').showModal();
  }
  root.querySelectorAll('[data-edit-day]').forEach((button)=>button.addEventListener('click',()=>openDay(button.dataset.editDay)));
  root.querySelectorAll('[data-day-reason]').forEach((button)=>button.addEventListener('click',()=>{$('#day-reason').value=button.dataset.dayReason;}));
  $('#day-form').addEventListener('submit',(event)=>{
    if (!currentDay || !state.can_edit || currentDay.locked || !currentDay.allowed) {event.preventDefault();return;}
    savePosition();
    $('#day-save').disabled=true;
  });
  window.addEventListener('pageshow',()=>{$('#day-save').disabled=!currentDay || !state.can_edit || currentDay.locked || !currentDay.allowed;});

  function bulkChanged() {
    bulkReady=false;$('#save-bulk').hidden=true;$('#review-bulk').hidden=false;$('#bulk-confirmation').hidden=true;
  }
  function renderBulk(drafts) {
    const items=new Map((drafts||[]).map((item)=>[item.date,item]));
    const rows=state.rows.filter((row)=>row.bulk_eligible || row.bulk_optional || items.has(row.date));
    $('#bulk-rows').innerHTML=rows.map((row)=>{
      const draft=items.get(row.date), selected=drafts?Boolean(draft):row.bulk_eligible;
      const disabled=!(row.bulk_eligible||row.bulk_optional), readOnlyIn=Boolean(row.arrival), readOnlyOut=Boolean(row.departure);
      return '<tr data-bulk-date="'+row.date+'" data-revision="'+esc(draft?.revision||row.revision)+'" data-optional="'+(row.bulk_optional?'1':'0')+'">'+
        '<td><input type="checkbox" class="bulk-selected" aria-label="'+row.date+'を補完" '+(selected?'checked ':'')+(disabled?'disabled':'')+'></td>'+
        '<td>'+esc(row.date.slice(5))+'（'+row.weekday+'）<small>'+esc(row.visual)+' ／ '+esc(row.contact)+'</small></td>'+
        '<td><input type="time" class="bulk-arrival" aria-label="'+row.date+'の登園時刻" step="60" value="'+esc(draft?.arrival??row.arrival)+'" '+(readOnlyIn||disabled?'readonly':'')+'><small>'+(readOnlyIn?'記録済み・変更しません':'未打刻')+'</small></td>'+
        '<td><input type="time" class="bulk-departure" aria-label="'+row.date+'の降園時刻" step="60" value="'+esc(draft?.departure??row.departure)+'" '+(readOnlyOut||disabled?'readonly':'')+'><small>'+(readOnlyOut?'記録済み・変更しません':'未打刻')+'</small></td>'+
        '<td><select class="bulk-offset" aria-label="'+row.date+'の降園日" '+(readOnlyOut||disabled?'disabled':'')+'><option value="false">対象日</option><option value="true" '+((draft?.next_day??row.next_day)?'selected':'')+'>翌日</option></select></td><td>'+esc(row.planned||'未入力')+'</td></tr>';
    }).join('');
    if (!rows.length) $('#bulk-rows').innerHTML='<tr><td colspan="6">一括補完できる空欄はありません。</td></tr>';
    updateOptional();
  }
  function updateOptional() {
    root.querySelectorAll('#bulk-rows tr[data-bulk-date]').forEach((row)=>{
      row.hidden=row.dataset.optional==='1'&&!$('#include-unknown').checked;
      if(row.hidden) row.querySelector('.bulk-selected').checked=false;
    });
    bulkChanged();
  }
  function openBulk(draft) {
    $('#bulk-error').hidden=!draft;
    $('#bulk-error').textContent=draft?$('#server-error')?.textContent||'':'';
    $('#bulk-reason').value=draft?.reason||'';
    $('#include-unknown').checked=Boolean(draft?.items?.some((item)=>sameDay(item.date)?.bulk_optional));
    renderBulk(draft?.items);
    $('#bulk-editor').showModal();
  }
  function bulkError(message) {$('#bulk-error').textContent=message;$('#bulk-error').hidden=false;}
  function selectedRows() {return [...root.querySelectorAll('#bulk-rows tr[data-bulk-date]')].filter((row)=>!row.hidden&&row.querySelector('.bulk-selected').checked);}
  $('#open-bulk')?.addEventListener('click',()=>openBulk());
  $('#include-unknown')?.addEventListener('change',updateOptional);
  $('#bulk-select-all')?.addEventListener('click',()=>{root.querySelectorAll('#bulk-rows tr[data-bulk-date]').forEach((row)=>{const check=row.querySelector('.bulk-selected');if(!row.hidden&&!check.disabled)check.checked=true;});bulkChanged();});
  $('#bulk-select-none')?.addEventListener('click',()=>{root.querySelectorAll('.bulk-selected').forEach((input)=>{input.checked=false;});bulkChanged();});
  $('#apply-common')?.addEventListener('click',()=>{
    const arrival=$('#common-arrival').value, departure=$('#common-departure').value;
    if (!arrival&&!departure) return bulkError('共通の登園・降園時刻の少なくとも一方を入力してください。');
    const selected=selectedRows();
    if(!selected.length)return bulkError('候補を入れる日を選択してください。');
    selected.forEach((row)=>{
      if(arrival&&!row.querySelector('.bulk-arrival').readOnly)row.querySelector('.bulk-arrival').value=arrival;
      if(departure&&!row.querySelector('.bulk-departure').readOnly)row.querySelector('.bulk-departure').value=departure;
    });
    $('#bulk-error').hidden=true;bulkChanged();
  });
  $('#bulk-rows')?.addEventListener('input',bulkChanged);
  $('#bulk-reason')?.addEventListener('input',bulkChanged);
  $('#review-bulk')?.addEventListener('click',()=>{
    const selected=selectedRows(), reason=$('#bulk-reason').value.trim(), payload=[], diff=[];
    if(!selected.length)return bulkError('補完する日を選択してください。');
    if(!reason)return bulkError('共通の補完理由を入力してください。');
    for(const tr of selected) {
      const old=sameDay(tr.dataset.bulkDate);
      const item={date:old.date,revision:tr.dataset.revision,arrival:tr.querySelector('.bulk-arrival').value,departure:tr.querySelector('.bulk-departure').value,next_day:tr.querySelector('.bulk-offset').value==='true'};
      if(!item.arrival&&!item.departure)return bulkError(old.date+'：少なくとも片方の時刻を入力するか、対象から外してください。');
      if(item.arrival&&item.departure&&clockMinutes(item.departure)+(item.next_day?1440:0)<=clockMinutes(item.arrival))return bulkError(old.date+'：降園は登園より後にしてください。');
      if(item.departure&&item.next_day&&clockMinutes(item.departure)>180)return bulkError(old.date+'：翌日の降園は03:00までです。');
      if(item.arrival===old.arrival&&item.departure===old.departure&&item.next_day===old.next_day)continue;
      payload.push(item);diff.push('<p><strong>'+esc(old.date)+'</strong><br>'+esc(times(old))+' → '+esc(times(item))+'</p>');
    }
    if(!payload.length)return bulkError('補完する空欄がありません。');
    $('#bulk-payload').value=JSON.stringify(payload);
    $('#bulk-count').textContent=state.child_name+' の '+payload.length+'日分を保存します';
    $('#bulk-diff').innerHTML=diff.join('');
    $('#bulk-confirmation').hidden=false;$('#bulk-error').hidden=true;$('#review-bulk').hidden=true;
    $('#save-bulk').hidden=false;$('#save-bulk').disabled=false;$('#save-bulk').textContent=payload.length+'日分をまとめて保存';
    bulkReady=true;$('#save-bulk').focus();
  });
  $('#bulk-form')?.addEventListener('submit',(event)=>{
    if(!bulkReady){event.preventDefault();bulkError('「保存内容を確認」で対象日と時刻を確認してください。');return;}
    savePosition();$('#save-bulk').disabled=true;
  });
  window.addEventListener('pageshow',()=>{if($('#save-bulk'))$('#save-bulk').disabled=false;});
  restorePosition();
  if(state.draft?.mode==='day'&&state.draft.items[0])openDay(state.draft.items[0].date,state.draft.items[0]);
  if(state.draft?.mode==='bulk'&&state.is_admin)openBulk(state.draft);
})();
