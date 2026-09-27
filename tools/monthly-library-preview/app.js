'use strict';
// Fictional fixtures only. No fetch, storage, production endpoints, or AI calls.
const sections = window.PREVIEW_SECTIONS;
const $ = id => document.getElementById(id);
const escapeHtml = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const el = (tag, text, className) => { const node = document.createElement(tag); node.textContent = text; if (className) node.className = className; return node; };
const state = {age:'',month:'',category:'all',keyword:'',mode:'original',selected:new Map(),ai:[],draft:null,saved:null,error:false,none:false};
let confirmResolve = null;
function askConfirm(message) {
  $('confirm-message').textContent=message;
  $('confirm-dialog').showModal();
  return new Promise(resolve=>{confirmResolve=resolve;});
}
function finishConfirm(answer) { $('confirm-dialog').close(); const resolve=confirmResolve;confirmResolve=null;if(resolve)resolve(answer); }
$('confirm-no').onclick=()=>finishConfirm(false);
$('confirm-yes').onclick=()=>finishConfirm(true);
$('confirm-dialog').addEventListener('cancel',event=>{event.preventDefault();finishConfirm(false);});
const months = [4,5,6,7,8,9,10,11,12,1,2,3];
months.forEach(m => $('month').add(new Option(`${m}月`, m)));
sections.forEach(s => $('category').add(new Option(s.title, s.key)));

