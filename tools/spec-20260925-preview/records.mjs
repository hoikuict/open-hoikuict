import { TODAY } from './model.mjs';

export const ACTORS = { hana: { name:'見本 はなこ', admin:false }, taro: { name:'見本 たろう', admin:false }, admin: { name:'見本 さくら', admin:true } };
const categories = ['日常の姿','成長・変化','興味・遊び','友達との関わり','生活習慣','健康・発達','家庭との共有','保育者の援助と反応','配慮事項','引継ぎ事項'];
const perspectives = ['健やかに伸び伸びと育つ','身近な人と気持ちが通じ合う','身近なものと関わり感性が育つ','健康','人間関係','環境','言葉','表現'];
const textFields = {child_state:'子どもの姿',caregiver_support:'保育者の関わり',reflection:'気付き・振り返り',next_focus:'次に意識したいこと',family_note:'家庭との共有・連携'};
const descriptions = { child_state:'解釈だけでなく、言葉や行動などの具体的な姿を記録します。', caregiver_support:'行った援助や環境の工夫、そのときの反応を記録します。',reflection:'記録から読み取れる育ちや気付きを記録します。',next_focus:'次に見守りたい姿や試したい関わりを記録します。',family_note:'家庭から得た情報や共有したい内容を必要な範囲で記録します。' };
const blank = () => ({observed_on:TODAY,...Object.fromEntries(Object.keys(textFields).map(k=>[k,''])),categories:[],perspective_tags:[],sensitivity:'normal',visibility:'private',recipients:['admin'],custom_note:'',correction_reason:''});
const clone = value => JSON.parse(JSON.stringify(value));
const sample = () => ({...blank(),child_state:'積み木を何度も積み直し、崩れると「もう一回」と言って友だちと笑い合っていた。',caregiver_support:'安定する積み方を隣で一緒に試した。',reflection:'崩れた後も、自分で工夫を続けていた。',next_focus:'組み合わせや高さの違いを楽しめるようにする。',family_note:'お迎えの際に遊びの様子を共有した。',categories:['日常の姿','興味・遊び'],perspective_tags:['環境','表現']});

