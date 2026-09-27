import { TODAY, STAFF, CLASSES, STATUS, VERIFY, FIELDS, makeChildren, alarms, category, counts, blankReply, replyPreset, shiftDate, allowedTime, availableMinutes, pickupErrors } from './model.mjs';

const $ = (selector, root = document) => root.querySelector(selector);
const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({ '&':'&amp;', '<':'&lt;', '>':'&gt;', '"':'&quot;', "'":'&#39;' }[c]));
const opt = (value, label, selected) => `<option value="${esc(value)}" ${value === selected ? 'selected' : ''}>${esc(label)}</option>`;
const badge = (label, tone = '') => `<span class="badge ${tone}">${esc(label)}</span>`;
const classOptions = value => opt('', '全クラス', value) + CLASSES.map(c => opt(c, c, value)).join('');
const button = (label, action, extra = '', cls = '') => `<button type="button" data-action="${action}" ${extra} class="${cls}">${label}</button>`;
const choice = (label, action, value, selected, extra = '') => button(esc(label), action, `data-value="${esc(value)}" aria-pressed="${value === selected}" ${extra}`);
let children = makeChildren();
let scenario = 'partial', inputStyle = 'quick', page = 'roster', currentChild = 1, contactDate = TODAY;
let rosterClass = '', rosterSearch = '', rosterDate = TODAY, homeScope = 'all';
let checkClass = '', checkFilter = 'all', checkLayout = 'classroom', checkDate = TODAY;
let contactClass = CLASSES[0], contactSearch = '', contactSort = 'name';
let closedAt = '19:00', settingError = '', savedSetting = false;
let kiosk = { step: 'pickup', className: CLASSES[0], childId: 2, hour: '', minute: '', person: '', snack: '', actualPerson: '', error: '' };
const replies = new Map(), expandedChecks = new Set();
let modal = null, toastTimer, lastRoute = '';
const childById = id => children.find(c => c.id === Number(id)) || children[0];
const key = (id, date) => `${id}:${date}`;
const prettyDate = date => new Intl.DateTimeFormat('ja-JP', { dateStyle:'long', timeZone:'UTC' }).format(new Date(`${date}T12:00:00Z`));
function entry(id = currentChild, date = contactDate) {
  const k = key(id, date);
  if (!replies.has(k)) {
    const prior = date < TODAY;
    const sample = date === TODAY ? replyPreset(scenario) : prior ? replyPreset('filled') : blankReply();
    const published = prior && date !== shiftDate(TODAY, -1);
    replies.set(k, { saved: {...sample}, working: {...sample}, published: published ? {...sample} : null, status: published ? 'published' : 'draft', dirty: false, savedOnce: prior || date === TODAY && scenario !== 'empty', error: '', clickCount: 0 });
  }
  return replies.get(k);
}
function toast(message) { const el = $('#toast'); el.textContent = message; el.hidden = false; clearTimeout(toastTimer); toastTimer = setTimeout(() => { el.hidden = true; }, 6500); }
function openDialog(title, body, actions) { $('#dialog-content').innerHTML = `<h2 id="dialog-title">${title}</h2>${body}<div class="actions end">${actions}</div>`; if (!$('#dialog').open) $('#dialog').showModal(); }
function closeDialog() { $('#dialog').close(); modal = null; }
function errorBlock(message) { return message ? `<div class="notice error" role="alert">${esc(message)}</div>` : ''; }
function replyBadge(r) { return r.dirty ? badge('未送信・編集中', 'amber') : r.status === 'published' ? badge('公開済み', 'green') : badge(r.published ? '未送信の変更あり' : '未送信', 'amber'); }
function head(title, desc, actions = '') { return `<div class="page-head"><div><h1>${title}</h1><p>${desc}</p></div>${actions}</div>`; }
function statsMarkup(list) { const c = counts(list); return `<div class="stats">${[['在籍',c.enrolled],['登園',c.arrived],['在園中',c.in],['降園',c.out],['欠席',c.absent],['未登園',c.pending]].map(([label,n]) => `<div class="stat"><span>${label}</span><strong>${n}</strong></div>`).join('')}</div>`; }
function rosterPage() {
  const groups = CLASSES.filter(c => !rosterClass || c === rosterClass);
  const filtered = children.filter(c => (!rosterClass || c.classroom === rosterClass) && c.name.replace(/\s/g,'').includes(rosterSearch.replace(/\s/g,'')));
  return head('子どもの名前一覧', `${prettyDate(rosterDate)} · 在園・降園・お休み・未登園をクラスごとに確認できます。`, '<a href="#home">トップの人数表示へ →</a>') +
    `<div class="toolbar"><label>日付<input id="roster-date" type="date" value="${rosterDate}"></label><label>クラス<select id="roster-class">${classOptions(rosterClass)}</select></label><label class="grow">子どもの名前<input id="roster-search" type="search" value="${esc(rosterSearch)}" placeholder="名前で探す"></label>${button('条件をクリア','clear-roster')}</div>
    ${rosterDate !== TODAY ? '<div class="notice">この試作では、日付を変えた場合も同じ架空の出欠データを表示します。</div>' : ''}
    <p class="summary-line">全区分の${filtered.length}人を表示 · 在園 ${counts(filtered).in} / 降園 ${counts(filtered).out} / お休み ${counts(filtered).absent} / 未登園 ${counts(filtered).pending} · 名前から詳細</p>` +
    groups.map(group => { const list = filtered.filter(c => c.classroom === group); return `<section class="class-section"><div class="class-heading"><h2>${group}<small>${list.length}人${rosterSearch ? '（検索結果）' : '在籍'}</small></h2><a href="#checks/${encodeURIComponent(group)}">出欠確認を開く →</a></div><div class="roster-columns">${Object.entries(STATUS).map(([status,label]) => {
      const items = list.filter(c => category(c) === status);
      return `<section class="roster-column ${status}" aria-label="${group}の${label}"><h3 class="column-title"><span>${label}</span><b>${items.length}人</b></h3><div class="name-list">${items.map(c => button(`${esc(c.name)}${alarms(c).length ? '<span class="alarm-dot" aria-label="要確認">●</span>' : ''}`, 'child-detail', `data-id="${c.id}" title="${esc(`${c.name} / ${label} / 登園 ${c.checkIn||'未打刻'} / 降園 ${c.checkOut||'未打刻'}${alarms(c).length?' / 要確認':''}`)}"`, 'name-button')).join('') || '<p class="empty">—</p>'}</div></section>`;
    }).join('')}</div></section>`; }).join('');
}
function homePage() {
  return head('職員ホーム', `${prettyDate(TODAY)} · こもれび保育園`, '<a href="#roster">子どもの名前一覧を開く →</a>') + `<div class="home-grid"><section class="card"><div class="row between"><div><div class="eyebrow">Attendance</div><h2>${homeScope === 'all' ? '全クラス' : '担当クラス'}の出欠確認</h2></div><div class="row">${choice('担当','home-scope','assigned',homeScope)}${choice('全クラス','home-scope','all',homeScope)}</div></div><p class="small muted mt">登園人数には職員の出席確認も含みます。打刻時刻は別に記録します。</p>${CLASSES.filter((c,i) => homeScope === 'all' || i === 0).map(group => { const list = children.filter(c => c.classroom === group); return `<article class="home-class"><div class="row between"><div class="row"><h3>${group}</h3>${badge(`アラーム ${counts(list).alarm}人`, counts(list).alarm ? 'red' : '')}</div><a class="small strong" href="#checks/${encodeURIComponent(group)}">出欠確認を開く</a></div>${statsMarkup(list)}</article>`; }).join('')}</section><section class="card"><div class="eyebrow">Today</div><h2>今日の予定</h2><div class="contact-note"><strong>10:00–11:00</strong>園庭あそび</div><div class="contact-note"><strong>11:30–12:15</strong>給食</div><div class="contact-note"><strong>12:30–14:30</strong>お昼寝</div><p class="small muted mt">トップは既存の人数表示を維持する確認用です。今回の変更対象外の業務は省略しています。</p></section></div>`;
}
function checksPage() {
  const filtered = children.filter(c => (!checkClass || c.classroom === checkClass) && (checkFilter === 'all' || checkFilter === 'alarm' && alarms(c).length || checkFilter === 'absent' && ['private_absent','sick_absent'].includes(c.verification) || checkFilter === c.verification));
  let previousClass = '';
  return `<div class="check-hero"><div class="row between"><h1>出欠確認</h1><span class="small">${checkDate} / ${STAFF}</span></div></div>
    <div class="toolbar"><label>日付<input type="date" id="check-date" value="${checkDate}"></label><label>表示形態<select id="check-layout">${opt('flat','全園児を一覧',checkLayout)}${opt('classroom','クラス別に表示',checkLayout)}</select></label><label>絞り込み<select id="check-filter">${Object.entries({all:'全員（すべての状態）', present:'出席のみ', absent:'欠席のみ',private_absent:'私用休み',sick_absent:'病欠',unknown:'未確認',alarm:'アラームあり'}).map(([v,l])=>opt(v,l,checkFilter)).join('')}</select></label><label>クラス<select id="check-class">${classOptions(checkClass)}</select></label>${button('表示','refresh-checks','','primary')}${button('全員を表示','all-checks')}</div>
    ${checkDate !== TODAY ? '<div class="notice">別の日は表示の試用のみです。訂正は9月24日に戻して試してください。</div>' : ''}
    <p class="summary-line">${filtered.length}人を表示 · 在園 ${counts(filtered).in} / 降園 ${counts(filtered).out} / お休み ${counts(filtered).absent} / 未登園 ${counts(filtered).pending} · アラーム ${filtered.filter(c=>alarms(c).length).length}人</p><div class="check-columns" aria-hidden="true"><span>子ども</span><span>現在</span><span>登園 / 降園</span><span>保護者連絡</span><span>目視確認</span><span>詳細</span></div>` + filtered.map(c => {
      const groupHead = checkLayout === 'classroom' && previousClass !== c.classroom ? `<h2 class="check-class-heading">${c.classroom}<small>${filtered.filter(p=>p.classroom===c.classroom).length}人</small></h2>` : ''; previousClass = c.classroom;
      return groupHead + `<article class="check-row ${alarms(c).length ? 'alarm' : ''}" id="check-${c.id}"><div class="check-summary"><div class="check-name"><strong>${c.name}</strong>${alarms(c).length ? '<span class="alarm-dot" title="アラームあり" aria-label="アラームあり">●</span>' : ''}${checkLayout==='flat'?`<small>${c.classroom}</small>`:''}</div><div class="check-category">${badge(STATUS[category(c)], {in:'green',out:'indigo',absent:'red',pending:'amber'}[category(c)])}</div><div class="check-times"><span aria-label="登園時刻">${c.checkIn || '—'}</span><span class="muted"> / </span><span aria-label="降園時刻">${c.checkOut || '—'}</span></div><div class="check-parent">${esc(c.confirmed ? `${c.confirmed.method} / ${VERIFY[c.confirmed.status]}` : c.parentType ? `${c.parentType} / アプリ` : '未提出')}</div><div class="check-status" role="group" aria-label="${c.name}の目視確認">${Object.entries(VERIFY).map(([v,label]) => choice(label,'verify',v,c.verification,`data-id="${c.id}" ${checkDate!==TODAY?'disabled':''}`)).join('')}</div>${button(expandedChecks.has(c.id)?'閉じる':'詳細','toggle-check',`data-id="${c.id}" aria-label="${c.name}の詳細${expandedChecks.has(c.id)?'を閉じる':''}" aria-expanded="${expandedChecks.has(c.id)}"`,'check-open')}</div>
      ${expandedChecks.has(c.id) ? checkDetail(c) : ''}</article>`;
    }).join('') + (!filtered.length ? '<div class="card empty">条件に合う子どもはいません。</div>' : '');
}
function checkDetail(c) {
  return `<div class="check-detail">${c.checkIn?`<div class="row between mb"><p class="small">打刻：登園 ${c.checkIn} / 降園 ${c.checkOut||'未打刻'}</p>${button('誤打刻を取り消す','punch-cancel',`data-id="${c.id}"`,'link-button small')}</div>`:''}<div class="field-grid"><section><h3>保護者連絡</h3><p class="small mt">${esc(c.parentType || '連絡はまだありません')}</p>${c.parentType === '病欠' ? '<p class="small">体温：37.8℃ / 症状：発熱<br>診断名：未受診 / 備考：家庭で休みます。</p>' : '<p class="small">体調メモ：普段どおりです。<br>連絡事項：特になし</p>'}<a class="small" href="#contact/${c.id}/${checkDate}">保護者連絡の詳細へ</a></section><section><h3>目視確認</h3><p class="small mt">${VERIFY[c.verification]}<br>更新者：${c.logs.length ? STAFF : '見本 たろう'}<br>更新時刻：${c.logs.at(-1)?.time || '09:10:00'} JST</p></section><section><h3>アラーム理由</h3><p class="small mt">${esc(alarms(c).join(' / ') || 'なし')}</p></section><section><h3>訂正・操作履歴</h3>${c.logs.length ? c.logs.slice().reverse().map(log => `<div class="history-item"><strong>${esc(log.action)}</strong><p>${esc(log.before)} → ${esc(log.after)}<br>訂正者：${esc(log.staff)} / ${esc(log.time)}<br>理由：${esc(log.reason)}</p></div>`).join('') : '<p class="small muted mt">まだ訂正履歴はありません。</p>'}</section></div>
    <hr class="separator"><h3>電話・口頭連絡の受付</h3><p class="small muted mt">目視確認と同じ欠席理由を受け付けると、「保護者連絡なし」を解消します。</p>
    <div class="field-grid mt"><label class="field"><span>連絡方法</span><select id="method-${c.id}"><option>電話</option><option>口頭</option></select></label><label class="field"><span>欠席理由</span><select id="absence-${c.id}"><option value="">選択してください</option><option value="private_absent">私用休み</option><option value="sick_absent">病欠</option></select></label></div><label class="field mt"><span>連絡内容・訂正理由<span class="required">必須</span></span><input id="note-${c.id}" maxlength="1000" placeholder="誰から、どのような連絡を受けたか"></label><div class="actions">${button('連絡受付を記録','record-contact',`data-id="${c.id}" ${checkDate!==TODAY?'disabled':''}`,'primary')}${c.confirmed ? button('受付を取り消す','revoke-contact',`data-id="${c.id}" ${checkDate!==TODAY?'disabled':''}`) : ''}</div><div id="contact-error-${c.id}" role="alert"></div></div>`;
}
function contactListPage() {
  let list = children.filter(c => (!contactClass || c.classroom === contactClass) && c.name.includes(contactSearch));
  if (contactSort === 'name') list.sort((a,b)=>a.name.localeCompare(b.name,'ja'));
  if (contactSort === 'unsent') list.sort((a,b)=>Number(entry(a.id,contactDate).status === 'published')-Number(entry(b.id,contactDate).status === 'published'));
  return head('保護者連絡一覧','保護者の提出状況と、園からの連絡の未送信・公開済みを確認できます。') + `<div class="toolbar"><label>日付<input id="contact-list-date" type="date" value="${contactDate}"></label><label>クラス<select id="contact-class">${classOptions(contactClass)}</select></label><label>表示順<select id="contact-sort">${opt('name','名前順',contactSort)}${opt('unsent','未送信から',contactSort)}</select></label><label class="grow">名前<input id="contact-search" type="search" value="${esc(contactSearch)}" placeholder="名前で探す"></label></div><div class="table-wrap"><table><thead><tr>${['園児','クラス','保護者の提出状況','園からの連絡','連絡内容','提出者','更新日時','操作'].map(x=>`<th>${x}</th>`).join('')}</tr></thead><tbody>${list.map(c=>`<tr><td><strong>${c.name}</strong></td><td>${c.classroom}</td><td>${badge(c.parentType?'提出済み':'未提出',c.parentType?'green':'amber')}</td><td>${replyBadge(entry(c.id,contactDate))}<small>${entry(c.id,contactDate).savedOnce?'更新者：'+STAFF:'未作成'}</small></td><td>${c.parentType||'—'}</td><td>${c.parentType?'見本の保護者':'—'}</td><td>${c.parentType?`${contactDate} 07:30`:'—'}</td><td><a href="#contact/${c.id}/${contactDate}">詳細を開く</a></td></tr>`).join('') || '<tr><td colspan="8">条件に合う子どもはいません。</td></tr>'}</tbody></table></div>`;
}
function parentContact(c) {
  if (!c.parentType || contactDate > TODAY) return '<section class="card"><h2>保護者からの連絡</h2><p class="muted mt">保護者からの連絡は未提出です。園から先に連絡を公開できます。</p></section>';
  const data = c.parentType === '病欠' ? [['欠席理由','病欠'],['備考','家庭で休みます。'],['現在の体温','37.8℃'],['症状','発熱'],['医師から伝えられた診断名','未受診']] : [['就寝','20:30'],['起床','06:30'],['朝食の内容','ごはん・みそ汁・卵'],['排便の性状','普通'],['排便回数','1回'],['体温','36.5℃'],['睡眠メモ','よく眠りました'],['朝食','完食'],['排便','あり'],['機嫌','良好'],['服薬','なし'],['咳','なし'],['鼻水','なし'],['状態','提出済み']];
  return `<section class="card"><h2>保護者からの連絡</h2><div class="contact-meta">提出者：見本の保護者 / 更新日時：${contactDate} 07:30 JST / 連絡内容：${c.parentType}</div><div class="contact-info">${data.map(([l,v])=>`<div><span>${l}</span>${v}</div>`).join('')}</div>${c.parentType === '病欠' ? '' : '<div class="contact-note"><strong>体調メモ</strong>普段どおりです。</div><div class="contact-note"><strong>園への連絡事項</strong>お迎えは母です。よろしくお願いします。</div>'}</section>`;
}
function choiceField(keyName, label, options, r) {
  return `<fieldset class="field"><legend>${label}</legend>${inputStyle === 'quick' ? `<div class="choices">${options.map(x=>choice(x,'reply-choice',x,r.working[keyName],`data-field="${keyName}"`)).join('')}${button('クリア','reply-choice',`data-field="${keyName}" data-value=""`,'clear')}</div>` : `<select data-reply-field="${keyName}" aria-label="${label}">${opt('','未選択',r.working[keyName])}${options.map(x=>opt(x,x,r.working[keyName])).join('')}</select>`}</fieldset>`;
}
function contactPage() {
  const c = childById(currentChild), r = entry();
  return `<div class="narrow">${head(`${c.name} の保護者連絡`,`${c.classroom} · 同じ子どもの連絡を日付で確認`, '<a href="#contacts">一覧へ戻る</a>')}<div class="toolbar between"><div class="date-controls">${button('← 前日','date-prev')}<input type="date" id="contact-date" aria-label="連絡の日付" value="${contactDate}">${button('翌日 →','date-next')}${button('今日','date-today')}</div><div class="row">${button('園からの連絡を入力 ↓','jump-reply','','link-button')}<a href="#history/${c.id}">この子の連絡履歴</a></div></div>${parentContact(c)}
    <section class="card reply-form"><div class="row between"><div><h2>園からの連絡</h2><p class="small muted mt">保護者に伝える当日の様子を入力します。</p></div><div id="reply-status">${replyBadge(r)}<p class="small muted mt">${r.dirty ? '変更はまだ保存されていません' : r.status === 'published' ? '公開済みの内容を表示しています' : r.savedOnce ? '下書き保存済み' : 'まだ保存されていません'}</p></div></div>${r.published && (r.dirty || r.status==='draft') ? '<div class="notice warning">公開済みの内容はそのままです。変更内容は、もう一度公開するまで保護者には反映されません。</div>' : ''}${errorBlock(r.error)}
    <div class="field-grid"><label class="field"><span>お昼寝時間</span><input data-reply-field="nap_time" value="${esc(r.working.nap_time)}" placeholder="12:30-14:20"><span class="small muted">例：12:30-14:20。寝なかった場合も文字で入力できます。</span></label><div class="field"><label class="field"><span>体温</span><input data-reply-field="temperature" inputmode="decimal" value="${esc(r.working.temperature)}" placeholder="36.8"></label>${inputStyle === 'quick' ? `<div class="temperature-choices" aria-label="体温の整数">${[35,36,37,38,39,40].map(x=>choice(String(x),'temperature-whole',String(x),r.working.temperature.split('.')[0])).join('')}</div><div class="temperature-choices" aria-label="体温の小数">${Array.from({length:10},(_,x)=>choice(`.${x}`,'temperature-fraction',String(x),r.working.temperature.split('.')[1])).join('')}${button('クリア','reply-choice','data-field="temperature" data-value=""','link-button')}</div>` : ''}</div>${choiceField('bowel_movement','排便',['あり','なし'],r)}${choiceField('appetite','食欲（給食）',['完食','ほぼ完食','半分','少なめ'],r)}</div>
    <label class="field mt"><span>連絡メモ</span><textarea data-reply-field="message" rows="5" placeholder="今日の様子や保護者に伝えたいこと">${esc(r.working.message)}</textarea></label><div class="actions">${button('下書き保存','save-draft')}${button(r.status==='published'?'変更を公開':'保護者に公開','publish','','primary')}${r.dirty?button('変更を取り消す','discard-reply'):''}</div><p class="small muted mt">未入力の項目を自動で埋めることはありません。</p></section></div>`;
}
function historyPage() {
  const c = childById(currentChild);
  return `<div class="narrow">${head(`${c.name} の連絡履歴`,`${c.classroom} · 同じ子どもの日ごとの連絡`,`<a href="#contact/${c.id}/${contactDate}">連絡画面へ戻る</a>`)}<div class="table-wrap"><table><thead><tr><th>日付</th><th>園からの連絡</th><th>連絡メモ</th><th>操作</th></tr></thead><tbody>${Array.from({length:7},(_,i)=>shiftDate(TODAY,-i)).map(date=>{ const r=entry(c.id,date); return `<tr><td>${date}</td><td>${replyBadge(r)}</td><td>${esc((r.saved.message || '—').slice(0,25))}</td><td><a href="#contact/${c.id}/${date}">開く</a></td></tr>`; }).join('')}</tbody></table></div><p class="small muted mt">この一覧の形は試作案です。園からの未送信と、保護者からの未提出は別々に扱います。</p></div>`;
}
let kioskNow = '08:15';
function kioskPage() {
  const c = childById(kiosk.childId);
  const afterClose = !allowedTime(kioskNow,closedAt);
  const header = `<div class="kiosk-config"><strong>試用設定（業務画面の外）</strong><div class="row"><label>場面 <select id="kiosk-scene">${opt('pickup','登園後のお迎え入力',kiosk.step)}${opt('classes','クラス・名前選択',kiosk.step)}${opt('departure','降園',kiosk.step)}</select></label><label>現在時刻の再現 <input type="time" id="kiosk-now" value="${kioskNow}"></label><span>閉園 ${closedAt}（仮の設定値）</span><a href="#settings">設定を変更</a></div><p class="mt">閉園時刻ちょうどから非表示・受付不可とする案です。時刻や境界はモックで確認してください。</p></div><div class="kiosk-top"><div><strong>登園・降園</strong><p class="small">2026年9月24日（木）</p></div><time>${kioskNow}</time>${button('最初に戻る','kiosk-start')}</div>`;
  let content = '';
  if (kiosk.step === 'classes') content = `<section class="card"><h2>1. クラスを選択</h2><div class="choice-grid mt">${CLASSES.map(c=>button(c,'kiosk-class',`data-value="${c}"`)).join('')}</div></section>`;
  else if (kiosk.step === 'names') content = `<section class="card"><h2>2. 園児を選択（${kiosk.className}・全員）</h2><p class="small muted mt">在園・降園・お休み・未登園の子をすべて表示しています。</p><div class="choice-grid mt">${children.filter(c=>c.classroom===kiosk.className).map(c=>button(`${esc(c.name)}<br>${badge(STATUS[category(c)],{in:'green',out:'indigo',absent:'red',pending:'amber'}[category(c)])}`,'kiosk-child',`data-id="${c.id}"`)).join('')}</div></section>`;
  else if (kiosk.step === 'arrival') content = `<section class="card"><p class="muted">${c.classroom}</p><h1>${c.name}</h1>${button('登園する','kiosk-arrive',afterClose?'disabled':'','primary width-full')}${errorBlock(kiosk.error)}</section>`;
  else if (kiosk.step === 'departure') content = `<section class="card"><p class="muted">${c.classroom}</p><h1>${c.name}</h1><p class="muted">登園時刻：${c.checkIn || '未打刻（職員が出席確認済み）'} ／ お迎えの予定：母</p><fieldset class="mt"><legend>実際にお迎えに来た人を選んでください</legend><div class="choices">${['母','父','祖父','祖母','ファミリーサポート','その他'].map(x=>choice(x,'actual-person',x,kiosk.actualPerson)).join('')}</div></fieldset>${errorBlock(kiosk.error)}<div class="actions">${button('降園する','kiosk-depart',afterClose?'disabled':'','primary')}</div></section>`;
  else if (kiosk.step === 'done') content = `<section class="card"><p class="muted">${c.classroom}</p><h1>${c.name}</h1><div class="notice success"><strong>受付が完了しました</strong><p>このタブ内での記録です。本番の打刻・送信はありません。</p></div>${button('最初に戻る','kiosk-start','','primary')}</section>`;
  else if (kiosk.step === 'confirm') content = `<section class="card"><p class="muted">${c.classroom}</p><h1>${c.name}</h1><h2>お迎え予定の確認</h2><div class="time-display"><span>降園予定</span><strong>${kiosk.hour}:${kiosk.minute}</strong></div><p>お迎え予定の人：${esc(kiosk.person)}<br>補食：${esc(kiosk.snack)}</p>${errorBlock(kiosk.error)}<div class="actions">${button('修正する','kiosk-edit')}${button('この内容で登録する','kiosk-commit',afterClose?'disabled':'','primary')}</div></section>`;
  else {
    const hourButtons = hours => hours.filter(h=>allowedTime(`${String(h).padStart(2,'0')}:00`,closedAt)).map(h=>choice(`${h}時`,'pickup-hour',String(h).padStart(2,'0'),kiosk.hour)).join('');
    const validMinutes = kiosk.hour ? availableMinutes(kiosk.hour,closedAt) : ['00','15','30','45'];
    const late = hourButtons([19,20,21,22]);
    content = `<section class="card"><p class="muted">${c.classroom}</p><h1>${c.name}</h1><h2>お迎え予定を入力してください</h2>${errorBlock(kiosk.error)}<fieldset class="mt"><legend>降園予定時刻</legend><div class="time-display"><span>選択中</span><strong>${kiosk.hour||'--'}:${kiosk.minute||'--'}</strong></div><p class="strong">1. 時を選ぶ <span class="small muted">（24時間表記）</span></p><p class="small muted mt">10〜14時</p><div class="hours">${hourButtons([10,11,12,13,14])}</div><p class="small muted">15〜18時</p><div class="hours main">${hourButtons([15,16,17,18])}</div>${late?`<p class="small muted">19時以降</p><div class="hours main">${late}</div>`:''}<details><summary>その他の時刻</summary><div class="hours">${hourButtons([0,1,2,3,4,5,6,7,8,9,23])}</div></details><p class="strong mt">2. 分を選ぶ</p><div class="minutes">${['00','15','30','45'].filter(m=>validMinutes.includes(m)).map(m=>choice(`${m}分`,'pickup-minute',m,kiosk.minute,!kiosk.hour?'disabled':'')).join('')}</div><details><summary>その他の分を選ぶ</summary><label class="field"><span>分（1分単位）</span><select id="pickup-exact" ${!kiosk.hour?'disabled':''}>${opt('','選択してください',kiosk.minute)}${validMinutes.map(m=>opt(m,`${m}分`,kiosk.minute)).join('')}</select></label></details></fieldset><hr class="separator"><fieldset><legend>お迎え予定の人</legend><div class="choices">${['母','父','祖父','祖母','ファミリーサポート','その他'].map(p=>choice(p,'pickup-person',p,kiosk.person)).join('')}</div></fieldset><fieldset class="mt"><legend>補食</legend><div class="choices">${['不要','必要'].map(s=>choice(s,'pickup-snack',s,kiosk.snack)).join('')}</div></fieldset><div class="actions">${button('取り消し','kiosk-cancel')}${button('確認へ','kiosk-confirm',afterClose?'disabled':'','primary')}</div></section>`;
  }
  return `<div class="kiosk-frame">${header}${afterClose ? `<div class="notice warning" role="alert">本日の受付は終了しました（閉園 ${closedAt}）。職員にお声がけください。</div>` : ''}${content}${button('全画面終了','kiosk-fullscreen','','quiet-exit')}<p class="small muted">※全画面の終了は、この試作では表示のみ再現します。</p></div>`;
}
function settingsPage() { return `<div class="narrow">${head('閉園時間の設定','保護者キオスクで選べるお迎え予定時刻に反映します。')}<section class="card"><h2>保護者キオスク</h2><label class="field mt"><span>閉園時刻<span class="required">必須</span></span><input type="time" id="closing-time" value="${closedAt}"></label><p class="small muted mt">設定した時刻以降の時・分のボタンを表示せず、その時刻の入力も受け付けません。</p>${errorBlock(settingError)}${savedSetting?'<div class="notice success">試用設定を保存しました。キオスクに反映されています。</div>':''}<div class="actions">${button('設定を保存','save-settings','','primary')}<a href="#kiosk">保護者キオスクを開く →</a></div></section><div class="notice">モックでの仮置き：初期値19:00、閉園時刻ちょうども受付不可、曜日によらず同じ時刻。現在時刻が閉園を過ぎた場合の受付終了表示も試せます。</div></div>`; }