function seasonal(month) {
  if ([3,4,5].includes(Number(month))) return {thing:'草花',action:'春の草花を見つける',food:'春の野菜',event:'春の散歩',weather:'気温の変化'};
  if ([6,7,8].includes(Number(month))) return {thing:'水',action:'水や砂の感触を楽しむ',food:'夏の野菜',event:'水に親しむ遊び',weather:'暑さや汗のかき方'};
  if ([9,10,11].includes(Number(month))) return {thing:'落ち葉',action:'色や形の違う落ち葉を集める',food:'秋の野菜',event:'秋の散歩',weather:'朝夕と日中の気温差'};
  return {thing:'冬の自然',action:'冬の自然の変化に気づく',food:'冬の野菜',event:'冬の散歩',weather:'寒さや空気の乾燥'};
}
function examplesFor(age, month) {
  if (age === '' || !month) return [];
  const season = seasonal(month);
  const partner = Number(age) < 2 ? '保育者と一緒に' : Number(age) < 4 ? '保育者や友だちと一緒に' : '友だちと思いを伝え合いながら';
  const subject = Number(age) < 2 ? `${season.thing}を見たり、保育者の声に反応したりする` : `${season.thing}を見つけて友だちや保育者に知らせる`;
  const body = {
    monthly_goal:[`${partner}、${season.thing}に親しみ、気づいたことや心地よさを表情や言葉で伝える。`,`${partner}安心して過ごし、身近な環境の中で好きな遊びを見つける。`],
    children_snapshot:[`${subject}姿が見られる。`,`${partner}遊ぶ中で、興味のあるものに手を伸ばしたり、自分から関わったりしている。`],
    monthly_environment:[`${season.thing}に親しめる場所を用意し、子どもが手にするものの大きさや状態を確かめる。`,`${season.action}遊びを続けられるよう、素材を置く場所と落ち着いて過ごす場所を整える。`],
    monthly_support:[`${partner}${season.action}。一人ひとりの表情や言葉を受け止め、楽しさを共有する。`,`子どもの発見を言葉にして伝え、それぞれのペースで好きな遊びを続けられるようにする。`],
    monthly_health_safety:[`${season.weather}に留意し、活動と休息のバランスや衣服を調整する。`,`散歩先や園庭の状態を確認し、一人ひとりの体調に合わせて活動する。`],
    monthly_food_education:[`${season.food}を見たりにおいを感じたりしながら、身近な食材に親しむ。`,`食事の様子を受け止め、それぞれのペースで食べる心地よさを感じられるようにする。`],
    monthly_events:[`${season.event}を通して、いつもの生活の中で季節に触れる。`,`行事の前後も生活リズムを大切にし、無理のない予定で過ごす。`],
    monthly_10_perspectives:[`身近な自然への気づきや、保育者・友だちとの関わりを長期的な育ちの記録として捉える。`,`思いや気づきを表す姿を受け止め、日々の遊びのつながりを記録する。`],
    monthly_family_collaboration:[`${season.thing}への興味や園で楽しんだ遊びを家庭に伝え、家庭での様子も共有する。`,`${season.weather}に合わせた衣服や生活の様子を家庭と伝え合う。`],
    monthly_reflection_viewpoint:[`${season.thing}に親しむ中で、何に心を動かし、どのように思いを表していたか振り返る。`,`一人ひとりが安心して遊べる環境と、興味に応じた関わりを用意できたか振り返る。`],
  };
  return sections.flatMap((section, sectionIndex) => body[section.key].map((text, index) => ({
    id:`original-${age}-${month}-${section.key}-${index}`,key:section.key,title:section.title,
    item:section.items[Math.min(index,section.items.length-1)],age,month,kind:'original',text,
    file:`【架空】${2025-index}年度_${age}歳児_${String(month).padStart(2,'0')}月_月案.xlsx`,
    location:`シート「月案」 / B${8+sectionIndex*3+index}`,year:2025-index,
  })));
}
function filteredSources() {
  return examplesFor(state.age,state.month).filter(c =>
    (state.category==='all' || c.key===state.category) &&
    (!state.keyword || `${c.text} ${c.title} ${c.item}`.includes(state.keyword)));
}
function notify(text, error=false) {
  $('flash').textContent=text; $('flash').className=error?'error':''; $('flash').hidden=false;
}
function scopeLabel() { return state.age!=='' && state.month ? `${state.age}歳児・${state.month}月` : ''; }
function sourceMarkup(c) { return `<div class="source-block"><h3>${escapeHtml(c.file)}</h3><small>${escapeHtml(c.location)} · ${escapeHtml(c.item)} · ${c.age}歳児 · ${c.month}月</small><p>${escapeHtml(c.text)}</p></div>`; }
function showSource(candidate) {
  $('source-body').innerHTML=(candidate.kind==='ai' ? `<p><span class="tag ai">AI提案の動作見本</span></p><p>${escapeHtml(candidate.text)}</p><h3>参考にした架空の原文</h3>` : '') + (candidate.sources || [candidate]).map(sourceMarkup).join('');
  $('source-dialog').showModal();
}
function toggleChoice(candidate) {
  if (state.selected.has(candidate.id)) state.selected.delete(candidate.id); else state.selected.set(candidate.id,candidate);
  renderResults(); renderBasket();
}
function renderCard(candidate) {
  const card=el('article','',`candidate${state.selected.has(candidate.id)?' selected':''}`);
  const tags=el('div','','candidate-meta');
  tags.append(el('span',candidate.kind==='ai'?'AI提案の見本':'架空の原文',candidate.kind==='ai'?'tag ai':'tag'),el('span',`${candidate.age}歳児`,'tag'),el('span',`${candidate.month}月`,'tag'),el('span',candidate.item,'tag'));
  card.append(tags,el('p',candidate.text),el('div',candidate.kind==='ai'?`参考資料：${candidate.sources.length}件（架空）`:candidate.file,'origin'));
  const actions=el('div','','candidate-actions');
  const source=el('button',candidate.kind==='ai'?'参考にした原文を見る':'出典・原文を見る','text-button'); source.type='button';source.onclick=()=>showSource(candidate);
  const choose=el('button',state.selected.has(candidate.id)?'✓ 選択中':'＋ この候補を選ぶ','choose'); choose.type='button';choose.setAttribute('aria-pressed',String(state.selected.has(candidate.id)));choose.setAttribute('aria-label',`${candidate.title}：${candidate.text}を選択`);choose.onclick=()=>toggleChoice(candidate);
  actions.append(source,choose);card.append(actions);return card;
}
function empty(title,message) { const node=el('div','','empty');node.append(el('strong',title),el('p',message));return node; }
function renderResults() {
  const results=$('results');results.replaceChildren();$('ai-controls').hidden=state.mode!=='ai';
  $('original-mode').setAttribute('aria-pressed',String(state.mode==='original'));
  $('ai-mode').setAttribute('aria-pressed',String(state.mode==='ai'));
  $('generate').disabled=state.age==='' || !state.month || state.error || state.none;
  if(state.age==='' || !state.month) { $('result-summary').textContent='年齢と月を選んでください。';results.append(empty('どの月案を探しますか？','年齢・月・カテゴリを選ぶと、ここに候補が表示されます。'));return; }
  if(state.error) { $('result-summary').textContent=scopeLabel();const box=el('div','','error-box');box.setAttribute('role','alert');box.append(el('strong','候補を読み込めませんでした（エラーの見本）'),el('p','選んだ候補と入力内容は保持しています。'));const retry=el('button','もう一度読み込む','button button--secondary');retry.onclick=()=>{state.error=false;lastScenario='partial';$('scenario').value='partial';renderResults();};box.append(retry);results.append(box);return; }
  const original=state.none?[]:filteredSources();
  if(!original.length) { $('result-summary').textContent=`${scopeLabel()} · 0件`;results.append(empty('条件に合う候補がありません','カテゴリや検索語を変えて探してください。年齢・月の異なる資料は自動で混ぜません。'));return; }
  const candidates=state.mode==='original'?original:state.ai.filter(c=>(state.category==='all'||c.key===state.category)&&c.age===state.age&&c.month===state.month);
  $('result-summary').textContent=state.mode==='original'?`${scopeLabel()} · ${candidates.length}件 · すべて架空サンプル`:`${scopeLabel()} · 参考にできる架空の原文 ${original.length}件 · 提案は見本`;
  if(!candidates.length) { results.append(empty('資料を参考にした提案を確認','「提案の見本を表示」を押すと、出典付きの提案と選択操作を試せます。'));return; }
  sections.forEach(section=>{
    const group=candidates.filter(c=>c.key===section.key);if(!group.length)return;
    const heading=el('div','','group-heading');heading.append(el('h3',section.title),el('span',`${group.length}件`));results.append(heading);
    group.forEach(c=>results.append(renderCard(c)));
  });
}
function renderBasket() {
  $('basket-count').textContent=`${state.selected.size}件`;$('clear-selection').hidden=!state.selected.size;$('to-edit').disabled=!state.selected.size;
  $('basket-list').replaceChildren();
  if(!state.selected.size) {$('basket-list').append(el('p','使いたい候補の「＋ この候補を選ぶ」を押してください。','field-note'));return;}
  state.selected.forEach(c=>{ const item=el('div','','basket-item');item.append(el('strong',c.title),el('p',c.text),el('span',c.kind==='ai'?'AI提案の見本':'架空の原文','tag'));const remove=el('button','選択解除','text-button');remove.setAttribute('aria-label',`${c.title}の選択を解除`);remove.onclick=()=>toggleChoice(c);item.append(document.createTextNode(' '),remove);$('basket-list').append(item); });
}
async function changeScope() {
  if(state.selected.size && !await askConfirm('年齢・月を変更すると、選んだ候補とAI提案の見本を解除します。基本情報は保持します。変更しますか？')) { $('age').value=state.age;$('month').value=state.month;return; }
  const previousMonth=state.month;state.age=$('age').value;state.month=$('month').value;
  state.selected.clear();state.ai=[];state.error=false;state.none=false;
  if(!state.draft && state.month && (!$('target-month').value || Number($('target-month').value.slice(-2))===Number(previousMonth))) $('target-month').value=`${$('target-month').value.slice(0,4)||'2026'}-${state.month.padStart(2,'0')}`;
  renderResults();renderBasket();
}
['age','month'].forEach(id=>$(id).addEventListener('change',changeScope));
$('category').addEventListener('change',()=>{state.category=$('category').value;renderResults();});
$('filters').addEventListener('submit',event=>{event.preventDefault();state.keyword=$('keyword').value.trim();state.ai=[];renderResults();});
$('keyword').addEventListener('input',()=>{state.keyword=$('keyword').value.trim();state.ai=[];renderResults();});
['original','ai'].forEach(mode=>$(mode+'-mode').onclick=()=>{state.mode=mode;renderResults();});
$('generate').onclick=()=>{
  const available=filteredSources();state.ai=sections.flatMap(section=>{
    const sources=available.filter(c=>c.key===section.key).slice(0,2);if(!sources.length)return [];
    return [{id:`ai-${state.age}-${state.month}-${section.key}`,key:section.key,title:section.title,item:section.items[0],age:state.age,month:state.month,kind:'ai',sources,
      text:`${sources[0].text} 子どもの反応を確かめながら、興味の広がりに応じて内容を調整する。`}];
  });renderResults();notify('AI提案の固定見本を表示しました。入力内容は外部へ送信していません。');
};
$('clear-selection').onclick=()=>{state.selected.clear();renderResults();renderBasket();};
$('close-source').onclick=()=>$('source-dialog').close();$('close-info').onclick=()=>$('info-dialog').close();$('import-info').onclick=()=>$('info-dialog').showModal();
$('add-example').onclick=()=>notify('現行の「自作文例を追加」への入口です。今回のモックでは検索と修正の流れを試せます。');
$('back-home').onclick=()=>notify('ここは指導計画ホームへ戻る入口です。モックではこの画面に留まります。');