export function createRecords({esc,button,head,errorBlock,openDialog,closeDialog,toast,render,navigate,childById,getScenario}) {
  let actor='hana', custom=false, activeChild=1, editing=null, draft=null, initial='', formError='', filter='all', category='', pending=null;
  let logs=[], nextId=10;
  const me=()=>ACTORS[actor];
  const scope=r=>r.sensitivity==='restricted'?'限定共有':r.visibility==='private'?'自分だけ':'みんなで共有';
  const visible=r=>r.visibility==='private' ? r.author===actor : r.sensitivity==='restricted' ? r.author===actor || r.recipients.includes(actor) || me().admin : true;
  const editable=r=>visible(r) && !r.voided && (r.author===actor || me().admin && r.visibility!=='private');
  function reset() {
    logs=[
      {...sample(),id:1,child:1,author:'hana',created:'2026/09/25 09:10',visibility:'private',history:[]},
      {...sample(),id:2,child:1,author:'taro',created:'2026/09/25 08:50',visibility:'shared',child_state:'園庭で落ち葉を拾い、色の違いを友だちに伝えていた。',history:[]},
      {...blank(),id:3,child:1,author:'admin',created:'2026/09/24 16:30',visibility:'shared',sensitivity:'restricted',recipients:['admin'],child_state:'関係機関との連絡記録（架空）。次回の面談日を確認した。',categories:['配慮事項'],history:[]},
      {...blank(),id:4,child:1,author:'taro',created:'2026/09/25 09:00',child_state:'別の職員の個人メモ（架空）。明日の活動で使う素材を確認する。',history:[]}
    ];nextId=10; draft=null;editing=null;filter='all';category='';formError='';
  }
  reset();
  function enter(child, editId=null) {
    activeChild=child;editing=editId?Number(editId):null;formError='';
    if(editing){const record=logs.find(r=>r.id===editing&&r.child===child);draft=record&&editable(record)?{...clone(record),correction_reason:''}:null;}
    else draft=preset(getScenario());
    initial=JSON.stringify(draft);
  }
  function preset(state){return state==='filled'||state==='error'?sample():state==='partial'?{...blank(),child_state:'園庭で見つけた落ち葉を友だちに見せていた。'}:blank();}
  function dirty(){return !!draft&&initial!==JSON.stringify(draft);}
  function setScenario(state,wasError){if(!wasError&&draft&&!editing){draft=preset(state);initial=JSON.stringify(draft);}formError='';}
  function switchActor(value){actor=value;draft=null;editing=null;initial='';formError='';filter='all';}
  function capture(){const form=document.getElementById('record-form');if(!form||!draft)return;const values=new FormData(form);for(const k of ['observed_on',...Object.keys(textFields),'custom_note','correction_reason'])if(values.has(k))draft[k]=values.get(k);draft.categories=values.getAll('categories');draft.perspective_tags=values.getAll('perspective_tags');if(values.has('visibility'))draft.visibility=values.get('visibility');if(me().admin){draft.sensitivity=values.get('sensitivity')||draft.sensitivity;if(draft.sensitivity==='restricted'){draft.visibility='shared';draft.recipients=values.getAll('recipients');}}}
  function labels(list,name,selected){return `<div class="record-tags">${list.map(x=>`<label><input type="checkbox" name="${name}" value="${esc(x)}" ${selected.includes(x)?'checked':''}>${esc(x)}</label>`).join('')}</div>`;}
  function formPage(){
    const c=childById(activeChild);
    if(!draft)return `${head('この記録は編集できません','現在の職員が閲覧・訂正できる記録を選んでください。')}<a href="#records/${c.id}">記録一覧へ戻る</a>`;
    const restricted=draft.sensitivity==='restricted';
    return `<div class="narrow">${head(editing?'子どもの記録を訂正':'子どもの記録を追加',`${c.classroom} / ${c.name} · 具体的に見えた姿を中心に記録します。`,`<a href="#records/${c.id}">記録一覧へ</a>`)}
      <form id="record-form" class="record-form" novalidate>
      <section class="card"><fieldset><legend>公開範囲</legend>${restricted?'<p class="badge amber">限定共有</p>':`<div class="sharing-radios"><label><input type="radio" name="visibility" value="private" ${draft.visibility==='private'?'checked':''}>自分だけ</label><label><input type="radio" name="visibility" value="shared" ${draft.visibility==='shared'?'checked':''}>みんなで共有</label></div>`}
      <p class="sharing-summary">${restricted?'管理者が指定した職員と、作成者・管理者が閲覧できます。':draft.visibility==='private'?'書いた本人だけが閲覧できます。':'職員全員が閲覧できます。保護者への公開はありません。'}</p></fieldset></section>
      <section class="card"><div class="field-grid">
      <label class="field"><span>観察日・出来事の日 <span class="required">必須</span></span><input type="date" name="observed_on" value="${esc(draft.observed_on)}" required><small class="field-help">実際に子どもの姿を見た日を記録します。</small></label>
      ${Object.entries(textFields).map(([key,label])=>`<label class="field ${key==='child_state'?'span-two':''}"><span>${label}${key==='child_state'?'<span class="required">必須</span>':''}</span><textarea name="${key}" rows="${key==='child_state'?6:4}" maxlength="5000" ${key==='child_state'?'required':''}>${esc(draft[key])}</textarea><small class="field-help">${descriptions[key]}</small></label>`).join('')}
      <fieldset class="span-two"><legend>記録区分</legend>${labels(categories,'categories',draft.categories)}</fieldset>
      <fieldset class="span-two"><legend>領域・視点</legend>${labels(perspectives,'perspective_tags',draft.perspective_tags)}</fieldset>
      ${me().admin?`<label class="field span-two"><span>取扱区分</span><select name="sensitivity"><option value="normal" ${!restricted?'selected':''}>通常</option><option value="restricted" ${restricted?'selected':''}>取扱注意（共有先を指定）</option></select></label>${restricted?`<fieldset class="span-two"><legend>共有先を指定</legend><p class="field-help">作成者・管理者は閲覧できます。追加で閲覧できる職員を選びます。</p><div class="record-tags mt">${Object.entries(ACTORS).filter(([id,a])=>!a.admin).map(([id,a])=>`<label><input type="checkbox" name="recipients" value="${id}" ${draft.recipients.includes(id)?'checked':''}>${a.name}</label>`).join('')}</div></fieldset>`:''}`:restricted?'<p class="field-help span-two">共有先は管理者が設定しています。</p>':''}
      ${custom?`<label class="field span-two"><span>園で大切にしている視点</span><textarea name="custom_note" rows="3" maxlength="5000">${esc(draft.custom_note)}</textarea></label>`:''}
      </div></section>
      ${editing?`<section class="card"><label class="field"><span>訂正理由 <span class="required">必須</span></span><textarea name="correction_reason" rows="2" maxlength="500" required>${esc(draft.correction_reason)}</textarea></label><p class="field-help mt">保存前の内容は訂正履歴に残ります。</p></section>`:''}
      <div id="record-error" role="alert">${errorBlock(formError)}</div>
      <div class="row between"><a href="#records/${c.id}">キャンセル</a>${button(editing?'訂正を保存':'記録を保存','memo-save','','primary')}</div>
      </form>
      ${editing?`<section class="card mt"><h2>誤登録として無効化</h2><p class="small muted mt">記録は削除せず、無効化理由とともに保持します。</p><label class="field mt"><span>無効化理由</span><input id="void-reason" maxlength="500" placeholder="無効化理由"></label>${button('無効化する','memo-void','','mt')}<div id="void-error" role="alert"></div></section>`:''}
      </div>`;
  }
  function listPage(child){
    activeChild=child;const c=childById(child);
    const items=logs.filter(r=>r.child===child&&visible(r)&&(!category||r.categories.includes(category))&&(filter==='all'||filter==='private'&&r.visibility==='private'||filter==='shared'&&r.visibility==='shared'&&r.sensitivity==='normal'||filter==='restricted'&&r.sensitivity==='restricted')).slice().reverse();
    return `<div class="narrow">${head(`${c.name}の記録`,`${c.classroom} · 日々の姿を追記し、時系列で振り返ります。`,`<div class="row"><a href="#roster">名前一覧へ</a><a class="button-link" href="#memo/${c.id}">記録を追加</a></div>`)}
    <div class="toolbar"><label>記録区分<select id="memo-category"><option value="">すべて</option>${categories.map(x=>`<option ${category===x?'selected':''}>${x}</option>`).join('')}</select></label><div class="record-filter" role="group" aria-label="記録の公開範囲">${Object.entries({all:'すべて',private:'自分だけ',shared:'みんなで共有',restricted:'限定共有'}).map(([v,label])=>button(label,'memo-filter',`data-value="${v}" aria-pressed="${filter===v}"`)).join('')}</div></div>
    <div class="record-list">${items.map(r=>`<article class="card" data-record-id="${r.id}"><div class="record-head"><div><strong>${r.observed_on}</strong> <span class="badge ${r.sensitivity==='restricted'?'amber':r.visibility==='shared'?'green':''}">${scope(r)}</span>${r.voided?'<span class="badge red">無効</span>':''}<p class="meta">${ACTORS[r.author].name}・${c.classroom} / ${r.created}</p></div>${editable(r)?`<a href="#editmemo/${c.id}/${r.id}">訂正</a>`:''}</div>
    <div class="record-tags">${r.categories.map(x=>`<span class="badge indigo">${esc(x)}</span>`).join('')}</div><div class="record-body">${esc(r.child_state)}</div>
    ${Object.keys(textFields).slice(1).some(k=>r[k])||r.custom_note?`<details><summary>関わり・振り返りを見る</summary><dl>${Object.entries(textFields).slice(1).filter(([k])=>r[k]).map(([k,l])=>`<div><dt>${l}</dt><dd>${esc(r[k])}</dd></div>`).join('')}${r.custom_note?`<div><dt>園で大切にしている視点</dt><dd>${esc(r.custom_note)}</dd></div>`:''}</dl></details>`:''}
    ${r.perspective_tags.length?`<p class="small mt">領域・視点：${r.perspective_tags.map(esc).join('、')}</p>`:''}
    ${r.sensitivity==='restricted'?`<p class="small muted mt">共有先：${[...new Set([r.author,'admin',...r.recipients])].map(id=>ACTORS[id].name).join('、')}</p>`:''}
    ${r.history.length?`<details class="record-revision mt"><summary>訂正・無効化の履歴（${r.history.length}件）</summary>${r.history.slice().reverse().map(h=>`<p class="small mt">${esc(h.time)} / ${esc(h.actor)} / ${esc(h.action)}<br>理由：${esc(h.reason)}<br>変更前：${esc(h.previous.child_state)}<br>変更前の公開範囲：${scope(h.previous)}</p>`).join('')}</details>`:''}
    </article>`).join('')||'<div class="card empty">表示できる記録はありません。「記録を追加」から記録できます。</div>'}</div></div>`;
  }
  function showError(message){formError=message;document.getElementById('record-error').innerHTML=errorBlock(message);document.getElementById('record-error').scrollIntoView({block:'center'});}
  function save(){capture();if(!draft)return false;if(!draft.observed_on||!draft.child_state.trim()){showError('観察日・出来事の日と、子どもの姿を入力してください。');return false;}if(editing&&!draft.correction_reason.trim()){showError('訂正理由を入力してください。');return false;}if(getScenario()==='error'){showError('保存できませんでした。入力内容は残っています。試用設定でエラーを解除し、もう一度保存してください。');return false;}
    const now=new Date().toLocaleString('ja-JP');
    if(editing){const i=logs.findIndex(r=>r.id===editing);if(i<0||!editable(logs[i]))return false;const old=clone(logs[i]);logs[i]={...clone(draft),history:[...old.history,{actor:me().name,time:now,action:'訂正',reason:draft.correction_reason,previous:old}]};}
    else logs.push({...clone(draft),id:nextId++,child:activeChild,author:actor,created:now,history:[]});
    initial=JSON.stringify(draft);toast('記録を保存しました（このタブ内のみ）。');navigate(`#records/${activeChild}`);return true;
  }
  function guard(target){if(!dirty())return false;pending=target;openDialog('保存していない記録があります','<p>入力を続けるか、変更を破棄して移動してください。</p>',button('入力を続ける','close-dialog')+button('破棄して移動','memo-discard'));return true;}
  function action(name,el){if(!name.startsWith('memo-'))return false;
    if(name==='memo-save')save();
    if(name==='memo-filter'){filter=el.dataset.value;render();}
    if(name==='memo-discard'){draft=null;initial='';closeDialog();const target=pending;pending=null;navigate(target);}
    if(name==='memo-void'){capture();const reason=document.getElementById('void-reason').value.trim();if(!reason){document.getElementById('void-error').innerHTML=errorBlock('無効化理由を入力してください。');return true;}openDialog('この記録を無効化しますか',`<p>理由：${esc(reason)}</p><p>記録と理由は履歴に残ります。</p><div id="modal-error" role="alert"></div>`,button('戻る','close-dialog')+button('無効化する','memo-confirm-void',`data-reason="${esc(reason)}"`));}
    if(name==='memo-confirm-void'){if(getScenario()==='error'){document.getElementById('modal-error').innerHTML=errorBlock('保存できませんでした。理由を保持しています。');return true;}const r=logs.find(x=>x.id===editing);if(!r||!editable(r))return true;const old=clone(r);r.history.push({actor:me().name,time:new Date().toLocaleString('ja-JP'),action:'無効化',reason:el.dataset.reason,previous:old});r.voided=true;draft=null;initial='';closeDialog();navigate(`#records/${activeChild}`);toast('記録を無効化しました（このタブ内のみ）。');}
    return true;
  }
  function change(el){if(el.id==='memo-category'){category=el.value;render();return true;}if(el.closest('#record-form')){capture();if(['visibility','sensitivity'].includes(el.name))render();return true;}return false;}
  return {listPage,formPage,enter,dirty,guard,action,change,capture,reset,setScenario,switchActor,actorName:()=>me().name,setCustom:value=>{custom=value;},getActor:()=>actor};
}