function render() {
  const contactInputs = page==='checks' ? [...document.querySelectorAll('.check-detail input, .check-detail select')].map(el=>[el.id,el.value]) : [];
  const renders = {home:homePage, roster:rosterPage, checks:checksPage, contacts:contactListPage, contact:contactPage, history:historyPage, kiosk:kioskPage, settings:settingsPage};
  $('#app').dataset.page=page;
  $('#app').innerHTML = (renders[page]||rosterPage)();
  contactInputs.forEach(([id,value])=>{const el=document.getElementById(id);if(el)el.value=value;});
  document.querySelectorAll('.app-nav a').forEach(a=>{ const target=a.hash.slice(1); if (target===page || target==='contacts'&&['contact','history'].includes(page)) a.setAttribute('aria-current','page'); else a.removeAttribute('aria-current'); });
}
function applyRoute() {
  const [route, id, date] = (location.hash.slice(1)||'roster').split('/');
  page = ['home','roster','checks','contacts','contact','history','kiosk','settings'].includes(route)?route:'roster';
  if (page==='checks' && id) checkClass=decodeURIComponent(id);
  if (['contact','history'].includes(page) && id) currentChild=childById(id).id;
  if (page==='contact' && /^\d{4}-\d{2}-\d{2}$/.test(date||'')) contactDate=date;
  lastRoute=location.hash || '#roster'; render(); window.scrollTo({top:0,behavior:'instant'});
}
function commitNavigate(target) { if (location.hash===target) applyRoute(); else location.hash=target; }
function navigate(target) {
  if (page==='contact' && entry().dirty && target!==lastRoute) {
    modal={type:'navigate',target};
    openDialog('編集中の連絡があります',`<p>${esc(childById(currentChild).name)}さん・${contactDate} の変更はまだ保存されていません。</p><p class="mt">下書き保存すると「未送信」のまま移動します。</p><div id="modal-error"></div>`,button('入力に戻る','close-dialog')+button('変更を破棄して移動','discard-navigate')+button('下書き保存して移動','save-navigate','','primary')); return;
  }
  commitNavigate(target);
}
function saveReply(publish=false) {
  const r=entry();
  if (scenario==='error') { r.error='保存できませんでした。入力内容は残っています。試用設定を「一部入力」などに切り替えると再試行できます。'; return false; }
  if (/^\.|\.$/.test(r.working.temperature)) { r.error='体温の整数と小数を両方選ぶか、体温をクリアしてください。'; return false; }
  if (publish && !Object.values(r.working).some(v=>v.trim())) { r.error='公開する内容を1つ以上入力してください。'; return false; }
  r.saved={...r.working}; r.dirty=false; r.status=publish?'published':'draft'; if(publish)r.published={...r.working}; r.savedOnce=true; r.error=''; return true;
}
function touchReply(field,value) { const r=entry(); r.working[field]=value; r.dirty=JSON.stringify(r.working)!==JSON.stringify(r.saved); r.error=''; r.clickCount++; }
function updateReplyStatus() {
  const r=entry();
  $('#reply-status').innerHTML=`${replyBadge(r)}<p class="small muted mt">${r.dirty?'変更はまだ保存されていません':r.status==='published'?'公開済み':'下書き保存済み'}</p>`;
  const actions=$('.reply-form > .actions');
  actions.innerHTML=button('下書き保存','save-draft')+button(r.status==='published'?'変更を公開':'保護者に公開','publish','','primary')+(r.dirty?button('変更を取り消す','discard-reply'):'');
}
function correctionDialog(c,type,value='') {
  if (checkDate!==TODAY) { toast('9月24日に戻して訂正を試してください。'); return; }
  modal={type, id:c.id, value};
  const reason = ['filled','error'].includes(scenario) ? '確認時の選択を誤ったため、担任が本人の状況を確認して訂正。' : '';
  let fields = type==='verify' ? `<p class="notice">目視確認：${VERIFY[c.verification]} → ${VERIFY[value]}</p>${value==='unknown'?'<label class="field"><span>保護者への確認依頼</span><select id="notify-parent"><option value="no">連絡しない</option><option value="yes">連絡する（モック内で再現）</option></select></label>':''}` : type==='punch-cancel' ? `<label class="field"><span>取り消す記録</span><select id="cancel-operation">${c.checkOut?'<option value="check_out">降園打刻のみ（登園は残す）</option>':''}<option value="all">登園・降園とお迎え予定を取り消す</option></select></label><p class="small muted mt">元の打刻と理由を履歴に残します。別のアラームは再確認します。</p>` : '<p class="notice">電話・口頭連絡の受付を取り消します。</p>';
  openDialog(type==='verify'?'出欠確認を訂正':type==='punch-cancel'?'打刻の取消':'連絡受付の取消',`<p>${c.name} / ${checkDate}</p>${fields}<label class="field"><span>訂正した人<span class="required">必ず記録</span></span><input value="${STAFF}" readonly aria-label="訂正した人"><small class="muted">ログイン中の職員を自動記録します。</small></label><label class="field"><span>訂正理由<span class="required">必須</span></span><textarea id="correction-reason" rows="3" maxlength="500" placeholder="訂正の理由を入力してください">${reason}</textarea></label><div id="modal-error"></div>`,button('取り消し','close-dialog')+button('理由を記録して確定','confirm-correction','','primary'));
}
function appendLog(c,action,before,after,reason) { c.logs.push({action,before,after,reason,staff:STAFF,time:new Intl.DateTimeFormat('ja-JP',{hour:'2-digit',minute:'2-digit',second:'2-digit',timeZone:'Asia/Tokyo'}).format(new Date())}); }
function confirmCorrection() {
  const reason=$('#correction-reason').value.trim();
  if (!reason) { $('#modal-error').innerHTML=errorBlock('訂正理由を入力してください。理由なしでは保存できません。'); $('#correction-reason').focus(); return; }
  if (scenario==='error') { $('#modal-error').innerHTML=modalSaveError('保存できませんでした。理由を保持しています。'); return; }
  const c=childById(modal.id);
  if (modal.type==='verify') { appendLog(c,'目視確認の訂正',VERIFY[c.verification],VERIFY[modal.value],reason); c.verification=modal.value; }
  else if (modal.type==='punch-cancel') { const all=$('#cancel-operation').value==='all'; appendLog(c,'打刻の取消',`登園 ${c.checkIn||'なし'}・降園 ${c.checkOut||'なし'}`,all?'登園・降園なし':`登園 ${c.checkIn}・降園なし`,reason); c.checkOut=''; if(all)c.checkIn=''; }
  else { appendLog(c,'連絡受付の取消',c.confirmed?.method+' / '+VERIFY[c.confirmed?.status],'受付なし',reason); c.confirmed=null; }
  expandedChecks.add(c.id); closeDialog(); render(); $(`#check-${c.id}`)?.scrollIntoView({block:'center'}); toast('訂正理由と訂正者を記録しました。出欠確認画面のまま続けられます。');
}
function presetKiosk() {
  Object.assign(kiosk,{hour:scenario==='empty'?'':scenario==='error'?'19':'17',minute:scenario==='empty'?'':'00',person:['filled','error'].includes(scenario)?'母':'',snack:['filled','error'].includes(scenario)?'不要':'',error:''});
}
function checkKioskBeforeSave() {
  kiosk.error= !allowedTime(kioskNow,closedAt) ? '閉園時間を過ぎているため、受付できません。' : pickupErrors(kiosk,closedAt).join(' ');
  if (!kiosk.error && scenario==='error') kiosk.error='保存できませんでした。入力内容を保持しています。試用設定でエラーを解除して再試行してください。';
  return !kiosk.error;
}
function modalSaveError(message) { return errorBlock(message)+`<div class="kiosk-config mt"><p>試用操作：保存失敗からの再試行を確認します。</p>${button('保存エラーを解除','recover-error')}</div>`; }