function showPage(page) { ['picker','editor','saved'].forEach(id=>$(id).hidden=id!==page);window.scrollTo({top:0,behavior:'instant'}); }
function draftFromSelection() {
  return {title:`${$('target-month').value} 月案（${$('classroom').value}）`,owner:$('owner').value.trim(),target:$('target-month').value,classroom:$('classroom').value,confirmation:'',
    sections:sections.map(s=>{const chosen=Array.from(state.selected.values()).filter(c=>c.key===s.key);return {...s,body:chosen.map(c=>c.text).join('\n'),note:'',confirmed:false,sources:chosen};})};
}
function loadEditor(draft) {
  const form=$('editor').querySelector('form');form.elements.title.value=draft.title;form.elements.owner_name.value=draft.owner;form.elements.confirmation_items.value=draft.confirmation;
  $('editor').querySelector('.lead').textContent=`園: 見本の園 / クラス: ${draft.classroom} / タブ内の下書き`;
  $('editor').querySelectorAll('.edit-source,.review-tip').forEach(n=>n.remove());
  const tip=el('p','全10項目を表示しています。本文・編集メモ・確認状態を修正できます。保存はタブ内のみで、再読み込みすると消えます。','review-tip');form.prepend(tip);
  draft.sections.forEach(s=>{form.elements[`body_${s.key}`].value=s.body;form.elements[`editor_note_${s.key}`].value=s.note;form.elements[`confirmed_${s.key}`].checked=s.confirmed;
    const area=form.elements[`body_${s.key}`].closest('.edit-section');const refs=el('div','','edit-source');
    if(!s.sources.length) refs.textContent='候補未選択・直接入力できます。';
    s.sources.forEach((c,i)=>{const button=el('button',`${i+1}. ${c.kind==='ai'?'AI提案の参考原文':'選択した原文'}を見る`,'text-button');button.type='button';button.onclick=()=>showSource(c);refs.append(button,document.createTextNode('　'));});area.append(refs);
  });
  form.querySelector('button[type=submit]').textContent='修正を保存（モック）';
  const back=form.querySelector('.form-actions a');back.textContent='修正を取り消して戻る';back.onclick=async event=>{event.preventDefault();if(await askConfirm('保存していない本文・編集メモの修正を取り消して戻りますか？')){showPage(state.saved?'saved':'picker');notify('未保存の修正を取り消しました。候補の選択は保持しています。');}};
  showPage('editor');
}
$('to-edit').onclick=async()=>{
  if(!$('target-month').value || !$('classroom').value || !$('owner').value.trim()) {notify('対象月・クラス・作成者を入力してください。',true);$('basic-panel').scrollIntoView({behavior:'smooth'});return;}
  if(Number($('target-month').value.slice(-2))!==Number(state.month)) {notify('対象月と候補の月が異なっています。対象月または検索条件を修正してください。',true);$('target-month').focus();return;}
  if(!state.selected.size)return;
  // Returning to search and creating again is an explicit new draft.
  if(state.saved && !await askConfirm('選択した候補から新しい下書きを作ります。タブ内の保存済み見本を置き換えますか？'))return;
  state.saved=null;state.draft=draftFromSelection();loadEditor(state.draft);notify('タブ内に下書きを作成しました。本文を確認して修正できます。');
};
$('editor').querySelector('form').addEventListener('submit',event=>{
  event.preventDefault();const form=event.currentTarget;
  if(!form.elements.title.value.trim()||!form.elements.owner_name.value.trim()) {notify('タイトルと作成者を入力してください。',true);window.scrollTo({top:0});return;}
  const draft=structuredClone(state.draft);draft.title=form.elements.title.value.trim();draft.owner=form.elements.owner_name.value.trim();draft.confirmation=form.elements.confirmation_items.value;
  draft.sections.forEach(s=>{s.body=form.elements[`body_${s.key}`].value;s.note=form.elements[`editor_note_${s.key}`].value;s.confirmed=form.elements[`confirmed_${s.key}`].checked;});
  state.saved=draft;state.draft=structuredClone(draft);renderSaved();showPage('saved');notify('修正をタブ内に保存しました（モック）。実際の月案やDriveは更新されません。');
});
function renderSaved() {
  const container=$('saved');container.replaceChildren();const panel=el('div','','form-panel');panel.append(el('p','タブ内の保存見本','eyebrow'),el('h1',state.saved.title),el('p',`作成者：${state.saved.owner} / 下書き`,'field-note'));
  if(state.saved.confirmation) panel.append(el('h2','確認が必要な入力'),el('p',state.saved.confirmation));
  state.saved.sections.forEach(s=>{const block=el('section','','saved-block');block.append(el('h2',s.title),el('p',s.body||'未入力'),el('p',s.confirmed?'確認済み':'未確認','field-note'));if(s.note)block.append(el('p',`編集メモ：${s.note}`,'field-note'));s.sources.forEach(c=>{const button=el('button','出典・選択時の原文を見る','text-button');button.onclick=()=>showSource(c);block.append(button);});panel.append(block);});
  const toolbar=el('div','','form-actions');const edit=el('button','もう一度修正する','button button--primary');edit.onclick=()=>loadEditor(state.saved);const back=el('button','候補選びへ戻る','button button--secondary');back.onclick=()=>showPage('picker');toolbar.append(edit,back);container.append(panel,toolbar);
}
function applyScenario(value) {
  state.selected.clear();state.ai=[];state.draft=null;state.saved=null;state.error=value==='error';state.none=value==='none';state.mode='original';state.keyword='';state.category='all';$('keyword').value='';$('category').value='all';$('ai-context').value='';$('flash').hidden=true;
  const emptyState=value==='empty';state.age=emptyState?'':'3';state.month=emptyState?'':'10';$('age').value=state.age;$('month').value=state.month;
  $('target-month').value=emptyState?'':'2026-10';$('classroom').value=emptyState?'':'そら組（架空）';$('owner').value=emptyState?'':'担任（架空）';
  if(value==='partial'||value==='filled'||value==='error') {
    const all=examplesFor(state.age,state.month);const count=value==='filled'?sections.length:2;
    sections.slice(0,count).forEach(s=>{const candidate=all.find(c=>c.key===s.key);state.selected.set(candidate.id,candidate);});
  }
  renderResults();renderBasket();showPage('picker');
}
$('scenario').onchange=async()=>{if((state.selected.size||state.draft) && !await askConfirm('状態見本を切り替えると、今の入力・選択・タブ内の保存内容を初期化します。切り替えますか？')){$('scenario').value=lastScenario;return;}lastScenario=$('scenario').value;applyScenario(lastScenario);};
let lastScenario='empty';applyScenario('empty');
