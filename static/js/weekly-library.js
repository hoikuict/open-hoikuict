'use strict';
(() => {
  const root=document.querySelector('#weekly-library');if(!root)return;
  const q=s=>root.querySelector(s),qa=s=>[...root.querySelectorAll(s)],copy=x=>structuredClone(x);
  const esc=x=>String(x??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const date=s=>new Date(`${s}T12:00:00Z`),iso=d=>d.toISOString().slice(0,10),add=(s,n)=>{const d=date(s);d.setUTCDate(d.getUTCDate()+n);return iso(d);};
  const short=s=>`${Number(s.slice(5,7))}/${Number(s.slice(8))}`,days=['月','火','水','木','金','土'];
  const week=s=>{const d=date(add(s,3)),y=d.getUTCFullYear(),jan=date(`${y}-01-04`);jan.setUTCDate(jan.getUTCDate()-((jan.getUTCDay()+6)%7));return `${y}-W${String(1+Math.round((date(s)-jan)/604800000)).padStart(2,'0')}`;};
  const fromWeek=w=>{if(!/^\d{4}-W\d{2}$/.test(w))return null;const [y,n]=w.split('-W'),d=date(`${y}-01-04`);d.setUTCDate(d.getUTCDate()-((d.getUTCDay()+6)%7)+(Number(n)-1)*7);return week(iso(d))===w?iso(d):null;};
  const fields=['related_monthly_summary','previous_week_reflection','current_children_snapshot','weekly_activities_note','seasonal_context','family_context','class_notes'];
  const cache=new Map();let current,selected,busy=false,searchSeq=0,searchTimer,sourceItems=[];
  const scope=c=>`${c.classroom_id}|${c.month}|${c.age}`;
  const record=()=>current.data.records.find(r=>r.week_start===selected);
  const changed=(r,base)=>JSON.stringify([r.sheet,r.owner_name])!==JSON.stringify([base.sheet,base.owner_name]);
  const dirty=()=>[...cache.values()].some(c=>c.data.records.some((r,i)=>r.editable&&changed(r,c.saved.records[i])));
  function notice(text,error=false){const e=q('#weekly-message');e.textContent=text;e.hidden=!text;e.classList.toggle('error',error);e.setAttribute('role',error?'alert':'status');}
  async function api(path,body){
    const token=document.querySelector('meta[name="csrf-token"]')?.content || '';
    const response=await fetch(path,{method:body?'POST':'GET',headers:body?{'Content-Type':'application/json','X-CSRF-Token':decodeURIComponent(token||'')}:undefined,body:body?JSON.stringify(body):undefined,credentials:'same-origin'});
    if(response.redirected&&new URL(response.url).pathname.includes('/login'))throw Error('ログインを確認してください。入力内容は保持しています。');
    let result;try{result=await response.json();}catch{throw Error('通信を確認してください。入力内容は保持しています。');}
    if(!response.ok)throw Error(typeof result.detail==='string'?result.detail:'入力内容を確認してください。保存は完了していません。');return result;
  }
  function confirmChange(text){const dialog=q('#weekly-confirm');q('#weekly-confirm-text').textContent=text;dialog.showModal();q('#weekly-confirm-no').focus();return new Promise(resolve=>{const finish=v=>{dialog.close();dialog.oncancel=null;q('#weekly-confirm-no').onclick=null;q('#weekly-confirm-yes').onclick=null;resolve(v);};q('#weekly-confirm-no').onclick=()=>finish(false);q('#weekly-confirm-yes').onclick=()=>finish(true);dialog.oncancel=e=>{e.preventDefault();finish(false);};});}
  function install(data){const c={data:copy(data),saved:copy(data)};cache.set(scope(data),c);return c;}
  function collect(){if(!current||busy)return;
    qa('#paper-fields textarea').forEach(el=>{const r=current.data.records.find(r=>r.week_start===el.dataset.start);if(!r?.editable)return;if(el.dataset.day!==undefined)r.sheet.days[Number(el.dataset.day)][el.dataset.field]=el.value;else r.sheet[el.dataset.field]=el.value;});
    const r=record();if(r?.editable){r.owner_name=q('[name=owner_name]').value;r.sheet.include_saturday=q('[name=include_saturday]').checked;r.sheet.parent_document_id=Number(q('[name=parent_document_id]').value)||null;fields.forEach(f=>r.sheet.context[f]=q(`[name=${f}]`).value);}
  }
  function status(){const r=record();q('#weekly-status').textContent=current.data.records.some((r,i)=>r.editable&&changed(r,current.saved.records[i]))?'未保存の変更':r.status_label;
    const a=q('#weekly-document-link');a.hidden=!r.document_id;if(r.document_id)a.href=`/plans/documents/${r.document_id}`;
    const parent=q('#parent-link'),id=r.sheet.parent_document_id;parent.hidden=!id;if(id)parent.href=`/plans/monthly-library?document_id=${id}`;
  }
  function paper(){const c=current.data,r=record(),infant=c.age<3;
    q('#weekly-layout').textContent=infant?'0～2歳：月内の週を一覧':'3～5歳：曜日別';q('#paper-scope').textContent=`${c.classroom_name}・${c.age}歳児 ／ ${c.month}`;
    q('#week-range').textContent=`選択している週：${short(selected)}（月）〜${short(add(selected,6))}（日）${r.editable?'':' ／ 閲覧のみ'}`;
    q('#paper-format-note').textContent=infant?'期間とねらいは同じ欄、配慮・援助と準備も一つの欄に記入します。':'週のねらいと反省、曜日ごとの活動・援助配慮・準備を記入します。';
    const area=(row,field,day)=>`<textarea maxlength="20000" rows="5" ${row.editable?'':'disabled'} aria-label="${esc(short(row.week_start)+(day!==undefined?days[day]+'曜日':'週')+' '+({aim:'ねらい',activity:'活動',support:'援助・配慮事項',preparation:'準備',support_preparation:'配慮・援助すること／準備',reflection:'評価・反省'})[field])}" data-start="${row.week_start}" data-field="${field}" ${day!==undefined?`data-day="${day}"`:''}>${esc(day!==undefined?row.sheet.days[day][field]:row.sheet[field])}</textarea>`;
    if(infant)q('#paper-fields').innerHTML=`<div class="paper-scroll" tabindex="0" role="region" aria-label="乳児の週別計画"><table class="paper-table infant-paper"><thead><tr><th class="week-cell">週・期間／ねらい</th><th>活動</th><th class="support-cell">配慮・援助すること／準備</th><th>評価・反省</th></tr></thead><tbody>${c.records.map((row,i)=>`<tr class="${row.week_start===selected?'selected-row':''}"><th scope="row" class="week-cell"><strong>第${i+1}週</strong><br>${short(row.week_start)}〜${short(add(row.week_start,6))}<br><span>${esc(row.status_label)}</span><br>${row.week_start===selected?'選択中':`<button type="button" data-select-week="${row.week_start}">この週を選ぶ</button>`}<label class="week-aim-input">ねらい${area(row,'aim')}</label></th><td>${area(row,'activity')}</td><td>${area(row,'support_preparation')}</td><td>${area(row,'reflection')}</td></tr>`).join('')}</tbody></table></div>`;
    else q('#paper-fields').innerHTML=`<label>今週のねらい${area(r,'aim')}</label><div class="paper-scroll" tabindex="0" role="region" aria-label="幼児の曜日別計画"><table class="paper-table"><thead><tr><th class="date-column">日付・曜日</th><th>子どもの主な活動</th><th>援助・配慮事項</th><th>準備</th></tr></thead><tbody>${r.sheet.days.slice(0,r.sheet.include_saturday?6:5).map((d,i)=>`<tr><th scope="row">${short(add(selected,i))}<br>（${days[i]}）</th>${['activity','support','preparation'].map(f=>`<td>${area(r,f,i)}</td>`).join('')}</tr>`).join('')}</tbody></table></div><label>今週の反省${area(r,'reflection')}</label>`;
  }
  function render(){const c=current.data,r=record();q('#weekly-month').value=c.month;q('[name=target_week]').value=week(selected);q('[name=classroom_ref]').value=String(c.classroom_id);q('[name=age_class]').value=String(c.age);q('[name=owner_name]').value=r.owner_name;q('[name=include_saturday]').checked=r.sheet.include_saturday;
    q('[name=parent_document_id]').innerHTML='<option value="">接続しない</option>'+c.monthly_documents.map(m=>`<option value="${m.id}">${esc(m.title)}</option>`).join('');q('[name=parent_document_id]').value=String(r.sheet.parent_document_id||'');
    fields.forEach(f=>q(`[name=${f}]`).value=r.sheet.context[f]||'');
    ['owner_name','include_saturday','parent_document_id',...fields].forEach(f=>q(`[name=${f}]`).disabled=!r.editable);
    q('#weekly-save').disabled=!c.records.some(x=>x.editable);q('#weekly-revert').disabled=!c.records.some(x=>x.editable);
    qa('.plan-calendar-nav a').forEach(a=>{if(a.id!=='weekly-document-link')a.search=new URLSearchParams({classroom_id:c.classroom_id,month:c.month,age:c.age}).toString();});
    paper();status();renderSources();
  }
  async function load(classroom_id,month,age,start){collect();if(busy)return;
    busy=true;q('#weekly-fields').disabled=true;
    try{const key=scope({classroom_id,month,age});current=cache.get(key)||install(await api('/plans/weekly-library/context?'+new URLSearchParams({classroom_id,month,age})));selected=current.data.records.some(r=>r.week_start===start)?start:current.data.records[0].week_start;notice(dirty()?'保存していない入力は画面内に保持しています。各年齢・月の画面で保存してください。':'');}
    catch(e){notice(e.message,true);}finally{busy=false;q('#weekly-fields').disabled=false;render();q('#search-age').value=String(current.data.age);q('#search-month').value=String(Number(current.data.month.slice(5)));search();}
  }
  function renderSources(){q('#source-list').innerHTML=sourceItems.map(s=>`<details class="source-card"><summary><strong>${esc(s.title)}</strong><small>${s.age}歳児・${s.month}月 ／ 詳細を開く</small></summary><div class="source-detail"><h3>ねらい</h3><p>${esc(s.aim)}</p><table><thead><tr><th>活動</th>${s.age<3?'<th>配慮・援助すること／準備</th>':'<th>援助・配慮事項</th><th>準備</th>'}</tr></thead><tbody>${s.age<3?`<tr><td>${esc(s.activity)}</td><td>${esc(s.support_preparation)}</td></tr>`:s.days.map((d,i)=>`<tr><td>${days[i]}：${esc(d.activity)}</td><td>${esc(d.support)}</td><td>${esc(d.preparation)}</td></tr>`).join('')}</tbody></table><p class="field-note">参照：${esc(s.source_label||'過去の週案')}。評価・反省はコピーしません。</p><button type="button" data-copy="${esc(s.id)}" ${record()?.editable?'':'disabled'}>この候補を選択中の週へコピー</button></div></details>`).join('');}
  async function search(){const seq=++searchSeq,params=new URLSearchParams({classroom_id:current.data.classroom_id,keyword:q('#search-keyword').value});for(const k of ['age','month'])if(q('#search-'+k).value)params.set(k,q('#search-'+k).value);
    q('#source-count').textContent='参考例を読み込んでいます…';
    try{const result=await api('/plans/weekly-library/candidates?'+params);if(seq!==searchSeq)return;sourceItems=result.items;renderSources();q('#source-count').textContent=sourceItems.length?`参考例 ${sourceItems.length}件`:'条件に合う参考例はありません。下の帳票へ手入力できます。';}catch(e){if(seq!==searchSeq)return;sourceItems=[];renderSources();q('#source-count').textContent=e.message;}
  }
  async function save(){collect();if(busy)return;const c=current.data,items=c.records.filter((r,i)=>r.editable&&(changed(r,current.saved.records[i])||(r.week_start===selected&&!r.document_id))).map(r=>({week_start:r.week_start,document_id:r.document_id,lock_version:r.lock_version,sheet:copy(r.sheet),owner_name:r.owner_name}));
    if(!items.length){notice('保存する変更はありません。');return;}if(items.some(r=>!r.owner_name.trim())){notice('入力した週の作成者を入力してください。',true);return;}
    busy=true;q('#weekly-fields').disabled=true;
    try{const result=await api('/plans/weekly-library/save',{classroom_id:c.classroom_id,month:c.month,age:c.age,items});current=install(result);notice(`週案${items.length}件を保存しました。カレンダーにも反映しています。`);}
    catch(e){notice(e.message,true);}finally{busy=false;q('#weekly-fields').disabled=false;render();}
  }
  async function leave(url){if(busy)return;collect();if(dirty()&&!await confirmChange('保存していない変更があります。変更を破棄して移動しますか？'))return;cache.clear();window.location.assign(url);}
  q('#weekly-form').addEventListener('submit',e=>{e.preventDefault();save();});
  q('#weekly-form').addEventListener('input',e=>{if(e.target.matches('textarea,[name=owner_name]')){collect();status();}});
  for(const selector of ['#weekly-month','[name=classroom_ref]','[name=age_class]'])q(selector).addEventListener('change',()=>load(Number(q('[name=classroom_ref]').value),q('#weekly-month').value,Number(q('[name=age_class]').value),selected));
  q('[name=target_week]').addEventListener('change',()=>{const start=fromWeek(q('[name=target_week]').value);if(!start){notice('対象週を正しく選択してください。',true);return;}if(current.data.records.some(r=>r.week_start===start)){collect();selected=start;render();}else load(current.data.classroom_id,add(start,3).slice(0,7),current.data.age,start);});
  q('[name=include_saturday]').addEventListener('change',()=>{collect();paper();status();});q('[name=parent_document_id]').addEventListener('change',()=>{collect();status();});
  q('#paper-fields').addEventListener('click',e=>{const b=e.target.closest('[data-select-week]');if(b){collect();selected=b.dataset.selectWeek;render();}});
  q('#source-list').addEventListener('click',async e=>{const b=e.target.closest('[data-copy]');if(!b||!record().editable)return;const s=sourceItems.find(x=>x.id===b.dataset.copy);if(!s)return;if((s.age<3)!==(current.data.age<3)){notice('帳票の形式が異なります。同じ形式の年齢で検索するか、詳細を参考に入力してください。',true);return;}collect();const r=record(),p=r.sheet;if([p.aim,p.activity,p.support_preparation,...p.days.flatMap(d=>Object.values(d))].some(Boolean)&&!await confirmChange('選択中の週の計画欄を参考例で置き換えます。入力した反省・期間・クラス・作成者・月案接続は保持します。続けますか？'))return;Object.assign(p,{aim:s.aim,activity:s.activity,support_preparation:s.support_preparation,days:copy(s.days),source_ids:[s.id]});paper();status();notice('選択中の週へコピーしました。内容を確認して保存してください。');});
  for(const id of ['#search-age','#search-month'])q(id).addEventListener('change',search);q('#search-keyword').addEventListener('input',()=>{clearTimeout(searchTimer);searchTimer=setTimeout(search,250);});
  q('#weekly-revert').addEventListener('click',async()=>{collect();if(await confirmChange('表示中の月・年齢の未保存の変更を取り消し、保存した内容へ戻しますか？')){current.data=copy(current.saved);render();notice('保存した内容へ戻しました。');}});
  q('#weekly-cancel').addEventListener('click',()=>leave('/plans/weekly-plans/?'+new URLSearchParams({classroom_id:current.data.classroom_id,month:current.data.month,age:current.data.age})));
  root.addEventListener('click',e=>{const a=e.target.closest('a[data-leave]');if(a){e.preventDefault();leave(a.href);}});
  window.addEventListener('beforeunload',e=>{collect();if(busy||dirty()){e.preventDefault();e.returnValue='';}});
  const boot=JSON.parse(document.querySelector('#weekly-boot').textContent);current=install(boot);selected=boot.selected_week;render();q('#search-age').value=String(boot.age);q('#search-month').value=String(Number(boot.month.slice(5)));search();
})();