document.addEventListener('click', event => {
  const link=event.target.closest('a[href^="#"]');
  if(link) {event.preventDefault(); navigate(link.getAttribute('href')); return;}
  const el=event.target.closest('[data-action]'); if(!el || el.disabled)return;
  const action=el.dataset.action, value=el.dataset.value, id=Number(el.dataset.id), c=childById(id);
  if(action==='close-dialog'){closeDialog();return;}
  if(action==='clear-roster'){rosterClass='';rosterSearch='';rosterDate=TODAY;render();}
  else if(action==='home-scope'){homeScope=value;render();}
  else if(action==='child-detail') {modal={type:'child'};openDialog(c.name,`<p>${c.classroom} / ${rosterDate}</p><div class="notice">${STATUS[category(c)]} · 登園 ${c.checkIn||'未打刻'} · 降園 ${c.checkOut||'未打刻'}</div><p>目視確認：${VERIFY[c.verification]}<br>保護者連絡：${c.parentType||'未提出'}</p>${alarms(c).length?`<div class="notice warning">${esc(alarms(c).join(' / '))}</div>`:''}`,button('閉じる','close-dialog')+button('出欠確認へ','child-check',`data-id="${c.id}"`)+button('連絡を開く','child-contact',`data-id="${c.id}"`,'primary'));}
  else if(action==='child-check'){closeDialog();expandedChecks.add(c.id);checkFilter='all';checkClass=c.classroom;navigate('#checks');setTimeout(()=>$(`#check-${c.id}`)?.scrollIntoView({block:'center'}),50);}
  else if(action==='child-contact'){closeDialog();navigate(`#contact/${c.id}/${TODAY}`);}
  else if(action==='toggle-check'){expandedChecks.has(id)?expandedChecks.delete(id):expandedChecks.add(id);render();}
  else if(action==='refresh-checks'){render();}
  else if(action==='all-checks'){checkClass='';checkFilter='all';commitNavigate('#checks');}
  else if(['verify','punch-cancel','revoke-contact'].includes(action)){if(action==='verify'&&value===c.verification){toast('現在と同じ確認状態です。');return;}correctionDialog(c,action,value);}
  else if(action==='confirm-correction'){confirmCorrection();}
  else if(action==='record-contact'){
    const method=$(`#method-${id}`).value,status=$(`#absence-${id}`).value,note=$(`#note-${id}`).value.trim();
    if(!status||!note){$(`#contact-error-${id}`).innerHTML=errorBlock('欠席理由と連絡内容・訂正理由を入力してください。');return;}
    if(scenario==='error'){$(`#contact-error-${id}`).innerHTML=errorBlock('保存できませんでした。入力は保持しています。');return;}
    appendLog(c,'電話・口頭連絡の受付',c.confirmed?'受付あり':'受付なし',`${method} / ${VERIFY[status]}`,note);c.confirmed={method,status,note};render();toast('連絡受付と操作した職員、理由を記録しました。');
  }
  else if(action==='reply-choice'){touchReply(el.dataset.field,value);render();}
  else if(action==='jump-reply'){$('.reply-form').scrollIntoView({block:'start',behavior:'smooth'});}
  else if(action==='temperature-whole'){touchReply('temperature',`${value}.${entry().working.temperature.split('.')[1]||''}`);render();}
  else if(action==='temperature-fraction'){touchReply('temperature',`${entry().working.temperature.split('.')[0]||''}.${value}`);render();}
  else if(action==='date-prev'){navigate(`#contact/${currentChild}/${shiftDate(contactDate,-1)}`);}
  else if(action==='date-next'){navigate(`#contact/${currentChild}/${shiftDate(contactDate,1)}`);}
  else if(action==='date-today'){navigate(`#contact/${currentChild}/${TODAY}`);}
  else if(action==='save-draft'){if(saveReply())toast('下書きを保存しました。未送信のままです。');render();}
  else if(action==='publish'){
    modal={type:'publish'};const r=entry();
    openDialog('この内容を保護者に公開しますか',`<p>${childById(currentChild).name} / ${contactDate}</p><div class="contact-note">${Object.entries(FIELDS).map(([k,l])=>`<p><strong>${l}</strong>${esc(r.working[k]||'未入力')}</p>`).join('')}</div><p class="small muted mt">このモックでは実際の公開・送信は行いません。</p><div id="modal-error"></div>`,button('修正に戻る','close-dialog')+button('公開する（試用）','confirm-publish','','primary'));
  }
  else if(action==='confirm-publish'){if(!saveReply(true)){$('#modal-error').innerHTML=scenario==='error'?modalSaveError(entry().error):errorBlock(entry().error);return;}closeDialog();render();toast('公開済みに切り替わりました（このタブ内の再現）。');}
  else if(action==='discard-reply'){modal={type:'discard'};openDialog('変更を取り消しますか','<p>最後に保存した内容に戻します。</p>',button('入力に戻る','close-dialog')+button('変更を取り消す','confirm-discard'));}
  else if(action==='confirm-discard'){const r=entry();r.working={...r.saved};r.dirty=false;r.error='';closeDialog();render();}
  else if(action==='save-navigate'){if(!saveReply()){$('#modal-error').innerHTML=scenario==='error'?modalSaveError(entry().error):errorBlock(entry().error);return;}const target=modal.target;closeDialog();commitNavigate(target);toast('下書きを保存して移動しました。未送信のままです。');}
  else if(action==='recover-error'){scenario='partial';$('#scenario').value='partial';entry().error='';$('#modal-error').innerHTML='<p class="notice success">試用の保存エラーを解除しました。もう一度確定してください。</p>';}
  else if(action==='discard-navigate'){const r=entry();r.working={...r.saved};r.dirty=false;r.error='';const target=modal.target;closeDialog();commitNavigate(target);}
  else if(action==='pickup-hour'){kiosk.hour=value;if(!availableMinutes(value,closedAt).includes(kiosk.minute))kiosk.minute='';kiosk.error='';render();}
  else if(action==='pickup-minute'){kiosk.minute=value;kiosk.error='';render();}
  else if(action==='pickup-person'){kiosk.person=value;render();}
  else if(action==='pickup-snack'){kiosk.snack=value;render();}
  else if(action==='actual-person'){kiosk.actualPerson=value;render();}
  else if(action==='kiosk-start'){kiosk.step='classes';kiosk.error='';render();}
  else if(action==='kiosk-class'){kiosk.className=value;kiosk.step='names';render();}
  else if(action==='kiosk-child'){kiosk.childId=id;kiosk.className=c.classroom;kiosk.step=c.checkOut?'done':c.checkIn?'departure':'arrival';kiosk.error='';kiosk.actualPerson='';render();}
  else if(action==='kiosk-arrive'){if(allowedTime(kioskNow,closedAt)){kiosk.step='pickup';Object.assign(kiosk,{hour:'',minute:'',person:'',snack:'',error:''});}render();}
  else if(action==='kiosk-cancel'){modal={type:'kiosk-cancel'};openDialog('お迎え予定の入力を取り消しますか','<p>入力内容を破棄して、最初の画面に戻ります。この操作では登録しません。</p>',button('入力に戻る','close-dialog')+button('取り消して戻る','confirm-kiosk-cancel'));}
  else if(action==='confirm-kiosk-cancel'){Object.assign(kiosk,{step:'classes',hour:'',minute:'',person:'',snack:'',error:''});closeDialog();render();}
  else if(action==='kiosk-confirm'){if(checkKioskBeforeSave())kiosk.step='confirm';render();}
  else if(action==='kiosk-edit'){kiosk.step='pickup';kiosk.error='';render();}
  else if(action==='kiosk-commit'){if(checkKioskBeforeSave()){const pupil=childById(kiosk.childId);pupil.checkIn ||= kioskNow;pupil.verification='present';kiosk.step='done';}render();}
  else if(action==='kiosk-depart'){
    kiosk.error=!kiosk.actualPerson?'お迎えに来た人を選んでください。':!allowedTime(kioskNow,closedAt)?'閉園時間を過ぎているため受付できません。':scenario==='error'?'保存できませんでした。入力内容は保持しています。':'';
    if(!kiosk.error){childById(kiosk.childId).checkOut=kioskNow;kiosk.step='done';}render();
  }
  else if(action==='kiosk-fullscreen'){toast('全画面を終了する操作を再現しました。終了ボタンは画面下部に小さく配置する案です。');}
  else if(action==='save-settings'){const value=$('#closing-time').value;settingError=!value?'閉園時刻を入力してください。':scenario==='error'?'設定を保存できませんでした。入力内容は保持しています。':'';if(settingError){const oldValue=value;render();$('#closing-time').value=oldValue;return;}closedAt=value;savedSetting=true;render();toast('閉園時刻をモックに反映しました。');}
});

