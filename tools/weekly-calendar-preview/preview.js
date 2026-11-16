'use strict';
(() => {
  const $ = s => document.querySelector(s);
  const $$ = s => [...document.querySelectorAll(s)];
  const clone = x => structuredClone(x);
  const esc = x => String(x ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const classes = [{name:'ことり組（架空）',age:0},{name:'こりす組（架空）',age:2},{name:'ひかり組（架空）',age:5}];
  const dayNames = ['月','火','水','木','金','土','日'];
  const date = s => new Date(`${s}T12:00:00Z`);
  const iso = d => d.toISOString().slice(0,10);
  const add = (s,n) => {const d=date(s);d.setUTCDate(d.getUTCDate()+n);return iso(d);};
  const monday = s => add(s,-((date(s).getUTCDay()+6)%7));
  const short = s => `${Number(s.slice(5,7))}/${Number(s.slice(8,10))}`;
  const range = s => `${short(s)}（月）〜${short(add(s,6))}（日）`;
  const monthLabel = m => `${m.slice(0,4)}年${Number(m.slice(5))}月`;
  const weeks = month => {
    const d=date(`${month}-01`);d.setUTCMonth(d.getUTCMonth()+1);d.setUTCDate(0);
    const end=iso(d), rows=[];for(let start=monday(`${month}-01`);start<=end;start=add(start,7))rows.push(start);
    return rows;
  };
  const toWeek = start => {
    const th=date(add(monday(start),3));const y=th.getUTCFullYear();
    const n=1+Math.round((date(monday(start))-date(monday(`${y}-01-04`)))/604800000);
    return `${y}-W${String(n).padStart(2,'0')}`;
  };
  const fromWeek = w => {
    if(!/^\d{4}-W\d{2}$/.test(w))return null;
    const [y,n]=w.split('-W');const start=add(monday(`${y}-01-04`),(Number(n)-1)*7);
    return toWeek(start)===w?start:null;
  };
  const key = (c,p) => `${c}|${p}`;
  const blank = () => ({aim:'',activity:'',support_preparation:'',reflection:'',days:Array.from({length:6},()=>({activity:'',support:'',preparation:''})),status:'draft',context:{}});
  const combinedSupport = p => p.support_preparation ?? [p.support,p.preparation].filter(Boolean).join('\n');
  const samples = [
    {id:'a',age:0,month:10,title:'秋の風を感じる・布でふれあう',aim:'保育者に見守られ、外気や素材の感触を楽しむ。',activity:'テラスで外気浴をする。柔らかな布でいないいないばあを楽しむ。',support:'一人ひとりの表情や体調に合わせて場所と時間を調整し、声や動きに応える。',preparation:'敷物、柔らかな布、着替え'},
    {id:'b',age:0,month:10,title:'音のする玩具・ゆったりした室内遊び',aim:'好きな音や動きに気づき、手を伸ばして遊ぶ。',activity:'安全な音の出る玩具を手に持つ。マットで体を動かす。',support:'口に入れても安全な大きさと清潔さを確認し、子どもが選ぶ時間を待つ。',preparation:'音の出る玩具、マット'},
    {id:'c',age:2,month:10,title:'落ち葉探し・お店屋さんごっこ',aim:'秋の自然に親しみ、見つけたものを言葉や身振りで伝える。',activity:'園庭で落ち葉を探す。集めた葉を使ってごっこ遊びをする。',support:'見つけた喜びを共有し、友だちとのやりとりを仲立ちする。',preparation:'かご、遊び用の皿、敷物'},
    {id:'d',age:5,month:10,title:'秋の自然探し・共同制作・運動遊び',aim:'友だちと考えを伝え合い、役割を工夫して遊ぶ。',activity:'散歩で見つけた秋を共同制作に取り入れ、体を動かす遊びを楽しむ。',support:'互いの考えを聞く時間を設け、必要な道具を自分たちで選べるようにする。',preparation:'画用紙、のり、かご、コーン',days:['園庭で自然探し','落ち葉の共同制作','散歩で秋を探す','チームで運動遊び','作品を紹介する','合同保育']},
    {id:'e',age:5,month:11,title:'木の実の工作・楽器遊び',aim:'素材の違いを試し、友だちと表現を楽しむ。',activity:'木の実や紙で工作し、楽器の音を合わせる。',support:'道具の使い方を確認し、工夫を言葉にして共有する。',preparation:'工作材料、楽器',days:['素材集め','工作','音探し','合奏','作品の紹介','合同保育']},
  ];
  const samplePlan = sample => ({...blank(),aim:sample.aim,activity:sample.activity,support_preparation:combinedSupport(sample),days:Array.from({length:6},(_,i)=>({activity:sample.days?.[i]||'',support:sample.days?sample.support:'',preparation:sample.days?sample.preparation:''})),source:sample.id});
  const state = {view:'weekly',cls:0,month:'2026-10',year:2026,editing:null,start:'2026-10-12',layout:'infant',dirty:false,weekly:{},monthly:{},monthlyAges:{},working:{}};
  let snapshot=null;
  function seed(){
    window.monthlyPreview.reset();
    state.weekly={};state.monthly={};
    classes.forEach((c,i)=>{
      const sample=samples.find(x=>x.age===c.age);
      ['2026-09-28','2026-10-05','2026-10-12'].forEach((start,j)=>{
        const p=samplePlan(sample);p.status=j<2?'approved':'draft';p.layout=c.age<3?'infant':'older';
        p.context={owner_name:'見本の保育士',age_class:`${c.age}歳児`,current_children_snapshot:'好きな素材を見つけ、保育者や友だちに知らせようとしている。',include_saturday:true};
        if(j===1)p.reflection='関心に合わせて遊ぶ場所を選ぶ姿が見られた。（架空の記録）';
        if(j===2){p.days[0]={activity:'休園（見本）',support:'',preparation:''};p.reflection='';}
        state.weekly[key(i,start)]=p;
      });
      for(const m of ['2026-04','2026-05','2026-06','2026-07','2026-08','2026-09','2026-10'])state.monthly[key(i,m)]={status:m==='2026-10'?'draft':'approved',context:{owner_name:'見本の保育士',current_children_snapshot:'季節の変化に気づき、好きな遊びを楽しんでいる。',play_interests:'自然物に触れる遊び',seasonal_context:'季節に合わせた活動を楽しむ。'}};
    });
  }
  function message(text,error=false){const el=$(error?'#error-message':'#status-message');el.textContent=text;el.hidden=false;if(error)el.focus();}
  function clearMessages(){['#status-message','#error-message'].forEach(s=>$(s).hidden=true);}
  async function confirmChange(text){
    const d=$('#confirm-dialog');$('#confirm-message').textContent=text;d.showModal();$('#confirm-cancel').focus();
    return new Promise(resolve=>{const finish=v=>{d.close();d.oncancel=null;$('#confirm-yes').onclick=null;$('#confirm-cancel').onclick=null;resolve(v);};$('#confirm-yes').onclick=()=>finish(true);$('#confirm-cancel').onclick=()=>finish(false);d.oncancel=e=>{e.preventDefault();finish(false);};});
  }
  const mayLeave = () => !state.dirty || confirmChange('保存していない変更があります。変更を破棄して移動しますか？');
  function pill(status){return `<span class="pill ${status||'empty'}">${({draft:'下書き',approved:'承認済み'})[status]||'未作成'}</span>`;}
  function syncViews(){
    $('#calendar-view').hidden=!!state.editing;$('#weekly-editor').hidden=state.editing!=='weekly';$('#monthly-editor').hidden=state.editing!=='monthly';
    $$('[data-view]').forEach(b=>b.setAttribute('aria-pressed',String(state.view===b.dataset.view&&!state.editing)));
    $('#month-control').hidden=state.view!=='weekly';$('#year-control').hidden=state.view!=='monthly';
    $('#calendar-age-control').hidden=state.view!=='monthly';$('#calendar-age').value=String(state.monthlyAges[state.cls]??classes[state.cls].age);
    $('#calendar-class').value=String(state.cls);$('#calendar-month').value=state.month;$('#calendar-year').value=String(state.year);
  }
  function renderCalendar(){
    syncViews();const c={...classes[state.cls]};if(state.view==='monthly')c.age=state.monthlyAges[state.cls]??c.age;
    $('#calendar-title').textContent=state.view==='weekly'?`${monthLabel(state.month)}の週案`:`${state.year}年度の月案`;
    $('#calendar-description').textContent=`${c.name}・${c.age}歳児 ／ ${state.view==='weekly'?'期間から週案を開きます。':'4月から翌年3月まで。月を選ぶと、その月の計画を開きます。'}`;
    if(state.view==='monthly'){
      $('#calendar-content').innerHTML='<div class="month-grid">'+Array.from({length:12},(_,i)=>{
        const d=new Date(Date.UTC(state.year,3+i,1,12));const m=iso(d).slice(0,7),r=window.monthlyPreview.summary(state.cls+1,m,c.age),approved=r?.status==='承認済み';
        return `<button class="month-card ${m==='2026-10'?'current':''}" type="button" data-month-open="${m}" aria-label="${monthLabel(m)}の月案を${r?'開く':'作成'}"><span class="month-number">${d.getUTCMonth()+1}月</span>${pill(r?(approved?'approved':'draft'):null)}<p>${r?esc(r.sheet.fields['common:goal']?.body||'保存した計画を確認できます。'):'この月の計画はまだありません。'}</p><span class="open-label">${approved?'計画を確認する →':r?'下書きを編集 →':'＋ 月案を作成'}</span></button>`;
      }).join('')+'</div>';return;
    }
    $('#calendar-content').innerHTML=weeks(state.month).map(start=>{
      const p=state.weekly[key(state.cls,start)];
      return `<article class="week-card ${start==='2026-10-05'?'active-week':''}"><div class="week-heading"><strong>${range(start)}</strong>${pill(p?.status)}<button type="button" data-week-open="${start}" aria-label="${range(start)}の週案を${p?'開く':'作成'}">${p?.status==='approved'?'計画を確認':p?'下書きを編集':'＋ 週案を作成'}</button></div><p class="week-aim">ねらい：${esc(p?.aim||'未入力')}</p>${p?.layout==='infant'?`<p class="week-aim">今週の活動：${esc(p.activity||'未入力')}<br><small>週全体の計画です。各日への割り当てはありません。</small></p>`:''}<div class="week-days-scroll" tabindex="0" role="region" aria-label="${range(start)}の活動"><div class="week-days">${dayNames.map((day,i)=>{
        const dayDate=add(start,i);let activity=i===6?'—':p?.layout==='older'?p.days[i]?.activity:'';
        return `<div class="week-day ${dayDate.slice(0,7)!==state.month?'outside':''} ${i===6?'sunday':''} ${dayDate==='2026-10-11'?'today':''}"><strong>${short(dayDate)} ${day}</strong><p>${esc(activity||'—')}</p></div>`;
      }).join('')}</div></div></article>`;
    }).join('');
  }
  function setForm(kind,context){
    const form=$(`#${kind}-form`);form.reset();form.querySelectorAll('[name]').forEach(el=>{
      el.disabled=false;el.removeAttribute('aria-invalid');
      if(el.type==='checkbox')el.checked=!!context[el.name];else el.value=context[el.name]??'';
    });
    form.querySelectorAll('button').forEach(b=>b.disabled=false);
  }
  function context(kind){const result={};$(`#${kind}-form`).querySelectorAll('[name]').forEach(el=>result[el.name]=el.type==='checkbox'?el.checked:el.value);return result;}
  function baseContext(kind,period){return {classroom_ref:classes[state.cls].name,owner_name:'見本の保育士',age_class:`${classes[state.cls].age}歳児`,[kind==='weekly'?'target_week':'target_month']:kind==='weekly'?toWeek(period):period,include_saturday:true};}
  const current = () => state.working[state.start] ||= clone(state.weekly[key(state.cls,state.start)]||blank());
  const weeklyAge = () => Number($('#weekly-form [name=age_class]').value.match(/^([0-5])歳児$/)?.[1] ?? classes[state.cls].age);
  const isApproved = () => state.editing==='monthly'?state.monthlyReadOnly:state.weekly[key(state.cls,state.start)]?.status==='approved';
  function collectPaper(){
    $$('#paper-fields textarea').forEach(el=>{
      const p=state.working[el.dataset.start] ||= blank();
      if(el.dataset.day!==undefined)p.days[Number(el.dataset.day)][el.dataset.field]=el.value;else p[el.dataset.field]=el.value;
    });
  }
  function renderPaper(){
    const p=current(), read=isApproved(), age=weeklyAge();state.layout=age<3?'infant':'older';$('#layout').value=state.layout;
    const check=$('#weekly-form [name=include_saturday]');
    $('#paper-scope').textContent=`${classes[state.cls].name}・${age}歳児 ／ ${state.layout==='infant'?monthLabel(state.month):range(state.start)}${read?' ／ 承認済みの見本・閲覧のみ':''}`;
    $('#paper-format-note').textContent=state.layout==='infant'?'0～2歳：月内の週を一覧にします。期間とねらいは同じ欄、配慮・援助と準備も一つの欄に記入します。':'3～5歳：週のねらい、月～土の活動・援助配慮・準備、週の反省を記入します。';
    $('#week-range').textContent=`選択している週：${range(state.start)}${state.layout==='infant'?'（週全体の計画・曜日別の欄はありません）':check.checked?'（土曜を含む）':'（土曜は非表示・入力内容は保持）'}`;
    const area=(start,field,value,day,locked=false,label='')=>`<textarea ${locked?'disabled':''} aria-label="${esc(label||`${range(start)} ${field}`)}" data-start="${start}" data-field="${field}" ${day!==undefined?`data-day="${day}"`:''} rows="5">${esc(value)}</textarea>`;
    if(state.layout==='infant'){
      $('#paper-fields').innerHTML=`<div class="paper-scroll" tabindex="0" role="region" aria-label="乳児の週別計画"><table class="paper-table infant-paper"><thead><tr><th class="week-cell">週・期間／ねらい</th><th>活動</th><th class="support-cell">配慮・援助すること／準備</th><th>評価・反省</th></tr></thead><tbody>${weeks(state.month).map((start,index)=>{
        const row=state.working[start] ||= clone(state.weekly[key(state.cls,start)]||blank());const locked=read||state.weekly[key(state.cls,start)]?.status==='approved';
        return `<tr class="${start===state.start?'selected-row':''}"><th class="week-cell" scope="row"><strong>第${index+1}週</strong><br>${short(start)}〜${short(add(start,6))}<br>${pill(state.weekly[key(state.cls,start)]?.status)}${start===state.start?'<p>選択中</p>':`<button type="button" data-select-week="${start}">この週を選ぶ</button>`}<label class="week-aim-input">ねらい${area(start,'aim',row.aim,undefined,locked,`${short(start)}週のねらい`)}</label></th><td>${area(start,'activity',row.activity,undefined,locked,`${short(start)}週の活動`)}</td><td>${area(start,'support_preparation',combinedSupport(row),undefined,locked,`${short(start)}週の配慮・援助すること／準備`)}</td><td>${area(start,'reflection',row.reflection,undefined,locked,`${short(start)}週の評価・反省`)}</td></tr>`;
      }).join('')}</tbody></table></div>`;
    }else{
      $('#paper-fields').innerHTML=`<label>今週のねらい${area(state.start,'aim',p.aim,undefined,read,'今週のねらい')}</label><div class="paper-scroll" tabindex="0" role="region" aria-label="幼児の曜日別計画"><table class="paper-table"><thead><tr><th class="date-column">日付・曜日</th><th>子どもの主な活動</th><th>援助・配慮事項</th><th>準備</th></tr></thead><tbody>${p.days.slice(0,check.checked?6:5).map((row,i)=>`<tr><th scope="row">${short(add(state.start,i))}<br>（${dayNames[i]}）</th>${['activity','support','preparation'].map((f,j)=>`<td>${area(state.start,f,row[f],i,read,`${dayNames[i]}曜日 ${['子どもの主な活動','援助・配慮事項','準備'][j]}`)}</td>`).join('')}</tr>`).join('')}</tbody></table></div><label>今週の反省${area(state.start,'reflection',p.reflection,undefined,read,'今週の反省')}</label>`;
    }
  }
  function renderSources(){
    const mode=$('#mock-source').value;const age=$('#search-age').value,month=$('#search-month').value,q=$('#search-keyword').value.trim().toLocaleLowerCase();
    const results=mode==='normal'?samples.filter(s=>(age===''||s.age===Number(age))&&(month===''||s.month===Number(month))&&[s.title,s.aim,s.activity,s.support,s.preparation].some(t=>t.toLocaleLowerCase().includes(q))):[];
    $('#source-count').textContent=mode==='error'?'参考例を読み込めません。入力中の下書きは保持しています。':`参考例 ${results.length}件（すべて架空）`;
    $('#source-list').innerHTML=results.length?results.map(s=>`<details class="source-card"><summary><strong>${esc(s.title)}</strong><small>${s.age}歳児・${s.month}月 ／ 詳細を開く</small></summary><div class="source-detail"><h3>ねらい</h3><p>${esc(s.aim)}</p><table><thead><tr><th>活動</th>${s.age<3?'<th>配慮・援助すること／準備</th>':'<th>援助・配慮事項</th><th>準備</th>'}</tr></thead><tbody>${(s.days||[s.activity]).map((a,i)=>`<tr><td>${s.days?`${dayNames[i]}：`:''}${esc(a)}</td>${s.age<3?`<td>${esc(combinedSupport(s))}</td>`:`<td>${esc(s.support)}</td><td>${esc(s.preparation)}</td>`}</tr>`).join('')}</tbody></table><p class="sample-origin">様式参考：${s.age<3?'乳児の週一覧':'幼児の曜日別計画'}。内容はモック用の創作です。過去の反省・氏名・承認印はコピーしません。</p><button type="button" class="copy-button" data-copy="${s.id}" ${isApproved()?'disabled':''}>この候補を選択中の週へコピー</button></div></details>`).join(''):`<p class="empty-note">${mode==='error'?'読込エラーの見本です。下の帳票には引き続き手入力できます。':'条件に合う参考例がありません。年齢や月を「すべて」にするか、下の帳票へ手入力できます。'}</p>`;
  }
  function markDirty(){state.dirty=true;const el=$(state.editing==='weekly'?'#weekly-status':'#monthly-status');el.textContent='未保存の変更';el.className='pill draft';}
  function lockForm(kind,locked){
    $(`#${kind}-form`).querySelectorAll('[name],button[type=submit],[data-revert]').forEach(el=>el.disabled=locked);
    const status=$(`#${kind}-status`);status.textContent=locked?'承認済み・閲覧のみ':((kind==='weekly'?state.weekly[key(state.cls,state.start)]:state.monthly[key(state.cls,state.editMonth)])?'下書き':'未保存');status.className=`pill ${locked?'approved':'draft'}`;
  }
  function openWeekly(start,scroll=true){
    state.editing='weekly';state.start=start;state.working={};state.dirty=false;clearMessages();
    if(!weeks(state.month).includes(start))state.month=add(start,3).slice(0,7);
    const p=current();state.layout=p.layout||(classes[state.cls].age<3?'infant':'older');
    const connected=window.monthlyPreview.savedForClass(state.cls+1);
    $('#weekly-form [name=parent_document_id]').innerHTML='<option value="">接続しない</option>'+connected.map(c=>`<option value="${c.document_id}">${monthLabel(c.target_month)} 月案・${classes[state.cls].name}・${c.age}歳児</option>`).join('');
    setForm('weekly',{...baseContext('weekly',start),...p.context,target_week:toWeek(start),classroom_ref:classes[state.cls].name});
    $('#search-age').value=String(classes[state.cls].age);$('#search-month').value=String(Number(add(start,3).slice(5,7)));$('#search-keyword').value='';$('#mock-state').value='empty';
    renderPaper();lockForm('weekly',isApproved());renderSources();syncViews();snapshot=clone({working:state.working,context:context('weekly'),layout:state.layout});if(scroll)$('#weekly-editor').scrollIntoView({block:'start'});
  }
  function openMonthly(month){
    state.editing='monthly';state.editMonth=month;state.month=month;state.dirty=false;clearMessages();
    syncViews();window.monthlyPreview.editor.open(window.monthlyPreview.context(state.cls+1,month,state.monthlyAges[state.cls]??classes[state.cls].age));
    $('#monthly-editor').scrollIntoView({block:'start'});
  }
  async function navigate(view){if(!await mayLeave())return;if(state.editing==='monthly')window.monthlyPreview.editor.discard();state.editing=null;state.view=view;state.dirty=false;clearMessages();renderCalendar();$('#calendar-view').scrollIntoView({block:'start'});}
  async function copySample(id){
    if(isApproved())return;collectPaper();const p=current(),s=samples.find(s=>s.id===id);
    const nonempty=p.aim||p.activity||combinedSupport(p)||p.days.some(d=>Object.values(d).some(Boolean));
    if(nonempty&&!await confirmChange('選択中の週の計画欄を、この参考例で置き換えます。対象期間・クラス・作成者・入力した評価反省は保持します。続けますか？'))return;
    const copied=samplePlan(s);Object.assign(p,{aim:copied.aim,activity:copied.activity,support_preparation:copied.support_preparation,days:copied.days,source:id});
    renderPaper();markDirty();message('選択中の週へコピーしました。必要な箇所を書き換えてから保存してください。');$('#plan-paper').scrollIntoView({block:'start'});
  }
  async function simulate(value){
    if(!state.editing)openWeekly('2026-10-19',false);
    if(isApproved()){message('承認済みの見本は閲覧のみです。未作成の週・月を開いて試してください。');return;}
    if(state.dirty&&!await confirmChange('入力状態を切り替えると、保存していない変更を見本データで置き換えます。続けますか？'))return;
    if(state.editing==='monthly'){clearMessages();window.monthlyPreview.editor.simulate(value);return;}
    clearMessages();const kind=state.editing;const period=kind==='weekly'?state.start:state.editMonth;
    const ctx={...baseContext(kind,period),age_class:$('#weekly-form [name=age_class]').value};
    if(value==='partial'||value==='filled')ctx.current_children_snapshot='好きなものを見つけ、保育者に知らせようとしている。（架空）';
    if(value==='filled')Object.assign(ctx,{related_monthly_summary:'季節の自然に触れ、身近な人と楽しさを共有する。',previous_week_reflection:'落ち葉を見つけると指差しで知らせる姿があった。（架空）',weekly_activities_note:'秋の自然に触れる。',seasonal_context:'秋の戸外遊び',family_context:'生活リズムについて家庭と共有する。（架空）',class_notes:'体調に合わせて活動時間を調整する。',related_annual_summary:'身近な人と安心して過ごし、興味を広げる。',previous_reflection:'好きな遊びに繰り返し取り組む姿が見られた。（架空）',play_interests:'自然物・身近な素材'});
    if(value==='error')ctx.owner_name='';setForm(kind,ctx);
    if(kind==='weekly'){
      state.working={};const p=value==='filled'?samplePlan(samples.find(s=>s.age===weeklyAge())||samples.find(s=>(s.age<3)===(weeklyAge()<3))):blank();
      if(value==='partial')p.aim='秋の自然に興味をもつ。';state.working[state.start]=p;renderPaper();renderSources();
    }
    markDirty();if(value==='error')validate(kind);else message(`${({empty:'未入力',partial:'一部入力',filled:'入力済み'})[value]}の見本に切り替えました。`);
  }
  function validate(kind){
    const form=$(`#${kind}-form`),ctx=context(kind),missing=[];
    form.querySelectorAll('[aria-invalid]').forEach(el=>el.removeAttribute('aria-invalid'));
    const required=kind==='weekly'?{target_week:'対象週',classroom_ref:'クラス',age_class:'年齢',owner_name:'作成者'}:{target_month:'対象月',classroom_ref:'クラス',owner_name:'作成者'};
    for(const [field,label]of Object.entries(required))if(!String(ctx[field]||'').trim()){missing.push(label);form.querySelector(`[name=${field}]`).setAttribute('aria-invalid','true');}
    if(kind==='weekly'&&!fromWeek(ctx.target_week)&&!missing.includes('対象週'))missing.push('対象週');
    if(missing.length){message(`${missing.join('・')}を入力してください。入力した内容は残っています。`,true);return false;}
    return true;
  }
  function planHasText(p){return ['aim','activity','support_preparation','reflection'].some(f=>(p[f]||'').trim())||p.days.some(d=>Object.values(d).some(v=>v.trim()));}
  function save(kind){
    if(isApproved()||!validate(kind))return;
    if($('#save-error').checked){message('保存に失敗しました（見本）。入力は保持しています。「保存失敗を試す」を外して、再度保存できます。',true);return;}
    clearMessages();const ctx=context(kind);
    if(kind==='weekly'){
      collectPaper();let savedCount=0;
      Object.entries(state.working).forEach(([start,p])=>{
        if(state.weekly[key(state.cls,start)]?.status==='approved')return;
        if(start!==state.start&&!planHasText(p)&&!state.weekly[key(state.cls,start)])return;
        const next=clone(p);next.status='draft';next.layout=start===state.start?state.layout:(p.layout||state.layout);
        if(start===state.start)next.context=ctx;
        state.weekly[key(state.cls,start)]=next;savedCount++;
      });
      current().context=ctx;snapshot=clone({working:state.working,context:ctx,layout:state.layout});renderPaper();message(`週案${savedCount}件をモック内に保存しました。カレンダーにも反映しています。`);
    }else{state.monthly[key(state.cls,state.editMonth)]={status:'draft',context:ctx};snapshot=clone(ctx);message('月案をモック内に保存しました。カレンダーにも反映しています。');}
    state.dirty=false;lockForm(kind,false);
  }
  async function revert(kind){
    if(!state.dirty||!await confirmChange('保存後の変更を取り消し、最後に保存した内容へ戻しますか？'))return;
    if(kind==='weekly'){state.working=clone(snapshot.working);state.layout=snapshot.layout;setForm(kind,snapshot.context);renderPaper();}else setForm(kind,snapshot);
    state.dirty=false;lockForm(kind,isApproved());clearMessages();message('保存した内容（新規の場合は開いた時点）へ戻しました。');
  }
  $$('[data-view]').forEach(b=>b.addEventListener('click',()=>navigate(b.dataset.view)));
  $('#new-weekly').addEventListener('click',async()=>{if(await mayLeave()){if(state.editing==='monthly')window.monthlyPreview.editor.discard();const starts=weeks(state.month);openWeekly(starts.find(s=>!state.weekly[key(state.cls,s)])||starts[0]);}});
  $('#calendar-content').addEventListener('click',e=>{const w=e.target.closest('[data-week-open]'),m=e.target.closest('[data-month-open]');if(w)openWeekly(w.dataset.weekOpen);if(m)openMonthly(m.dataset.monthOpen);});
  $('#calendar-class').addEventListener('change',e=>{state.cls=Number(e.target.value);renderCalendar();});
  $('#calendar-age').addEventListener('change',e=>{state.monthlyAges[state.cls]=Number(e.target.value);renderCalendar();});
  $('#calendar-month').addEventListener('change',e=>{if(!/^\d{4}-\d{2}$/.test(e.target.value)||!e.target.validity.valid){e.target.value=state.month;return;}state.month=e.target.value;renderCalendar();});
  $('#calendar-year').addEventListener('change',e=>{state.year=Number(e.target.value);renderCalendar();});
  function movePeriod(n){if(state.view==='weekly'){const d=date(`${state.month}-01`);d.setUTCMonth(d.getUTCMonth()+n);state.month=iso(d).slice(0,7);}else{state.year+=n;const s=$('#calendar-year');if(![...s.options].some(x=>Number(x.value)===state.year))s.add(new Option(String(state.year),String(state.year)));}renderCalendar();}
  $('#previous-period').addEventListener('click',()=>movePeriod(-1));$('#next-period').addEventListener('click',()=>movePeriod(1));
  $('#current-period').addEventListener('click',()=>{state.month='2026-10';state.year=2026;renderCalendar();});
  ['weekly'].forEach(kind=>{
    const form=$(`#${kind}-form`);form.addEventListener('submit',e=>{e.preventDefault();save(kind);});
    form.addEventListener('input',e=>{if(e.target.matches('textarea,[name]')&&!isApproved())markDirty();});
    form.querySelector('[data-cancel]').addEventListener('click',()=>navigate(kind));
    form.querySelector('[data-revert]').addEventListener('click',()=>revert(kind));
    form.querySelector('[name=classroom_ref]').addEventListener('change',async e=>{
      const next=classes.findIndex(c=>c.name===e.target.value);e.target.value=classes[state.cls].name;
      if(next<0||!await mayLeave())return;state.cls=next;if(kind==='weekly')openWeekly(state.start,false);else openMonthly(state.editMonth);
    });
    form.querySelector(`[name=${kind==='weekly'?'target_week':'target_month'}]`).addEventListener('change',async e=>{
      const next=kind==='weekly'?fromWeek(e.target.value):e.target.value;
      if(!next){markDirty();return;}e.target.value=kind==='weekly'?toWeek(state.start):state.editMonth;
      if(!await mayLeave())return;if(kind==='weekly')openWeekly(next,false);else openMonthly(next);
    });
  });
  $('#weekly-form [name=include_saturday]').addEventListener('change',()=>{collectPaper();renderPaper();markDirty();});
  $('#weekly-form [name=age_class]').addEventListener('change',()=>{collectPaper();renderPaper();$('#search-age').value=String(weeklyAge());renderSources();markDirty();message('年齢に合わせて帳票を切り替えました。乳児用と幼児用の入力内容はそれぞれ保持しています。');});
  $('#paper-fields').addEventListener('click',async e=>{const b=e.target.closest('[data-select-week]');if(b&&await mayLeave())openWeekly(b.dataset.selectWeek,false);});
  $('#source-list').addEventListener('click',e=>{const b=e.target.closest('[data-copy]');if(b)copySample(b.dataset.copy);});
  ['#search-age','#search-month','#mock-source'].forEach(s=>$(s).addEventListener('change',renderSources));$('#search-keyword').addEventListener('input',renderSources);
  $('#mock-state').addEventListener('change',e=>simulate(e.target.value));
  $('#monthly-back').addEventListener('click',()=>navigate('monthly'));
  $('#mock-source').addEventListener('change',()=>{if(state.editing==='monthly')window.monthlyPreview.editor.refreshCandidates();});
  window.monthlyPreview.onStatus=(context,dirty)=>{
    if(state.editing!=='monthly')return;
    state.cls=context.classroom_id-1;state.editMonth=context.target_month;state.month=context.target_month;state.monthlyReadOnly=!context.editable;state.dirty=dirty;
    state.monthlyAges[state.cls]=context.age;
    state.year=Number(context.target_month.slice(0,4))-(Number(context.target_month.slice(5))<4?1:0);
    const select=$('#calendar-year');if(![...select.options].some(x=>Number(x.value)===state.year))select.add(new Option(String(state.year),String(state.year)));
    $('#monthly-status').textContent=dirty?'未保存の変更':context.status;$('#monthly-status').className=`pill ${context.editable?'draft':'approved'}`;
  };
  $('#reset-all').addEventListener('click',async()=>{if(!await confirmChange('モック内の保存済み・未保存の入力をすべて消し、最初の架空データへ戻しますか？'))return;seed();window.monthlyPreview.editor.discard();Object.assign(state,{view:'weekly',cls:0,month:'2026-10',year:2026,editing:null,dirty:false,monthlyAges:{}});$('#mock-state').value='empty';$('#mock-source').value='normal';$('#save-error').checked=false;clearMessages();renderCalendar();});
  window.addEventListener('beforeunload',e=>{if(state.dirty){e.preventDefault();e.returnValue='';}});
  seed();if(location.hash==='#monthly')state.view='monthly';renderCalendar();
})();
