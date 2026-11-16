(() => {
  const $ = id => document.getElementById(id);
  const clone = value => JSON.parse(JSON.stringify(value));
  const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const fields = [
    ['temperature','体温','検温の数値',['temperature']],
    ['sleep','睡眠','就寝・起床・睡眠メモ',['bedtime','wakeup_time','sleep_notes']],
    ['dinner','前日の夕食','食欲・食べたもの',['dinner_appetite','dinner_contents']],
    ['breakfast','当日の朝食','食欲・食べたもの',['breakfast_appetite','breakfast_contents']],
    ['stool','排便','性状・回数・排便メモ',['stool_consistency','stool_count','bowel_movement_status']],
    ['mood','機嫌','選択・自由記入',['mood']],
    ['cough','咳','自由記入',['cough']],
    ['runny_nose','鼻水','自由記入',['runny_nose']],
    ['medication','服薬','自由記入',['medication']],
    ['condition','体調メモ','自由記入',['condition_note']]
  ];
  const classes = {chick:{name:'ひよこ組',ages:[0,1]},squirrel:{name:'りす組',ages:[2]},
    cherry:{name:'さくら組',ages:[3,4,5]},star:{name:'ほし組（混合）',ages:[2,3,4,5]}};
  const facilityNames = {a:'見本こども園 A',b:'見本保育園 B'};
  function defaultRules(facility) {
    const rules = {mode:'age',ages:{},classes:{}};
    for(let age=0;age<6;age++) rules.ages[age]=Object.fromEntries(fields.map((f,i)=>[f[0],facility==='a' && age>=3 && i<6?'hide':'show']));
    for(const c of Object.keys(classes)) rules.classes[c]=Object.fromEntries(fields.map((f,i)=>[f[0],facility==='a' && c==='cherry' && i<6?'hide':'show']));
    return rules;
  }
  let state = {version:2,facility:'a',classroom:'chick',age:1,day:'2026-11-16',
    rules:{a:defaultRules('a'),b:defaultRules('b')},draftRules:null,records:{},drafts:{}};
  state.draftRules=clone(state.rules);
  let migrated=false;
  try {
    const cached=JSON.parse(sessionStorage.getItem('contact-fields-preview-r2'));
    if(cached?.version===2)state=cached;
    else {
      const previous=JSON.parse(sessionStorage.getItem('contact-fields-preview-r1'));
      if(previous?.version===1){
        // Preserve fictional submissions and drafts; keep the old policy under its original key.
        for(const name of ['facility','classroom','age','day','records','drafts'])state[name]=clone(previous[name]);
        migrated=true;
      }
    }
  } catch {}
  let view='settings', preview=false;
  const key = () => [state.facility,state.classroom,state.age,state.day].join('/');
  const childName = () => `見本 ${['あおい','ひなた','こはる','そら','ゆう','はる'][state.age]}`;
  const childLabel = () => `${childName()} ／ ${classes[state.classroom].name}・${state.age}歳児`;
  const persist = () => {try{sessionStorage.setItem('contact-fields-preview-r2',JSON.stringify(state));}catch{}};
  function resolve(rules,field,age=state.age,classroom=state.classroom) {
    return {show:(rules.mode==='age'?rules.ages[age][field]:rules.classes[classroom][field])==='show'};
  }
  const maskFor = rules => Object.fromEntries(fields.map(f=>[f[0],resolve(rules,f[0]).show]));
  function notify(message){$('notice').textContent=message;$('notice').hidden=false;}
  function controls(){
    $('facility').value=state.facility;
    $('classroom').innerHTML=Object.entries(classes).map(([id,c])=>`<option value="${id}">${c.name}</option>`).join('');
    $('classroom').value=state.classroom;
    $('age').innerHTML=classes[state.classroom].ages.map(a=>`<option value="${a}">${a}歳児</option>`).join('');
    $('age').value=state.age;$('day').value=state.day;
  }
  const selection = (field,scope,id,value) => `<select aria-label="${scope==='age'?id+'歳児':classes[id].name}の${fields.find(f=>f[0]===field)[1]}" data-rule="${field}" data-level="${scope}" data-target="${id}" data-choice="${value}">${[['show','表示する'],['hide','表示しない']].map(([v,l])=>`<option value="${v}" ${value===v?'selected':''}>${l}</option>`).join('')}</select>`;
  function renderSettings(){
    const rules=state.draftRules[state.facility], scope=rules.mode;
    $('facility-heading').textContent=facilityNames[state.facility];
    $('dirty-state').textContent=JSON.stringify(rules)===JSON.stringify(state.rules[state.facility])?'仮保存した設定と同じ':'未保存の変更あり';
    document.querySelectorAll('[name=settings-mode]').forEach(input=>input.checked=input.value===scope);
    $('saved-mode').textContent='仮保存中の方式：'+(state.rules[state.facility].mode==='age'?'年齢ごと':'クラスごと');
    let head,body;
    if(scope==='age'){
      $('settings-description').innerHTML='<p>各年齢で、保護者に表示する項目を選びます。同じ年齢なら、所属クラスが違っても同じ項目になります。</p>';
      head='<th scope="col">連絡項目</th>'+[0,1,2,3,4,5].map(a=>`<th scope="col">${a}歳児</th>`).join('');
      body=fields.map(([id,label,description])=>`<tr><th scope="row">${label}<span class="field-description">${description}</span></th>${[0,1,2,3,4,5].map(a=>`<td>${selection(id,scope,a,rules.ages[a][id])}</td>`).join('')}</tr>`).join('');
    }else{
      $('settings-description').innerHTML='<p>各クラスで、保護者に表示する項目を選びます。混合クラスも、クラス内の全員に同じ項目を表示します。</p>';
      head='<th scope="col">連絡項目</th>'+Object.values(classes).map(c=>`<th scope="col">${c.name}<span class="field-description">${c.ages.join('・')}歳児</span></th>`).join('');
      body=fields.map(([id,label,description])=>`<tr><th scope="row">${label}<span class="field-description">${description}</span></th>${Object.keys(classes).map(c=>`<td>${selection(id,scope,c,rules.classes[c][id])}</td>`).join('')}</tr>`).join('');
    }
    $('settings-editor').innerHTML=`<div class="table-wrap"><table class="rules-table"><thead><tr>${head}</tr></thead><tbody>${body}</tbody></table></div>`;
    $('summary-title').textContent=`保存前の表示（${scope==='age'?'年齢ごと':'クラスごと'}）：${classes[state.classroom].name}・${state.age}歳児`;
    $('summary').innerHTML='<div class="pills">'+fields.map(([id,label])=>{const r=resolve(rules,id);return `<span class="pill ${r.show?'':'off'}">${label}・${r.show?'表示':'非表示'}</span>`;}).join('')+'</div>';
    $('settings-editor').querySelectorAll('[data-rule]').forEach(select=>select.addEventListener('change',()=>{
      const {level,target,rule}=select.dataset;
      rules[level==='age'?'ages':'classes'][target][rule]=select.value;
      persist();const focusLabel=select.getAttribute('aria-label');renderSettings();
      [...$('settings-editor').querySelectorAll('select')].find(s=>s.getAttribute('aria-label')===focusLabel)?.focus();
    }));
  }
  function collect(){
    const form=$('contact-form');if(!form)return {};
    const values={};
    form.querySelectorAll('input[name],textarea[name],select[name]').forEach(el=>{
      if(el.closest('[data-order-editor]') || ['emergency_label','emergency_phone'].includes(el.name))return;
      if(el.type==='radio'){if(el.checked)values[el.name]=el.value;}
      else if(!(el.name in values) || !el.disabled)values[el.name]=el.value;
    });
    values.emergency_rows=[...form.querySelectorAll('[data-order-editor] ol>li')].map(row=>({label:row.querySelector('[name=emergency_label]').value,phone:row.querySelector('[name=emergency_phone]').value}));
    return values;
  }
  function capture(){if(view==='parent'&&$('contact-form')){state.drafts[key()]=collect();persist();}}
  function populate(values){
    const form=$('contact-form');
    form.querySelectorAll('input[name],textarea[name],select[name]').forEach(el=>{
      if(!(el.name in values))return;
      if(el.type==='radio')el.checked=values[el.name]===el.value;else el.value=values[el.name]??'';
    });
    if(values.emergency_rows){const editor=form.querySelector('[data-order-editor]'),ol=editor.querySelector('ol');ol.replaceChildren();values.emergency_rows.forEach(row=>{
      const li=editor.querySelector('template').content.firstElementChild.cloneNode(true);
      li.querySelector('[name=emergency_label]').value=row.label;li.querySelector('[name=emergency_phone]').value=row.phone;ol.append(li);
    });}
  }
  function currentMask(){const record=state.records[key()];return record?record.mask:maskFor(preview?state.draftRules[state.facility]:state.rules[state.facility]);}
  function syncVisibility(){
    const form=$('contact-form'), present=form.querySelector('[name=attendance_mode]:checked')?.value==='present',mask=currentMask();
    form.querySelectorAll('[data-contact-group]').forEach(group=>{
      group.hidden=!mask[group.dataset.contactGroup];
      group.querySelectorAll('input,select,textarea,button').forEach(input=>input.disabled=!present||group.hidden);
    });
    const meals=form.querySelector('[data-contact-group=dinner]').parentElement;
    meals.hidden=!mask.dinner&&!mask.breakfast;
    // The production validator's inline message is irrelevant while its field is disabled.
    if(!mask.temperature){$('temperature-error').classList.add('hidden');$('temperature').setAttribute('aria-invalid','false');}
    const mode=form.querySelector('[name=emergency_mode]:checked')?.value;
    const editor=form.querySelector('[data-order-editor]');
    editor.hidden=mode!=='change';editor.querySelectorAll('input').forEach(e=>e.disabled=editor.hidden);
    form.querySelectorAll('[data-clear-appetite]').forEach(b=>b.hidden=!b.closest('fieldset').querySelector(':checked'));
  }
  function renderParent(){
    $('parent-facility').textContent=facilityNames[state.facility];
    $('parent-form').replaceChildren($('deployed-form').content.cloneNode(true));
    $('contact-title').textContent=childName()+' の日次連絡';
    $('contact-subtitle').textContent=state.day+' ／ '+classes[state.classroom].name+'・'+state.age+'歳児';
    const [year,month,day]=state.day.split('-').map(Number), d=new Date(year,month-1,day), yesterday=new Date(year,month-1,day-1);
    $('emergency-heading').textContent=`${month}月${day}日の緊急連絡先`;
    $('dinner-heading').textContent=`${yesterday.getMonth()+1}月${yesterday.getDate()}日の夕食`;
    $('breakfast-heading').textContent=`${d.getMonth()+1}月${d.getDate()}日の朝食`;
    const record=state.records[key()];
    populate(state.drafts[key()]||record?.values||{});
    $('contact-form').querySelector('[name=date]').value=state.day;
    bindDeployedInputs();
    syncVisibility();
    const banner=$('policy-banner');banner.classList.toggle('preview',preview);
    banner.textContent=preview?'保存前の設定で確認中。設定を仮保存してから、日次連絡を保存できます。':record?'仮保存済みの連絡です。保存時の項目を保持して表示しています。内容を直して保存できます。':'園が選んだ連絡項目を表示しています。';
    if(preview&&record)banner.textContent+=' この園児・日は既に保存済みのため、保存時の項目を表示しています。新しい日付で確認してください。';
    const errorBox=document.createElement('div');errorBox.id='contact-errors';errorBox.role='alert';errorBox.hidden=true;
    const submit=$('contact-form').querySelector('[type=submit]');submit.closest('div').before(errorBox);
    if(preview){submit.disabled=true;submit.title='園の設定を仮保存してから試せます';}
    $('contact-form').addEventListener('change',()=>{syncVisibility();state.drafts[key()]=collect();persist();});
    $('contact-form').addEventListener('input',()=>{state.drafts[key()]=collect();persist();});
    $('contact-form').addEventListener('submit',event=>{
      const blocked=event.defaultPrevented;event.preventDefault();if(preview)return;
      if(blocked){notify('入力内容を確認してください。仮保存した連絡は変更していません。');return;}
      const values=collect(),errors=[];
      const add=(message,name)=>errors.push({message,name});
      if(values.attendance_mode==='absent'&&values.absence_reason==='absent_sick'){
        if(!values.absence_temperature?.trim())add('病欠の場合は現在の体温を入力してください。','absence_temperature');
        if(!values.absence_symptoms?.trim())add('病欠の場合は症状を入力してください。','absence_symptoms');
      }
      if(values.attendance_mode==='present'&&currentMask().stool&&values.stool_count && (!/^\d+$/.test(values.stool_count)||Number(values.stool_count)>99))add('排便回数は0〜99の整数で入力してください。','stool_count');
      if(values.emergency_mode==='change'){
        if(!values.emergency_rows.length)add('変更後の連絡先を1件以上登録してください。','emergency_mode');
        values.emergency_rows.forEach(row=>{if(!row.label.trim()||!/^0[0-9\- ]{8,18}$/.test(row.phone))add('緊急連絡先の名前と電話番号を確認してください。','emergency_label');});
      }
      const box=$('contact-errors');box.hidden=!errors.length;
      if(errors.length){box.innerHTML='<b>まだ保存していません</b><ul>'+errors.map(e=>`<li>${esc(e.message)}</li>`).join('')+'</ul>';box.scrollIntoView({block:'center'});return;}
      const mask=currentMask(),saved={...values};
      fields.forEach(([id,,,names])=>{if(!mask[id]||values.attendance_mode!=='present')names.forEach(n=>delete saved[n]);});
      if(values.attendance_mode==='present') ['absence_reason','absence_temperature','absence_symptoms','absence_diagnosis','absence_note'].forEach(n=>delete saved[n]);
      else {['planned_pickup_time','pickup_hour','pickup_minute','pickup_person','snack_required','contact_note'].forEach(n=>delete saved[n]);if(values.absence_reason==='absent_private')['absence_temperature','absence_symptoms','absence_diagnosis'].forEach(n=>delete saved[n]);}
      if(values.emergency_mode!=='change')delete saved.emergency_rows;
      state.records[key()]={values:saved,mask:clone(mask),savedAt:new Date().toLocaleTimeString('ja-JP',{timeZone:'Asia/Tokyo',hour:'2-digit',minute:'2-digit'})};
      delete state.drafts[key()];persist();renderParent();notify('日次連絡をこのタブに仮保存しました。「職員の受け取り」で確認できます。');
    });
    $('cancel-contact').addEventListener('click',()=>{delete state.drafts[key()];persist();renderParent();notify(record?'今回の変更を取り消し、仮保存済みの内容に戻しました。':'今回の入力を取り消し、未入力に戻しました。');});
    document.querySelectorAll('[data-home]').forEach(a=>a.addEventListener('click',event=>{event.preventDefault();navigate('home');}));
  }
  const stoolLabels={none:'なし',normal:'普通',hard:'硬い',soft:'軟らかい',watery:'水様',mixed:'複数の性状',unknown:'不明'};
  const labels={temperature:'体温',bedtime:'就寝',wakeup_time:'起床',sleep_notes:'睡眠メモ',dinner_appetite:'食欲',dinner_contents:'食べたもの',breakfast_appetite:'食欲',breakfast_contents:'食べたもの',stool_consistency:'性状',stool_count:'回数',bowel_movement_status:'排便メモ',mood:'機嫌',cough:'咳',runny_nose:'鼻水',medication:'服薬',condition_note:'体調メモ'};
  function renderRecord(target){
    const record=state.records[key()], out=$(target+'-content');
    out.innerHTML=`<h1 class="record-heading">${esc(childLabel())}</h1><p>${state.day}</p>`;
    if(!record){out.innerHTML+='<p class="record-note">この日の連絡は未提出です。入力途中の内容は表示しません。</p>';return;}
    const v=record.values, present=v.attendance_mode==='present';
    const rows=[['出欠',present?'出席':v.absence_reason==='absent_sick'?'欠席・病欠':'欠席・私用']];
    rows.push(['緊急連絡先',v.emergency_mode==='change'?v.emergency_rows.map((r,i)=>`${i+1}. ${r.label} ${r.phone}`).join('\n'):v.emergency_mode==='usual'?'いつもどおり\n1. 見本保護者の職場 000-0000-0101\n2. 見本保護者の電話 000-0000-0102':'未回答（通常登録あり）']);
    if(present){
      rows.push(['お迎え予定',`時刻：${v.planned_pickup_time||'未入力'}\n人：${v.pickup_person||'未入力'}\n補食：${v.snack_required==='1'?'必要':v.snack_required==='0'?'不要':'未選択'}`]);
      fields.forEach(([id,label,,names])=>rows.push([label,record.mask[id]?names.map(n=>`${labels[n]}：${(n==='stool_consistency'?stoolLabels[v[n]]:v[n])||'未入力'}`).join('\n'):'対象外（保存時の設定）',!record.mask[id]]));
      rows.push(['園への連絡事項',v.contact_note||'未入力']);
    }else{
      if(v.absence_reason==='absent_sick')rows.push(['現在の体温',v.absence_temperature],['症状',v.absence_symptoms],['医師から伝えられた診断名',v.absence_diagnosis||'未入力']);
      rows.push(['備考',v.absence_note||'未入力']);
    }
    out.innerHTML+=`<p class="record-note">仮保存 ${record.savedAt} ／ 保存時の表示項目を保持。設定を変えても過去の記録は消しません。</p><dl class="record-list">${rows.map(([label,value,off])=>`<div><dt>${esc(label)}</dt><dd class="${off?'not-target':''}">${esc(value)}</dd></div>`).join('')}</dl>`;
    if(target==='history'){out.insertAdjacentHTML('beforeend','<div class="settings-actions"><button id="history-edit" class="primary">この連絡を修正</button></div>');$('history-edit').addEventListener('click',()=>navigate('parent'));}
  }
  function render(){
    for(const id of ['settings','parent','home','staff','history'])$(id+'-screen').hidden=id!==view;
    document.querySelectorAll('.screen-tabs [data-view]').forEach(b=>b.setAttribute('aria-pressed',String(b.dataset.view===view || (['home','history'].includes(view)&&b.dataset.view==='parent'))));
    if(view==='settings')renderSettings();else if(view==='parent')renderParent();else if(view==='home'){$('home-child').textContent=childLabel();$('home-status').textContent=state.day+' ／ '+(state.records[key()]?'連絡は仮保存済み':'連絡は未提出');}else renderRecord(view);
  }
  function navigate(next,withPreview=false){capture();preview=withPreview;view=next;persist();render();window.scrollTo({top:0});}
  document.querySelectorAll('[data-view]').forEach(b=>b.addEventListener('click',()=>navigate(b.dataset.view)));
  document.querySelectorAll('[name=settings-mode]').forEach(input=>input.addEventListener('change',()=>{state.draftRules[state.facility].mode=input.value;persist();renderSettings();}));
  for(const id of ['facility','classroom','age','day'])$(id).addEventListener('change',()=>{
    capture();const value=$(id).value;
    if(id==='day'&&!/^\d{4}-\d{2}-\d{2}$/.test(value)){$('day').value=state.day;return;}
    state[id]=id==='age'?Number(value):value;
    if(id==='classroom'&&!classes[value].ages.includes(state.age))state.age=classes[value].ages[0];
    controls();persist();$('notice').hidden=true;render();
  });
  $('save-settings').addEventListener('click',()=>{state.rules[state.facility]=clone(state.draftRules[state.facility]);persist();navigate('parent');notify('この施設の設定を仮保存しました。新しく入力する連絡から使います。');});
  $('preview-settings').addEventListener('click',()=>navigate('parent',true));
  $('cancel-settings').addEventListener('click',()=>{state.draftRules[state.facility]=clone(state.rules[state.facility]);persist();renderSettings();notify('この施設の未保存の設定変更を取り消しました。');});
  $('load-scenario').addEventListener('click',()=>{
    const scenario=$('scenario').value;
    const complete={attendance_mode:'present',contact_type:'present',temperature:'36.6',bedtime:'20:30',wakeup_time:'06:40',sleep_notes:'朝までよく眠りました。',dinner_appetite:'普通',dinner_contents:'ごはん、焼き魚、みそ汁',breakfast_appetite:'旺盛',breakfast_contents:'トースト、バナナ、牛乳',stool_consistency:'normal',stool_count:'1',bowel_movement_status:'朝に1回',mood:'良好',cough:'なし',runny_nose:'少し',medication:'なし',condition_note:'元気に過ごしています。',contact_note:'今日は祖母がお迎えに行きます。',planned_pickup_time:'17:30',pickup_hour:'17',pickup_minute:'30',pickup_person:'祖母',snack_required:'0',emergency_mode:'usual'};
    delete state.records[key()];delete state.drafts[key()];
    if(scenario==='filled')state.records[key()]={values:complete,mask:maskFor(state.rules[state.facility]),savedAt:'07:30'};
    if(scenario==='partial')state.drafts[key()]={attendance_mode:'present',contact_type:'present',temperature:'36.7',breakfast_contents:'バナナ',contact_note:'お迎え時刻は後ほどお知らせします。'};
    if(scenario==='error')state.drafts[key()]={attendance_mode:'absent',contact_type:'absent_sick',absence_reason:'absent_sick',absence_temperature:'',absence_symptoms:'',absence_note:'この文章はエラーでも残ります。'};
    preview=false;view='parent';persist();render();notify('この園児・日の架空データを「'+$('scenario').selectedOptions[0].textContent+'」にしました。');
    if(scenario==='error')$('contact-form').requestSubmit();
  });
  controls();render();
  if(migrated){persist();notify('設定方法を更新しました。設定は新しい見本から試せます。これまでの仮保存済み連絡と入力途中の内容は残しています。');}
})();