document.addEventListener('input',event=>{
  const el=event.target;
  if(el.dataset.replyField){touchReply(el.dataset.replyField,el.value);updateReplyStatus();}
  if(el.id==='roster-search' || el.id==='contact-search'){
    if(event.isComposing)return;
    const position=el.selectionStart;
    if(el.id==='roster-search')rosterSearch=el.value;else contactSearch=el.value;
    const id=el.id;render();$('#'+id).focus();$('#'+id).setSelectionRange(position,position);
  }
});
document.addEventListener('change',event=>{
  const el=event.target,v=el.value;
  if(el.dataset.replyField){touchReply(el.dataset.replyField,v);updateReplyStatus();return;}
  const handlers={
    'roster-class':()=>{rosterClass=v;}, 'roster-date':()=>{if(v)rosterDate=v;},
    'check-class':()=>{checkClass=v;},'check-filter':()=>{checkFilter=v;},'check-layout':()=>{checkLayout=v;},'check-date':()=>{if(v)checkDate=v;},
    'contact-class':()=>{contactClass=v;},'contact-sort':()=>{contactSort=v;},'contact-list-date':()=>{if(v)contactDate=v;},
    'pickup-exact':()=>{kiosk.minute=v;kiosk.error='';},
    'kiosk-scene':()=>{kiosk.step=v;kiosk.error='';if(v==='departure')kioskNow='16:30';},
    'kiosk-now':()=>{if(v)kioskNow=v;},
  };
  if(handlers[el.id]){handlers[el.id]();render();}
  if(el.id==='contact-date'&&v){el.value=contactDate;navigate(`#contact/${currentChild}/${v}`);}
});
$('#scenario').addEventListener('change',event=>{
  const wasError=scenario==='error';scenario=event.target.value;
  // Leave failed input intact when recovering, including open correction dialogs.
  if(!wasError){const r=entry();r.saved=replyPreset(scenario);r.working={...r.saved};r.published=null;r.status='draft';r.dirty=false;r.savedOnce=scenario!=='empty';r.error='';presetKiosk();}
  else {entry().error='';kiosk.error='';}
  if($('#dialog').open&&modal?.type?.includes('verify'))$('#modal-error').innerHTML='';
  render();toast(wasError?'エラーを解除しました。入力内容を保持したまま再試行できます。':'試用する入力状態を切り替えました。');
});
$('#input-style').addEventListener('change',event=>{inputStyle=event.target.value;render();});
$('#preview-width').addEventListener('change',event=>{$('#preview-shell').className=`preview-shell ${event.target.value==='wide'?'':event.target.value}`;});
$('#reset').addEventListener('click',()=>{children=makeChildren();replies.clear();expandedChecks.clear();closedAt='19:00';savedSetting=false;scenario='partial';$('#scenario').value='partial';Object.assign(kiosk,{step:'pickup',childId:2,className:CLASSES[0],actualPerson:'',error:''});kioskNow='08:15';presetKiosk();if($('#dialog').open)closeDialog();render();toast('架空の試用データを初期状態に戻しました。');});
$('#review-notes').addEventListener('click',()=>{modal={type:'notes'};openDialog('合意事項と、モックで確認する点',`<h3 class="mt">確認できた内容</h3><ul><li>トップの人数表示を維持。子どもの名前はクラス別の別ページへ。</li><li>在園・降園・お休み・未登園の4区分。</li><li>訂正理由と訂正した人を必ず記録し、出欠確認に留まる。</li><li>閉園時間以降のボタンを非表示にし、入力を受け付けない。</li><li>同じ子どもの前日・翌日に移動。未送信は未送信と表示。</li><li>既存入力項目を残し、早く入力できるUIを試す。</li></ul><h3>今回の仮置き・比較案</h3><ul><li>訂正者はログイン中の職員を固定表示。変更前後と日時も記録。</li><li>閉園は19:00の例。ちょうどの時刻を含めて制限し、現在時刻が閉園後の場合も受付終了。</li><li>連絡はボタン選択と従来プルダウンを比較。</li><li>未保存で移動する場合は、下書き保存・破棄・入力に戻るから選ぶ。</li><li>公開時は内容確認。既存の公開済み連絡の公開取消は今回の対象外。</li><li>連絡履歴の表と、名前一覧の配置は試作案。</li></ul><p class="small muted">基準：最新配備記録の06951a6（2026-09-23）。架空データだけの独立したモックです。実DB・外部通信・送信処理なし。再読み込みするとリセットします。</p>`,button('閉じる','close-dialog','','primary'));});
$('#dialog').addEventListener('cancel',()=>{modal=null;});
window.addEventListener('hashchange',()=>{
  if(page==='contact'&&entry().dirty&&location.hash!==lastRoute){const target=location.hash;history.replaceState(null,'',lastRoute);navigate(target);return;}
  applyRoute();
});
presetKiosk();applyRoute();
