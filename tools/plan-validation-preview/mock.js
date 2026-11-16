(() => {
  'use strict';
  const q = s => document.querySelector(s), form = q('#daily-draft'), rows = q('#daily-timeline-rows');
  const field = name => form.querySelector(`[name="${name}"]`), feedback = q('#save-feedback');
  const examples = JSON.parse(q('#example-data').textContent);
  let attempted = false, failNext = false, lastErrors = [];
  const names = ['target_date','age_class'];
  for (const name of names) {
    field(name).id = `draft-${name}`;
    const note = document.createElement('span'); note.className = 'field-error'; note.id = `error-${name}`;
    field(name).after(note); field(name).setAttribute('aria-describedby', note.id);
  }
  const timelineNote = document.createElement('p'); timelineNote.className = 'field-error'; timelineNote.id = 'error-timeline';
  rows.closest('.daily-plan-grid-scroll').after(timelineNote);
  rows.closest('.daily-plan-grid-scroll').setAttribute('aria-describedby', 'error-timeline');
  const timelineNames = ['timeline_time','timeline_activity','timeline_children','timeline_support','timeline_considerations'];
  function appendRow(values = {}) {
    const row = q('#daily-row-template').content.firstElementChild.cloneNode(true);
    row.querySelector('[name=timeline_row_key]').value = `mock_${Date.now()}_${rows.children.length}`;
    Object.entries(values).forEach(([name,value]) => {row.querySelector(`[name="${name}"]`).value = value;}); rows.append(row);
  }
  function errors() {
    const result = [];
    if (!field('target_date').value || !field('target_date').validity.valid) result.push(['target_date','対象日を選択してください。']);
    if (!field('age_class').value) result.push(['age_class','年齢を選択してください。']);
    if (![...rows.querySelectorAll('input,textarea')].some(e => timelineNames.includes(e.name) && e.value.trim())) result.push(['timeline','1日の流れを1行以上入力してください。']);
    return result;
  }
  function target(key) {return key === 'timeline' ? rows.querySelector('[name=timeline_time]') : field(key);}
  function mark(list) {
    for (const name of names) {
      field(name).removeAttribute('aria-invalid'); q(`#error-${name}`).textContent = '';
    }
    rows.closest('.daily-plan-grid-scroll').removeAttribute('aria-invalid'); timelineNote.textContent = '';
    list.forEach(([key,text]) => {q(`#error-${key}`).textContent = text; (key==='timeline'?rows.closest('.daily-plan-grid-scroll'):target(key))?.setAttribute('aria-invalid','true');});
  }
  function report(list, focus = false) {
    lastErrors = list; mark(list); feedback.replaceChildren(); feedback.hidden = false;
    feedback.dataset.kind = list.length ? 'error' : 'status'; feedback.setAttribute('role',list.length ? 'alert' : 'status');
    const title = document.createElement('strong'); title.textContent = list.length ? `まだ保存できません（記入漏れ ${list.length}件）` : '記入漏れは解消しました。'; feedback.append(title);
    const hint = document.createElement('p'); hint.textContent = list.length ? '入力内容は残っています。項目名を押すと記入欄へ移動できます。' : '内容を確認して、もう一度「下書きを保存」を押してください。'; feedback.append(hint);
    if (list.length) {const ul = document.createElement('ul'); list.forEach(([key,text]) => {const li=document.createElement('li'),a=document.createElement('a');a.href=`#${key==='timeline'?'daily-timeline-rows':`draft-${key}`}`;a.dataset.field=key;a.textContent=text;li.append(a);ul.append(li);});feedback.append(ul);}
    if (focus) {feedback.focus({preventScroll:true});feedback.parentElement.scrollIntoView({block:'end'});}
  }
  feedback.addEventListener('click',e => {const a=e.target.closest('[data-field]');if(!a)return;e.preventDefault();const input=target(a.dataset.field);input?.focus();input?.scrollIntoView({block:'center'});});
  function refresh() {if(!attempted)return;const next=errors();if(JSON.stringify(next)!==JSON.stringify(lastErrors))report(next);}
  form.addEventListener('input',refresh);form.addEventListener('change',refresh);
  new MutationObserver(refresh).observe(rows,{childList:true});
  function showEditor() {q('#editor').hidden=false;q('#saved').hidden=true;q('#left').hidden=true;}
  function reset() {
    showEditor();form.reset();rows.replaceChildren();attempted=false;lastErrors=[];feedback.hidden=true;mark([]);
    const state=q('#scenario').value; failNext=state==='error';
    field('target_date').value=state==='empty'?'':'2026-11-16';field('age_class').value=['filled','error'].includes(state)?'2歳児':'';
    field('daily_aims').value=state==='empty'?'':'秋の自然に親しみ、自分の発見を楽しむ。';field('daily_content').value=['filled','error'].includes(state)?'園庭で落ち葉の色や形を見つける。':'';
    const count=['filled','error'].includes(state)?8:3;
    for(let i=0;i<count;i++)appendRow(['filled','error'].includes(state)?{timeline_time:`${9+i}:00`,timeline_children:'好きな遊びを楽しむ。',timeline_support:'一人ひとりの思いを受け止める。',timeline_considerations:'安全と体調に配慮する。'}:{});
    q('#daily-example-feedback').hidden=true;
  }
  q('#scenario').addEventListener('change',reset);q('#reset').addEventListener('click',reset);
  q('#try-save').addEventListener('click',()=>{showEditor();form.querySelector('button[type=submit]').focus();});
  form.addEventListener('submit',e=>{
    e.preventDefault();attempted=true;const list=errors();if(list.length){report(list,true);return;}
    mark([]);lastErrors=[];
    if(failNext){failNext=false;feedback.hidden=false;feedback.dataset.kind='error';feedback.setAttribute('role','alert');feedback.textContent='保存できませんでした（確認用の通信エラー）。入力内容は残っています。もう一度「下書きを保存」を押してください。';feedback.focus({preventScroll:true});feedback.parentElement.scrollIntoView({block:'end'});return;}
    const dl=q('#saved-values');dl.replaceChildren();
    function line(label,value){const dt=document.createElement('dt'),dd=document.createElement('dd');dt.textContent=label;dd.textContent=value||'未入力';dl.append(dt,dd);}
    [['target_date','対象日'],['classroom_ref','クラス'],['age_class','年齢'],['owner_name','作成者'],['daily_aims','ねらい'],['daily_content','内容']].forEach(([name,label])=>line(label,field(name).value));
    [...rows.children].forEach((row,i)=>line(`1日の流れ ${i+1}行目`,['timeline_time','timeline_children','timeline_support','timeline_considerations'].map((name,j)=>`${['時間','子どもの様子','保育士の援助','配慮事項'][j]}：${row.querySelector(`[name=${name}]`).value||'未入力'}`).join('\n')));
    q('#editor').hidden=true;q('#saved').hidden=false;q('#saved h1').focus();
  });
  q('#edit').addEventListener('click',()=>{showEditor();attempted=false;feedback.hidden=true;field('target_date').focus();});
  q('#mock-back').addEventListener('click',e=>{e.preventDefault();q('#leave-choice').showModal();});
  q('#keep-editing').onclick=()=>q('#leave-choice').close();
  q('#discard').onclick=()=>{q('#leave-choice').close();reset();q('#editor').hidden=true;q('#left').hidden=false;};
  q('#resume').onclick=()=>{showEditor();field('target_date').focus();};
  q('#mock-search').addEventListener('submit',e=>{e.preventDefault();const search=e.target;const match=examples.filter(x=>(!search.elements.age_class.value||search.elements.age_class.value===x.age_class)&&(!search.elements.month.value||Number(search.elements.month.value)===x.month)&&(!search.elements.q.value||JSON.stringify(x).includes(search.elements.q.value)));document.querySelectorAll('.daily-example-card').forEach(card=>card.hidden=!match.length);q('.daily-example-list-heading strong').textContent=`主な活動 ${match.length}件`;});
  q('.daily-example-panel').addEventListener('click',async e=>{
    const a=e.target.closest('[data-copy]');if(!a)return;e.preventDefault();const example=examples.find(x=>x.id===a.dataset.copy);let mode='replace';
    if(field('age_class').value||field('daily_aims').value.trim()||field('daily_content').value.trim()||!errors().some(x=>x[0]==='timeline')){
      const dialog=q('#daily-copy-choice');q('#daily-copy-example').textContent=`選んだ文例は「${example.main_activity}」（${example.age_class}）です。`;dialog.returnValue='';dialog.showModal();mode=await new Promise(resolve=>dialog.addEventListener('close',()=>resolve(dialog.returnValue),{once:true}));if(!['append','replace'].includes(mode))return;
    }
    if(mode==='replace'){field('age_class').value=example.age_class;rows.replaceChildren();}
    for(const [name,text] of [['daily_aims',example.aims.join('\n')],['daily_content',example.content]])field(name).value=mode==='append'&&field(name).value.trim()?field(name).value+'\n'+text:text;
    if(mode==='append'&&errors().some(x=>x[0]==='timeline'))rows.replaceChildren();
    example.activity_blocks.forEach(x=>appendRow({timeline_time:x.time_and_activity,timeline_children:x.child_state,timeline_support:x.support,timeline_considerations:x.considerations}));
    const note=q('#daily-example-feedback');note.hidden=false;note.textContent='文例を反映しました。内容を確かめて「下書きを保存」を押してください。';refresh();field('daily_aims').focus();
  });
  reset();
})();
