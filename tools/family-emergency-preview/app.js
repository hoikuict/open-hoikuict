(function main(){
const $ = (s, root=document) => root.querySelector(s);
const $$ = (s, root=document) => Array.from(root.querySelectorAll(s));
const esc = value => String(value ?? '').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const copy = value => JSON.parse(JSON.stringify(value));
const firstDay = '2026-11-09';
const names = {1:'見本 あおい',2:'見本 ひなた'};
const groups = {1:'さくら組',2:'ひよこ組'};
const meals = [
 {id:'dinner',label:'夕食',legacyKey:'dinner_amount',legacyLabel:'食べた量'},
 {id:'breakfast',label:'朝食',legacyKey:'breakfast_status',legacyLabel:'朝食・食欲'}
];
const stoolLabels={normal:'普通',none:'なし',soft:'軟らかい',hard:'硬い',watery:'水様',mixed:'複数の性状',unknown:'不明'};
const actors = {母:'見本 はなこ',父:'見本 たろう'};
const requestedExample=new URLSearchParams(location.search).get('family');
const sampleKey=Object.hasOwn(contactExamples,requestedExample)?requestedExample:'standard';
const sample=contactExamples[sampleKey];
const firstActor=Object.keys(actors).find(key=>sample.guardians.some(g=>g.name===actors[key]));
$('#family-example').value=sampleKey;
for(const option of $('#actor').options){
 const guardian=sample.guardians.find(g=>g.name===actors[option.value]);
 option.hidden=option.disabled=!guardian;
 if(guardian)option.textContent=guardian.role||guardian.name;
}
function defaultContacts(guardians){
 const priority=role=>role==='母'?0:role==='父'?1:2;
 const sorted=[...guardians].sort((a,b)=>priority(a.role)-priority(b.role));
 const result=[];
 for(const field of ['office','phone']){
  for(const guardian of sorted){
   if(!guardian[field])continue;
   const role=guardian.role;
   const uniqueRole=role&&role!=='保護者'&&guardians.filter(g=>g.role===role).length===1;
   const who=uniqueRole?role:guardian.name||`保護者${guardians.indexOf(guardian)+1}`;
   const phoneType=field==='office'?'職場':guardian.mobile?'携帯':'電話';
   result.push({id:`guardian-${guardian.id}-${field}`,label:`${who}の${phoneType}`,phone:guardian[field]});
  }
 }
 return result;
}
const candidates=defaultContacts(sample.guardians);
const grandma = {label:'祖母の携帯',phone:'000-0000-0105',id:'grandma',only:true};
const storeKey = 'hoikuict-child-emergency-mock-v1'+(requestedExample===sampleKey?'-'+sampleKey:'');
const emptyOrder = () => ({usual:[],baseRev:0,days:{},history:[]});
const emptyState = () => ({orders:{1:emptyOrder(),2:emptyOrder()},entries:{},tick:0});
let db=emptyState(), today=firstDay, day=firstDay, actor=firstActor, child=1, screen='', editing, rows=[], dailyMode='', baseRev, dayRev, entryRev;
let toastTimer=0;
let oralMode='day', informant='';
const isBaseEditor=()=>screen==='usual'||(screen==='oral'&&oralMode==='base');
function recordChange(kind,record,targetDate=''){
 order().history.push({...copy(record),kind,targetDate});
}
const blankRow=()=>({id:ids(),label:'',phone:''});
function editorRows(source){return source.length?copy(source):[blankRow()];}
function read(){try{const saved=localStorage.getItem(storeKey);if(saved)db=JSON.parse(saved);}catch{/* offline file may disable persistence */}}
function write(){try{localStorage.setItem(storeKey,JSON.stringify(db));}catch{/* the open page still works */}}
read();
function message(s){const el=$('#status');el.textContent=s;el.hidden=false;clearTimeout(toastTimer);toastTimer=setTimeout(()=>{el.hidden=true;},3200);}
const order=(id=child)=>db.orders[id];
const activeReply=(d,id=child)=>order(id).days[d]?.mode==='withdraw'?undefined:order(id).days[d];
function allowedChildren(){
 const selection=$('#scope').value;
 return selection==='both'?[1,2]:selection==='none'?[]:[Number(selection)];
}
function attributed(record){
 return record.by==='staff'?`口頭・${esc(record.informant)}から／受付：見本 職員`:esc(actors[record.by])+'（保護者アプリ）';
}
const key=(id=child,d=day)=>`${id}|${d}`;
const pickupFields=['planned_pickup_time','pickup_hour','pickup_minute','pickup_person','snack_required'];
let pickupRevision;
function pickupValues(id=child,d=day){
 const k=key(id,d), values=db.pickups?.[k]?.values||db.entries[k]?.values||{};
 return Object.fromEntries(pickupFields.map(name=>[name,values[name]??'']));
}
function entry(id=child,d=day){
 const row=db.entries[key(id,d)];
 if(!row||row.values.contact_type!=='present')return row;
 return {...row,values:{...row.values,...pickupValues(id,d)}};
}
const dateLabel=d=>{const [,m,n]=d.split('-');return `${+m}月${+n}日`;};
function previous(d){const dt=new Date(d+'T12:00:00Z');dt.setUTCDate(dt.getUTCDate()-1);return dt.toISOString().slice(0,10);}
function stamp(){const n=8*60+10+(++db.tick);return `${dateLabel(today)} ${String(Math.floor(n/60)%24).padStart(2,'0')}:${String(n%60).padStart(2,'0')}`;}
function dayReply(mode,list,by=actor){
 const usual=order().usual;
 const snapshot=list.map(r=>({...r,only:!usual.some(c=>c.label===r.label&&c.phone===r.phone)}));
 return {mode,rows:snapshot,by,at:stamp(),rev:(order().days[day]?.rev||0)+1};
}
function ids(){return 'c'+Math.random().toString(36).slice(2);}
function nav(route){if(location.hash==='#'+route)render();else location.hash=route;}
function button(action,label,style='',attrs=''){return `<button type="button" class="btn ${style}" data-act="${action}" ${attrs}>${esc(label)}</button>`;}
function link(route,label,style='text-link'){return `<a href="#${route}" class="${style}">${esc(label)}</a>`;}
function choice(value,label,disabled=false){return `<label class="choice"><input type="radio" name="emergency_mode" value="${value}" ${dailyMode===value?'checked':''} ${disabled?'disabled':''}>${label}</label>`;}
function list(items){return items.length?`<ol class="order-list">${items.map((r,i)=>`<li><span class="rank">${i+1}</span><b>${esc(r.label)}</b>${r.only?'<span class="day-only">この日だけ</span>':''}<span class="number">${esc(r.phone)}</span></li>`).join('')}</ol>`:'<p class="hint">いつもの連絡順は未登録です。</p>';}
function actorNav(staff){return `<div class="appbar ${staff?'staff':''}"><div class="appnav"><b>open-hoikuict</b><span>${staff?'職員画面':'保護者ホーム'}</span><span class="actor-name">${staff?'見本 職員':actors[actor]}</span><details class="menu"><summary>メニュー</summary><div class="pop">${staff?link('children','園児一覧')+link('meals','日次連絡'):link('home','保護者ホーム')+link('usual','緊急時の連絡先')+link('history','連絡履歴')}</div></details></div></div>`;}
function jump(id,label){return `<button type="button" data-jump="${id}">${esc(label)}</button>`;}
function heading(title,extra=''){return `<div class="screen-head"><h1>${esc(title)}</h1>${extra}</div>`;}
const dateControl=()=>`<label class="date-label">対象日<input type="date" class="view-date" value="${esc(day)}"></label>`;
function render(){
 read();
 const [requested,rawId,section]=(location.hash.slice(1)||'home').split('/');
 screen=['home','usual','oral','daily','pickup','history','children','profile','meals','detail'].includes(requested)?requested:'home';
 if(rawId==='1'||rawId==='2')child=Number(rawId);
 const staff=['children','profile','meals','detail','oral'].includes(screen);
 if(staff&&['profile','oral','detail'].includes(screen)&&!['1','2'].includes(rawId)){location.replace('#children');return;}
 $('#parent-tab').setAttribute('aria-current',staff?'false':'page');$('#staff-tab').setAttribute('aria-current',staff?'page':'false');
 $('#appbar').innerHTML=actorNav(staff);$('#race').hidden=sample.guardians.length<2||!['daily','oral','usual'].includes(screen)||screen==='usual'&&!rawId;
 $('#clock').value=today;$('#actor').value=actor;$('#closing').value=closingTime();
 const main=$('#main');main.replaceChildren();
 if(!staff && (['daily','pickup'].includes(screen)||screen==='usual'&&rawId) &&
    (!['1','2'].includes(rawId)||!allowedChildren().includes(child))){
  $('#race').hidden=true;
  main.innerHTML='<div class="sheet card"><h1>緊急時の連絡先</h1><p>このお子さまの登録を園にご確認ください。</p>'+link('usual','お子さまを選ぶ')+'</div>';
  return;
 }
 if(screen==='home')showHome();
 if(screen==='daily')showDaily();
 if(screen==='pickup')showPickup();
 if(screen==='usual'){
  if(rawId)showUsual();
  else if(allowedChildren().length===1){location.replace('#usual/'+allowedChildren()[0]);return;}
  else showChildPicker();
 }
 if(screen==='oral'){
  if($('#staff-role').value!=='edit'){location.replace('#profile/'+child);return;}
  day=today;oralMode='day';informant='';showOral();
 }
 if(screen==='children')showChildren();
 if(screen==='profile')showProfile();
 if(screen==='meals'){showMeals();bindMealFilters();}
 if(screen==='detail'||screen==='history'){showHistory();if(screen==='detail')bindReply();}
 if(screen==='daily'&&section==='meals'&&$('#dinner-heading').getClientRects().length)$('#dinner-heading').scrollIntoView();
 else if(screen==='profile'&&section==='contacts')$('#family-emergency').scrollIntoView();
 else window.scrollTo(0,0);
}
function showHome(){
 const main=$('#main');main.innerHTML=$('#home-template').innerHTML.replaceAll('MOCKDATE',day).replaceAll('見本 はなこ',actors[actor]);
 const form=$('form',main);
 if(form){form.addEventListener('submit',e=>{e.preventDefault();const chosen=$('input[type=date]',form).value;if(chosen){day=chosen;render();}});}
 [1,2].forEach(i=>{const a=$(`a[href="#daily/${i}"]`,main);if(!a)return;if(!allowedChildren().includes(i)){a.closest('.rounded-xl').remove();return;}const s=entry(i);a.textContent=s?'日次連絡を編集':'日次連絡を入力';const pill=a.parentNode.querySelector('span');if(pill)pill.textContent=s?'送信済み':'未送信';});
 const counts=$$('p.text-2xl',main);const present=allowedChildren().filter(i=>entry(i)).length;
 if(counts.length>=2){counts[0].textContent=String(allowedChildren().length);counts[1].textContent=String(present);if(counts[2])counts[2].textContent='0';}
}
function initEditor(){baseRev=order().baseRev;dayRev=order().days[day]?.rev||0;entryRev=entry()?.rev||0;}
function canUseDirectory(){return screen==='oral'||allowedChildren().length===2;}
function availableContacts(base){
 if(!base)return order().usual;
 if(!canUseDirectory())return [];
 return [...candidates,...(sample.extras[child]||[])];
}
function initialUsualRows(){
 if(order().usual.length)return copy(order().usual);
 const defaults=copy(availableContacts(true));
 if(canUseDirectory()&&sample.guardians.length===1&&!sample.extras[child]?.length){
  defaults.push({...blankRow(),optionalExtra:true});
 }
 return editorRows(defaults);
}
function emptyOptionalRow(row){return row.optionalExtra&&!row.label.trim()&&!row.phone.trim();}
function usualRowsToSave(){
 return rows.filter(r=>!emptyOptionalRow(r))
  .map(({id,label,phone})=>({id,label:label.trim(),phone:phone.trim()}));
}
function editorMarkup(base){
 const avail=availableContacts(base);
 const remaining=avail.filter(c=>!rows.some(r=>r.id===c.id||(r.label===c.label&&r.phone===c.phone)));
 return `<div class="edit-list">${rows.map((r,i)=>{
 return `<div class="edit-row" data-i="${i}"><span class="rank">${i+1}</span>
 <label>${r.optionalExtra?'その他の連絡先（任意）':'連絡先の名前'}<input data-prop="label" aria-label="${i+1}番目の連絡先の名前" value="${esc(r.label)}" maxlength="70" placeholder="例：祖母の携帯"></label><label>電話番号<input data-prop="phone" aria-label="${i+1}番目の電話番号" type="tel" maxlength="30" value="${esc(r.phone)}" placeholder="電話番号"></label>
 ${r.only?'<span class="day-only">この日だけ</span>':''}<div class="arrows"><button type="button" data-move="-1" aria-label="${i+1}番目を上へ" ${i===0?'disabled':''}>↑</button><button type="button" data-move="1" aria-label="${i+1}番目を下へ" ${i===rows.length-1?'disabled':''}>↓</button><button type="button" data-remove aria-label="${i+1}番目を外す">外す</button></div></div>`;
 }).join('')}</div>
 ${remaining.length?`<details class="candidates"><summary>${base?'台帳の電話番号から選ぶ':'いつもの連絡先から選ぶ'}</summary><div class="actions">${remaining.map(r=>button('candidate',r.label+' '+r.phone,'',`data-id="${esc(r.id)}"`)).join('')}</div></details>`:''}
 <div class="actions">${button('add-row',base?'連絡先を追加':'この日だけの連絡先を追加')}</div>`;
}
function initRowsForDay(mode){const answer=order().days[day];return editorRows(mode==='change'&&answer?.mode==='change'?answer.rows:order().usual);}
function showChildPicker(){
 const ids=allowedChildren();
 $('#main').innerHTML=`<div class="sheet">${heading('緊急時の連絡先')}<section class="card">
 ${ids.length?'<h2>お子さまを選んでください</h2>':'<p>お子さまの登録を園にご確認ください。</p>'}
 ${ids.map(id=>`<div class="roster-row"><div><b>${esc(names[id])}</b><div class="hint">${order(id).usual.length?'登録済み':'未登録'}</div></div>${link('usual/'+id,order(id).usual.length?'連絡順を確認・変更':'連絡順を登録','link-btn')}</div>`).join('')}
 </section>${link('home','保護者ホームへ')}</div>`;
}
function showUsual(){
 initEditor();rows=initialUsualRows();
 $('#main').innerHTML=`<div class="sheet"><div class="crumb">${link('home','保護者ホーム')} › ${link('usual','緊急時の連絡先')}</div>
 ${heading(names[child]+'さんの緊急連絡先')}<section class="card"><h2>いつもの連絡順</h2>
 <p>${order().usual.length?'':'連絡先の名前と電話番号を確認してください。'}園から最初に電話してほしい相手を、1番目にしてください。</p><div id="editor-rows"></div>
 <p tabindex="-1" id="problem" role="alert" hidden></p><div class="actions">${button('save-usual','いつもの連絡順を保存','primary')}${link('home','キャンセル','link-btn')}</div></section></div>`;
 drawRows();
}
function showOral(){
 initEditor();
 rows=oralMode==='base'?initialUsualRows():initRowsForDay('change');
 $('#main').innerHTML=`<div class="sheet"><div class="crumb">${link('profile/'+child,'園児詳細に戻る')}</div>
 ${heading(names[child]+'さんの口頭連絡')}<section class="card"><fieldset><legend>どの連絡順を記録しますか？</legend><div class="actions">
 ${[['day','その日だけ'],['base','いつもの連絡順']].map(([value,label])=>`<label class="choice"><input type="radio" name="oral_mode" value="${value}" ${oralMode===value?'checked':''}>${label}</label>`).join('')}</div></fieldset>
 ${oralMode==='day'?`<label class="date-label">対象日<input id="oral-date" type="date" value="${esc(day)}"></label>`:''}
 <label class="oral-from">伝えてくれた方<input id="informant" value="${esc(informant)}" maxlength="80" placeholder="例：お母さま"></label>
 <h2>電話する順番</h2>${oralMode==='day'&&order().usual.length?button('use-usual','いつもの連絡順を使う'):''}<div id="editor-rows"></div><p class="hint">受付職員：見本 職員</p>
 ${oralMode==='base'&&activeReply(today)?'<p class="hint">今日の連絡順はすでに届いています。今日の分も変えるときは「その日だけ」で記録してください。</p>':''}
 <p id="problem" tabindex="-1" role="alert" hidden></p><div class="actions">${button('save-oral',oralMode==='day'?'この日だけの連絡順を保存':'いつもの連絡順を保存','primary')}${link('profile/'+child+'/contacts','キャンセル','link-btn')}</div></section></div>`;
 drawRows();
}
function saveOral(){
 if($('#staff-role').value!=='edit')return;
 if(oralMode==='day'&&!$('#oral-date').value){problem('連絡順を変える日を選んでください。');return;}
 informant=$('#informant').value.trim();
 if(!informant){problem('伝えてくれた方を入力してください。');return;}
 const error=rowError();if(error){problem(error);return;}
 read();const current=order();
 if(current.baseRev!==baseRev || oralMode==='day' && (current.days[day]?.rev||0)!==dayRev){
  problem('このお子さまの連絡順が更新されました。最新の内容を確認してください。',true);return;
 }
 if(oralMode==='base'){
  const contacts=usualRowsToSave();
  current.usual=contacts;current.baseRev++;
  recordChange('いつもの連絡順',{rows:contacts,at:stamp(),by:'staff',informant});
 }else{
  const same=rows.length===current.usual.length&&rows.every((r,i)=>r.label===current.usual[i].label&&r.phone===current.usual[i].phone);
  const record={...dayReply(same?'usual':'change',rows,'staff'),informant};
  current.days[day]=record;recordChange('その日の連絡順',record,day);
 }
 write();
 nav('profile/'+child+'/contacts');
 const scopeLabel=oralMode==='base'?'いつもの連絡順':dateLabel(day)+'の連絡順';
 message(names[child]+'さんの'+scopeLabel+'を保存しました。');
}
function clearFieldProblem(){const alert=$('#problem');if(alert&&!alert.querySelector('button'))alert.hidden=true;}
function drawRows(){const target=$('#editor-rows');if(target)target.innerHTML=editorMarkup(isBaseEditor());clearFieldProblem();}
function problem(text,reload=false){const p=$('#problem');p.className='error';p.hidden=false;p.innerHTML=esc(text)+(reload?' '+button('reload','最新の連絡順を確認する'):'');p.focus();}
function rowError(){
 if(rows.every(emptyOptionalRow))return '電話してほしい連絡先を一つ以上入れてください。';
 for(const [i,row] of rows.entries()){
  if(emptyOptionalRow(row))continue;
  if(!row.label.trim())return `${i+1}番目の連絡先の名前を入れてください。`;
  if(!/^[0-9]{9,15}$/.test(row.phone.normalize('NFKC').replace(/[\s()（）\-ー−]/g,''))){
   return `${i+1}番目の電話番号を市外局番から入れてください。`;
  }
 }
 return '';
}
function closingTime(){return db.mockClosingTime||$('#closing').defaultValue;}
function updatePickupLimit(){
 const root=$('#main [data-pickup-fields]');
 if(!root)return;
 const closing=closingTime();
 root.dataset.closingTime=closing;
 const hint=$('[data-closing-hint]',root);
 hint.textContent=`この園の閉園は${closing}です。それより前の時刻を選んでください。`;
 for(const group of $$('.pickup-hours',root)){
  const buttons=$$('[data-pickup-hour]',group);
  for(const button of buttons){
   button.hidden=button.disabled=button.dataset.pickupHour+':00'>=closing;
  }
  group.hidden=buttons.every(button=>button.hidden);
  group.previousElementSibling.hidden=group.hidden;
 }
 root.dispatchEvent(new Event('closingchange'));
 const err=$('[data-pickup-time-error]',root);
 err.textContent=`閉園（${closing}）より前の「時」と「分」を選んでください。`;
 const hour=$('[data-pickup-hour-input]',root).value, minute=$('[data-pickup-minute-input]',root).value;
 if(hour && hour+':'+(minute||'00')>=closing)err.classList.remove('hidden');
}
function preparePickup(form){
 pickupRevision=db.pickups?.[key()]?.rev||0;
 const values=pickupValues();
 const [hour,minute]=values.planned_pickup_time.split(':');
 values.pickup_hour||=hour||''; values.pickup_minute||=minute||'';
 fillForm(form,values);
 const root=$('[data-pickup-fields]',form);
 $('legend',root).insertAdjacentHTML('afterend','<p class="text-sm text-slate-600" data-closing-hint></p>');
 const additional=$('details',root);
 $('summary',additional).textContent='その他の時刻（閉園前）';
 additional.open=$$('[data-pickup-hour]',additional).some(button=>button.dataset.pickupHour===values.pickup_hour);
 if(values.pickup_minute&&!['00','15','30','45'].includes(values.pickup_minute))$('[data-pickup-minute-exact]',root).closest('details').open=true;
 updatePickupLimit();
 bindPickupFields();
}
function fillForm(form,values){
 for(const field of form.elements){
  if(!field.name||!(field.name in values))continue;
  if(field.type==='radio')field.checked=field.value===values[field.name];
  else field.value=values[field.name];
 }
}
function storePickup(form){
 const root=$('[data-pickup-fields]',form), time=$('[data-pickup-time-input]',root).value;
 if(root.dataset.closingTime!==closingTime()){
  $('#closing').value=closingTime();updatePickupLimit();
 }
 if(time&&time>=closingTime()){
  const err=$('[data-pickup-time-error]',root);
  err.classList.remove('hidden');err.scrollIntoView({block:'center'});return false;
 }
 if(pickupRevision!==(db.pickups?.[key()]?.rev||0)){
  message('お迎え予定が更新されました。ホームから開き直して確かめてください。');return false;
 }
 const data=new FormData(form);
 db.pickups??={};
 db.pickups[key()]={rev:pickupRevision+1,values:Object.fromEntries(pickupFields.map(name=>[name,data.get(name)||'']))};
 return true;
}
function showPickup(){
 $('#main').innerHTML=$('#pickup-template').innerHTML.replaceAll('MOCKDATE',day).replaceAll('MOCKCHILD',names[child]);
 const form=$('#main form');preparePickup(form);
 form.addEventListener('submit',e=>{
  const invalid=e.defaultPrevented;e.preventDefault();if(invalid)return;
  read();if(!storePickup(form))return;
  write();nav('home');message('お迎え予定を保存しました。');
 });
}
function showDaily(){
 initEditor();dailyMode='';editing=!activeReply(day);rows=initRowsForDay('change');
 const main=$('#main');main.innerHTML=$('#daily-template').innerHTML.replaceAll('MOCKDATE',day).replaceAll('MOCKCHILD',names[child]);
 const form=$('form',main);const saved=entry()?.values||{};
 fillForm(form,saved);
 $('#dinner-heading').textContent=`${dateLabel(previous(day))}の夕食（前日）`;$('#breakfast-heading').textContent=`${dateLabel(day)}の朝食（当日）`;
 for(const meal of meals){
  const prior=document.createElement('p');prior.className='hint';$('#'+meal.id+'-heading',form).parentElement.append(prior);
  prior.textContent=priorMealNote(meal,saved);
  prior.hidden=!prior.textContent;
 }
 for(const clear of $$('[data-clear-appetite]',form))clear.hidden=!$('input:checked',clear.closest('fieldset'));
 form.insertAdjacentHTML('beforebegin',`<div class="jump">${jump('emergency','緊急連絡先へ')}${jump('dinner-heading','夕食・朝食へ')}${jump('save-daily','保存するところへ')}</div>`);$('button[type=submit]',form).id='save-daily';
 $('#emergency').className='emergency';drawEmergency();
 bindDeployedFields();
 preparePickup(form);
 for(const item of $$('[data-quick-choices], [data-temperature-picker]')){const id=item.dataset.quickChoices||item.dataset.temperaturePicker;$('#'+id)?.dispatchEvent(new Event('input'));}
 function modeStyle(){for(const f of $$('input[name=attendance_mode],input[name=absence_reason]',form)){const l=f.closest('label');l.style.borderColor=f.checked?'#6366f1':'';l.style.background=f.checked?'#eef2ff':'white';}const dinnerJump=$('[data-jump=dinner-heading]');dinnerJump.hidden=$('#present-fields').classList.contains('hidden');}
 form.addEventListener('change',modeStyle);modeStyle();
 form.addEventListener('submit',e=>{const invalid=e.defaultPrevented;e.preventDefault();if(invalid)return;saveDaily(form);});
}
function drawEmergency(){
 const answer=activeReply(day), area=$('#emergency');
 let content;
 if(answer&&!editing){content=`<p class="sub">この日の連絡先は、登録されています。${esc(answer.at)}・${attributed(answer)}</p><b>${answer.mode==='change'?'この日は連絡順が変わっています':'いつもどおりです'}</b>${list(answer.rows)}${button('amend','この日の連絡先を変更')}`;}
 else{
 content=`<p class="sub">この日に園から電話してほしい順番を、このお子さまについてお知らせください。</p><div class="actions">${choice('usual',answer?.mode==='change'?'いつもの順番に戻す':'いつもどおり',!order().usual.length)}${choice('change','今日は変更する')}${answer&&!order().usual.length?choice('withdraw','この日の回答を取り消す'):''}</div>`;
 if(dailyMode==='change')content+=`<p class="hint">上から順に電話します。矢印で順番を変えられます。</p><div id="editor-rows"></div>`;
 else content+=`<div class="hint">いつもの連絡順</div>${list(order().usual)}${!order().usual.length?link('usual/'+child,'この子のいつもの連絡順を登録'):''}`;
 if(answer)content+=`<div class="actions">${button('cancel-edit','変更をやめる')}</div>`;
 }
 area.innerHTML=`<h2>${dateLabel(day)}の緊急連絡先</h2>${content}<div id="problem" tabindex="-1" role="alert" hidden></div>`;drawRows();
}
function saveDaily(form){
 const values=Object.fromEntries(new FormData(form));delete values.emergency_mode;
 if(values.contact_type==='absent_sick'&&(!values.absence_temperature.trim()||!values.absence_symptoms.trim())){problem('病欠の場合は、現在の体温と症状を入れてください。');return;}
 const submitOrder=editing&&!!dailyMode;
 if(submitOrder&&dailyMode==='change'){const err=rowError();if(err){problem(err);return;}}
 read();
 if(entryRev!==(entry()?.rev||0)){problem('このお子さまの日次連絡が更新されました。最新の内容を開き直してください。',true);return;}
 if(submitOrder&&(dayRev!==(order().days[day]?.rev||0)||baseRev!==order().baseRev)){problem('このお子さまの連絡先が更新されました。最新の連絡順を確認してください。',true);return;}
 if(values.contact_type==='present'&&!storePickup(form))return;
 const previousValues=entry()?.values||{};
 for(const {legacyKey} of meals){
  if(previousValues[legacyKey])values[legacyKey]=previousValues[legacyKey];
 }
 if(submitOrder){order().days[day]=dayReply(dailyMode,dailyMode==='withdraw'?[]:dailyMode==='change'?rows:order().usual);}
 if(submitOrder) recordChange('日次連絡',order().days[day],day);
 db.entries[key()]={values,rev:entryRev+1,by:actor,at:stamp()};write();nav('home');message('日次連絡を保存しました。');
}
function showProfile(){
 $('#main').innerHTML=`<div class="crumb">${link('children','園児一覧')} › 詳細</div><div class="jump">${jump('family-emergency','今日の緊急連絡先へ')}</div>`+$('#profile-'+sampleKey+'-'+child).innerHTML;
 const reply=activeReply(today), changed=reply?.mode==='change', confirmed=!!reply;
 const title=changed?'今日は連絡順が変わっています':confirmed?'今日はいつもどおりです':(order().usual.length?'今日の連絡先は未回答です':'連絡順は未登録です');
 const box=$('#family-emergency');box.className='emergency'+(changed?' changed':'');box.style.marginBottom='18px';
 box.innerHTML=`<h2>今日の緊急連絡先</h2><div class="sub">${dateLabel(today)}${reply?'・受付 '+esc(reply.at)+'・'+attributed(reply):''}</div><p class="flag ${changed?'':'normal'}">${title}</p>${!confirmed&&order().usual.length?'<div class="hint">いつもの連絡順</div>':''}${list(reply?.rows||order().usual)}${changed?`<details><summary>いつもの連絡順を見る</summary>${list(order().usual)}</details>`:''}`;
 box.insertAdjacentHTML('beforeend',`<p class="hint">${esc(names[child])}さんの連絡先</p><div class="actions">
 ${$('#staff-role').value==='edit'?link('oral/'+child,'口頭の連絡を記録','link-btn'):''}
 </div><details><summary>連絡順の変更履歴</summary>${order().history.length?
 order().history.slice().reverse().map(r=>`<div class="divider"><b>${esc(r.kind)}${r.targetDate?'（'+dateLabel(r.targetDate)+'）':''}</b><p>${esc(r.at)}・${attributed(r)}</p>${r.mode==='withdraw'?'この日の回答を取り消しました。':list(r.rows)}</div>`).join(''):'<p>変更履歴はまだありません。</p>'}</details>`);
}
function priorMealNote(meal,values){
 const old=values[meal.legacyKey];
 return old?`以前の記録（${meal.legacyLabel}）：${old}`:'';
}
function mealSummary(values,d){
 if(!values)return '未提出';
 if(values.contact_type!=='present')return '欠席・対象外';
 return meals.map(meal=>{
  const date=meal.id==='dinner'?previous(d):d;
  const appetite=values[meal.id+'_appetite']||'未入力';
  const contents=values[meal.id+'_contents']||'未入力';
  const prior=priorMealNote(meal,values);
  return `<span class="meal-line"><small>${dateLabel(date)}の${meal.label}</small><br>食欲：${esc(appetite)}<br>食べたもの：${esc(contents)}${prior?'<br>'+esc(prior):''}</span>`;
 }).join('');
}
function showMeals(){
 const titles=['名前','機嫌','排便','睡眠','食事','検温','お迎え','子どもの様子・連絡','症状・服薬','園返信'];
 $('#main').innerHTML=`${heading('保護者連絡一覧・内容一覧')}<div class="table-scroll" tabindex="0"><table class="mock-table wide"><thead><tr>${titles.map(t=>`<th>${t}</th>`).join('')}</tr></thead><tbody>${[1,2].map(i=>{const v=entry(i)?.values;
 const cells=[v?.mood,[stoolLabels[v?.stool_consistency],v?.stool_count==null||v.stool_count===''?'':v.stool_count+'回',v?.bowel_movement_status].filter(Boolean).join(' '),[v?.bedtime,v?.wakeup_time,v?.sleep_notes].filter(Boolean).join(' ')];
 const plan=pickupValues(i);
 return `<tr><td>${link('detail/'+i,names[i])}<br><small>${groups[i]}</small></td>${cells.map(t=>`<td>${esc(t||'—')}</td>`).join('')}<td class="meals">${mealSummary(v,day)}</td><td>${esc(v?.temperature||v?.absence_temperature||'—')}</td><td>${esc([plan.planned_pickup_time,plan.pickup_person,plan.snack_required==='1'?'補食あり':plan.snack_required==='0'?'補食なし':''].filter(Boolean).join(' ')||'—')}</td><td>${esc([v?.condition_note,v?.contact_note,v?.absence_note].filter(Boolean).join('\n')||'—')}</td><td>${esc([v?.cough,v?.runny_nose,v?.medication,v?.absence_symptoms].filter(Boolean).join(' ')||'—')}</td><td>未送信</td></tr>`;}).join('')}</tbody></table></div><div class="actions">${link('children','園児一覧へ')}</div>`;
}
function showHistory(){
 const staff=screen==='detail';const records=staff?[child]:allowedChildren();
 $('#main').innerHTML=`<div class="sheet">${heading(staff?'日次連絡の詳細':'連絡履歴',dateControl())}${records.map(i=>{const s=entry(i);const reply=activeReply(day,i);return `<article class="card"><h2>${names[i]}</h2><p class="sub">${dateLabel(day)}・${groups[i]}${s?'・'+esc(s.at)+' '+actors[s.by]:''}</p>${s?`<div class="summary-grid"><div>${mealSummary(s.values,day)}</div><div><b>出欠</b><p>${({present:'出席',absent_private:'私用休み',absent_sick:'病欠'})[s.values.contact_type]}</p></div><div><b>園への連絡</b><p>${esc(s.values.contact_note||s.values.absence_note||'—')}</p></div></div>${extraValues(s.values)}`:'<p>この日の日次連絡は未提出です。</p>'}${reply ? '<h3>この日の緊急連絡先</h3><p>'+attributed(reply)+'</p>'+list(reply.rows) : '<p>この日の緊急連絡先は未回答です。</p>'}${replySummary(i)}${!staff?link('daily/'+i,s?'日次連絡を編集':'日次連絡を入力'):''}</article>`;}).join('')}
${staff?link('meals','内容一覧に戻る'):link('home','ホームへ戻る')}</div>`;
}

const mealFilters={room:'',sort:'classroom'};
function showChildren(){
 const main=$('#main');main.innerHTML=$('#roster-template').innerHTML.replaceAll('MOCKGUARDIANS',esc(sample.guardians.map(g=>g.name).join('・')));
 const form=$('#filter-form'),body=$('#table-area tbody'),allRows=Array.from(body.rows);
 const columns=$$('input[name=fields]',form);
 function filter(){
  const hasChildren=['all','enrolled'].includes(form.elements.status.value);
  const sorted=allRows.slice();if(form.elements.sort_order.value==='desc')sorted.reverse();
  for(const row of sorted){body.appendChild(row);row.hidden=!hasChildren;}
  columns.forEach((box,i)=>{for(const row of $$('#table-area tr',main)){if(row.cells.length>1)row.cells[i].hidden=!box.checked;}});
  const count=$('#table-area .border-b');if(count)count.textContent=hasChildren?'2 名':'0 名';
  let none=$('#none-found');if(!none){none=document.createElement('p');none.id='none-found';none.className='card';none.textContent='表示する園児がありません。';$('#table-area').appendChild(none);}none.hidden=hasChildren;
 }
 form.addEventListener('change',filter);form.addEventListener('submit',e=>e.preventDefault());filter();
 main.insertAdjacentHTML('beforeend',`<div class="actions">${link('meals','日次連絡の内容一覧')}</div>`);
}
function extraValues(v){
 const labels={temperature:'体温',bedtime:'就寝',wakeup_time:'起床',sleep_notes:'睡眠メモ',stool_consistency:'排便の性状',stool_count:'排便の回数',bowel_movement_status:'排便メモ',mood:'機嫌',medication:'服薬',cough:'咳',runny_nose:'鼻水',planned_pickup_time:'お迎え予定時刻',pickup_person:'お迎え予定の人',snack_required:'補食',condition_note:'体調メモ',absence_temperature:'現在の体温',absence_symptoms:'症状',absence_diagnosis:'医師から伝えられた診断名'};
 return `<dl class="summary-grid divider">${Object.entries(labels).filter(([k])=>v[k]).map(([k,label])=>`<div><dt>${label}</dt><dd>${esc(k==='snack_required'?(v[k]==='1'?'必要':'不要'):k==='stool_consistency'?stoolLabels[v[k]]:v[k])}</dd></div>`).join('')}</dl>`;
}
function bindMealFilters(){
 const bar=document.createElement('form');bar.className='options card';
 bar.innerHTML=`<label>日付<input type="date" name="date" value="${day}" required></label><label>クラス<select name="room"><option value="">すべて</option><option>さくら組</option><option>ひよこ組</option></select></label><label>表示順<select name="sort"><option value="classroom">クラス・園児順</option><option value="unsubmitted_first">未提出を先頭</option><option value="submitted_first">提出済みを先頭</option><option value="unsent_first">園の未送信を先頭</option></select></label><button class="btn primary">表示</button>`;
 $('#main .screen-head').after(bar);bar.elements.room.value=mealFilters.room;bar.elements.sort.value=mealFilters.sort;
 const tb=$('.wide tbody');const sorted=Array.from(tb.rows);
 function priority(id){if(mealFilters.sort==='classroom')return groups[id];if(mealFilters.sort==='unsent_first')return db.replies?.[key(id)]?.published?'1':'0';const submitted=!!entry(id);return (mealFilters.sort==='submitted_first'?submitted:!submitted)?'0':'1';}
 const id=r=>Number(r.querySelector('a').hash.split('/')[1]);
 sorted.sort((a,b)=>priority(id(a)).localeCompare(priority(id(b)),'ja')).forEach(r=>{r.hidden=!!mealFilters.room&&groups[id(r)]!==mealFilters.room;tb.appendChild(r);const rep=db.replies?.[key(id(r))];if(rep)r.lastElementChild.textContent=rep.draft?'未送信':rep.published?'公開済み':'未送信';});
 bar.onsubmit=e=>{e.preventDefault();day=bar.elements.date.value;mealFilters.room=bar.elements.room.value;mealFilters.sort=bar.elements.sort.value;render();};
}
function bindReply(){
 $('#main .sheet').insertAdjacentHTML('beforeend',$('#reply-template').innerHTML);
 const f=$('#daily-reply-form'),k=key(),saved=db.replies?.[k];
 for(const [name,value] of Object.entries(saved?.draft||saved?.published||{})){if(f.elements[name])f.elements[name].value=value;}
 if(saved)$('#reply-state').textContent=saved.draft?'未送信':'公開済み';
 f.onsubmit=e=>{e.preventDefault();const publish=e.submitter?.value==='publish';
 if(publish&&!window.confirm('見本の保護者画面にこの返信を表示しますか？'))return;
 const values=Object.fromEntries([...new FormData(f)].filter(([k])=>k.startsWith('reply_')));
 read();db.replies??={};const rec=db.replies[k]||{};db.replies[k]=publish?{published:values}:{...rec,draft:values};
 write();render();message(publish?'見本の保護者画面に公開しました。':'返信の下書きを保存しました。');};
}
function replySummary(id){const r=db.replies?.[key(id)]?.published;if(!r)return '';
 const fields={reply_nap_time:'お昼寝時間',reply_temperature:'体温',reply_bowel_movement:'排便',reply_appetite:'食欲',reply_message:'連絡メモ'};
 return `<div class="divider"><b>園からの連絡</b>${Object.entries(fields).filter(([k])=>r[k]).map(([k,l])=>`<p>${l}：${esc(r[k])}</p>`).join('')}</div>`;
}
function seed(scenario){
 db=emptyState();$('#scope').value='both';today=firstDay;day=today;actor=firstActor;child=1;
 if (['usual','changed','partial','error'].includes(scenario)) order().usual=copy(candidates);
 if(scenario==='usual'||scenario==='changed'){
  order().days[day]=scenario==='usual'?dayReply('usual',order().usual):dayReply('change',[grandma,...order().usual]);
 }
 if(['usual','changed','partial'].includes(scenario))db.entries[key()]={rev:1,by:actor,at:stamp(),values:{
  contact_type:'present',attendance_mode:'present',dinner_contents:'ごはん、焼き魚',dinner_appetite:scenario==='partial'?'':'旺盛',
  breakfast_contents:scenario==='partial'?'':'トーストとバナナ',breakfast_appetite:scenario==='partial'?'':'普通'}};
 write();$('#settings').open=false;
 const route=scenario==='unregistered'?'usual/1':'daily/1';
 history.replaceState(null,'','#'+route);render();
 if(scenario==='error'){dailyMode='change';rows=[{...grandma,phone:''},...copy(order().usual)];drawEmergency();problem(rowError());}
 else if(route==='daily/1')$('#emergency').scrollIntoView();
}
function saveUsual(){
 const err=rowError();if(err){problem(err);return;}
 const contacts=usualRowsToSave();
 read();if(baseRev!==order().baseRev){problem('いつもの連絡順が更新されました。最新の順番を確認してください。',true);return;}
 order().usual=contacts;order().baseRev++;recordChange('いつもの連絡順',{rows:contacts,by:actor,at:stamp()});write();nav('usual');message(names[child]+'さんの連絡順を保存しました。');
}
document.addEventListener('input',e=>{const field=e.target.closest('[data-prop]');if(field){rows[Number(field.closest('[data-i]').dataset.i)][field.dataset.prop]=field.value;clearFieldProblem();}});
document.addEventListener('change',e=>{
 const field=e.target;
 if(field.id==='scope'||field.id==='staff-role'){render();return;}
 if(field.name==='oral_mode'||field.id==='oral-date'){
  informant=$('#informant').value;
  if(field.name==='oral_mode')oralMode=field.value;
  else if(field.value)day=field.value;
  else return;
  showOral();return;
 }
 if(field.name==='emergency_mode'){dailyMode=field.value;drawEmergency();}
 if(field.matches('.view-date')&&field.value){day=field.value;render();}
});
document.addEventListener('click',e=>{
 const trigger=e.target.closest('button');if(!trigger)return;
 if(trigger.dataset.jump){document.getElementById(trigger.dataset.jump)?.scrollIntoView({block:'start'});return;}
 if(trigger.hasAttribute('data-move')||trigger.hasAttribute('data-remove')){
  const i=Number(trigger.closest('[data-i]').dataset.i);
  if(trigger.hasAttribute('data-remove'))rows.splice(i,1);
  else{const j=i+Number(trigger.dataset.move);[rows[i],rows[j]]=[rows[j],rows[i]];}
  drawRows();return;
 }
 switch(trigger.dataset.act){
 case 'candidate':{const obj=availableContacts(isBaseEditor()).find(r=>r.id===trigger.dataset.id);if(obj){
  const empty=rows.findIndex(r=>!r.label&&!r.phone);if(empty<0)rows.push(copy(obj));else rows[empty]=copy(obj);
 }drawRows();break;}
 case 'use-usual':rows=copy(order().usual);drawRows();break;
 case 'save-oral':saveOral();break;
 case 'add-row':rows.push({id:ids(),label:'',phone:'',only:!isBaseEditor()});drawRows();$$('[data-prop=label]').at(-1)?.focus();break;
 case 'save-usual':saveUsual();break;
 case 'amend':editing=true;dailyMode=order().days[day]?.mode||'';rows=initRowsForDay('change');drawEmergency();break;
 case 'cancel-edit':editing=false;dailyMode='';drawEmergency();break;
 case 'reload':
  if(screen==='daily'&&entryRev===(entry()?.rev||0)){initEditor();editing=!activeReply(day);dailyMode='';rows=initRowsForDay('change');drawEmergency();$('#emergency').scrollIntoView();}
  else render();break;
 }
});
$('#apply-example').addEventListener('click',()=>seed($('#scenario').value));
$('#family-example').addEventListener('change',e=>{
 const url=new URL(location.href);
 url.searchParams.set('family',e.target.value);
 url.hash='usual/'+child;
 location.assign(url);
});
$('#actor').addEventListener('change',e=>{actor=e.target.value;render();});
$('#clock').addEventListener('change',e=>{if(e.target.value){today=e.target.value;day=today;render();}});
$('#closing').addEventListener('change',e=>{
 const field=e.target;
 if(!field.checkValidity()){field.value=closingTime();message('閉園時刻は00:01から23:59の間で選んでください。');return;}
 read();db.mockClosingTime=field.value;write();updatePickupLimit();
});
$('#race').addEventListener('click',()=>{
 read();const other=actor==='母'?'父':'母';
 if(isBaseEditor()){order().usual=order().usual.length>1?copy(order().usual).reverse():copy(candidates);order().baseRev++;}
 else order().days[day]=dayReply('change',[{...grandma,id:'alternate',label:'祖父の携帯',phone:'000-0000-0106'},...order().usual],other);
 write();$('#settings').open=false;message('もう一人の保護者が連絡順を保存しました。');
});
window.addEventListener('hashchange',render);
window.addEventListener('storage',e=>{
 if(e.key!==storeKey)return;
 if(!['daily','pickup','usual','oral'].includes(screen)){render();return;}
 read();$('#closing').value=closingTime();updatePickupLimit();
});
render();

})();

