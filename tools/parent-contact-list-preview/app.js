(() => {
  'use strict';
  const $ = id => document.getElementById(id);
  const escape = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const shown = value => value === '' || value === null || value === undefined ? '<span class="muted">—</span>' : escape(value);
  const section = (label, value) => `<div class="cell-section"><span class="cell-label">${escape(label)}</span><div class="pre">${shown(value)}</div></div>`;
  const classes = ['ひよこ組', 'りす組'];
  // All identities and contact contents below are fictional.
  const children = [
    ['青葉 はる', 0, '母'], ['朝日 そら', 0, '父'], ['小野 ひなた', 0, '母'],
    ['川原 つむぎ', 0, '母'], ['高木 みなと', 0, '父'], ['中原 あおい', 0, '母'],
    ['花村 こはる', 1, '母'], ['藤野 りく', 1, '父'], ['森川 すず', 1, '母'], ['若葉 ゆう', 1, '父'],
  ].map(([name, classroom, parent], i) => ({id: i + 1, name, classroom, parent}));
  const samples = [
    {mood:'普通', bedtime:'20:30', wakeup:'06:30', sleep:'夜中に一度起きました。', breakfast:'完食', food:'ごはん、豆腐のみそ汁、卵焼き、バナナ', stool:'普通', count:1, stoolNote:'朝食後にあり', temperature:'36.6', pickup:'16:30', person:'母', snack:'不要', cough:'なし', nose:'なし', medicine:'なし', condition:'体調はいつもどおりです。', note:'週末は公園でたくさん歩きました。落ち葉を見つけるたびに立ち止まって、色や形をじっくり見ていました。\n今朝は少し甘えたい様子でしたが、朝食はしっかり食べています。着替えを1組多めに入れました。'},
    {mood:'良好', bedtime:'21:00', wakeup:'06:45', sleep:'朝までよく眠りました。', breakfast:'少なめ', food:'食パン、ヨーグルト、牛乳', stool:'なし', count:0, stoolNote:'', temperature:'36.8', pickup:'18:00', person:'父', snack:'必要', cough:'なし', nose:'少し', medicine:'なし', condition:'透明な鼻水が少し出ています。', note:'昨日から自分で靴を履こうとしています。時間がかかっても「自分で」とがんばっていました。今日は父がお迎えに行きます。'},
    {mood:'少し眠そう', bedtime:'22:00', wakeup:'06:40', sleep:'寝つくまで少し時間がかかりました。', breakfast:'半分', food:'おにぎり、みそ汁、りんご', stool:'軟らかい', count:1, stoolNote:'いつもより少し軟らかめ', temperature:'36.5', pickup:'17:15', person:'祖母', snack:'不要', cough:'少し', nose:'なし', medicine:'朝食後に服用（家庭）', condition:'今朝、咳が少しありました。', note:'昨夜は寝るのが遅くなりました。日中眠そうでしたら、様子を見ていただけると助かります。'},
  ];
  let state = {date:'2026-09-28', classroom:'', sort:'classroom', view:'content', scenario:'mixed'};
  let currentRows = [];
  let failed = false;
  let lastDetailButton = null;

  function rowsForDate() {
    const offset = (Number(state.date.slice(-2)) + 2) % 3;
    return children.map((child, index) => {
      const data = {...samples[(index + offset) % samples.length]};
      let submitted = true, type = 'present';
      if (state.scenario === 'empty') submitted = false;
      if (state.scenario === 'mixed') {
        submitted = ![1, 8].includes((index + offset) % 10);
        if (index === 5) type = 'sick';
        if (index === 9) type = 'private';
      }
      if (state.scenario === 'partial' || (state.scenario === 'mixed' && index === 3)) {
        for (const key of ['bedtime','sleep','food','stool','stoolNote','mood','medicine','condition']) data[key] = '';
        data.count = null;
        data.person = '';
        data.snack = '';
        data.note = 'お迎えの人は、決まり次第連絡します。';
      }
      return {...child, ...data, submitted, type,
        updated:`${String(7 + (index % 2)).padStart(2,'0')}:${String(12 + index * 4).padStart(2,'0')}`,
        reply: state.scenario === 'empty' ? 'none' : ['published','none','draft','changed'][index % 4],
        absenceTemperature: type === 'sick' ? '38.0' : '',
        symptoms: type === 'sick' ? '発熱、咳' : '',
        diagnosis: type === 'sick' ? '未受診' : '',
        absenceNote: type === 'sick' ? '朝から発熱があるためお休みします。午前中に受診予定です。' : type === 'private' ? '家族の用事でお休みします。' : '',
        // Pickup is stored separately from the parent contact in the deployed app.
        independentPickup: !submitted && state.scenario === 'mixed' && index === 1,
      };
    });
  }
  function visibleRows() {
    const rows = rowsForDate().filter(row => state.classroom === '' || String(row.classroom) === state.classroom);
    if (state.sort === 'unsubmitted_first') rows.sort((a,b) => Number(a.submitted) - Number(b.submitted));
    if (state.sort === 'submitted_first') rows.sort((a,b) => Number(b.submitted) - Number(a.submitted));
    if (state.sort === 'unsent_first') rows.sort((a,b) => Number(a.reply === 'published') - Number(b.reply === 'published'));
    return rows;
  }
  const typeLabel = row => row.type === 'sick' ? '病欠' : row.type === 'private' ? '私用休み' : '出席';
  const replyLabel = row => ({published:'返信済み', none:'未送信（未入力）', draft:'未送信', changed:'未送信の変更あり'}[row.reply]);
  function replyCell(row) {
    return `<span class="reply-label ${row.reply !== 'published' ? 'draft' : ''}">${replyLabel(row)}</span>${row.reply === 'none' ? '' : '<span class="sub">返信者：確認用職員</span>'}`;
  }
  function nameCell(row) {
    return `<div class="name-cell"><div><button class="child-name" data-detail="${row.id}" aria-label="${escape(row.name)}の連絡詳細">${escape(row.name)}</button><span class="sub">${classes[row.classroom]}</span><span class="badge ${!row.submitted ? 'missing' : row.type !== 'present' ? 'absent' : ''}">${row.submitted ? typeLabel(row) : '未提出'}</span>${row.submitted ? `<span class="sub">${state.date} ${row.updated}<br>提出者：${escape(row.name.split(' ')[0])} ${row.parent}</span>` : ''}</div></div>`;
  }
  function pickupCell(row) {
    if (row.submitted && row.type !== 'present') return '<span class="muted">対象外</span>';
    if (!row.submitted && !row.independentPickup) return shown('');
    return `${shown(row.pickup)}<span class="sub">迎え：${shown(row.person)}</span><span class="sub">補食：${shown(row.snack)}</span>${row.independentPickup ? '<span class="sub">予定のみ登録あり</span>' : ''}`;
  }
  function contentCells(row) {
    if (!row.submitted) return [shown(''), shown(''), shown(''), shown(''), shown(''), pickupCell(row), '<span class="muted">保護者からの連絡は未提出です。</span>', shown('')];
    if (row.type !== 'present') {
      const outside = '<span class="muted">対象外</span>';
      return [outside, outside, outside, outside, row.type === 'sick' ? `${shown(row.absenceTemperature)}℃` : outside, outside,
        section('欠席理由', typeLabel(row)) + section('備考', row.absenceNote),
        row.type === 'sick' ? section('症状', row.symptoms) + section('医師から伝えられた診断名', row.diagnosis) : outside];
    }
    const stool = `${shown(row.stool)}${row.count !== null && row.count !== undefined ? ` <span class="stool-count">（${row.count}回）</span>` : ''}${row.stoolNote ? `<span class="sub pre">${escape(row.stoolNote)}</span>` : ''}`;
    const sleep = `${shown(row.bedtime)} 〜 ${shown(row.wakeup)}${row.sleep ? `<span class="sub pre">${escape(row.sleep)}</span>` : ''}`;
    return [shown(row.mood), stool, sleep, section('朝食・食欲', row.breakfast) + section('食べた内容', row.food),
      row.temperature ? escape(row.temperature) + '℃' : shown(''), pickupCell(row),
      section('体調メモ', row.condition) + section('園への連絡事項', row.note),
      section('咳', row.cough) + section('鼻水', row.nose) + section('服薬', row.medicine)];
  }
  function renderContent() {
    const heads = [['名前',208],['機嫌',90],['排便',150,'前日夕方から連絡時まで'],['睡眠',140,'就寝 〜 起床'],['食事',190],['検温',88],['お迎え',144],['子どもの様子・連絡',360],['症状・服薬',180],['園返信',152]];
    return `<table class="content-table"><caption hidden>保護者からの連絡内容一覧</caption><colgroup>${heads.map(()=>'<col>').join('')}</colgroup><thead><tr>${heads.map(([label,width,note])=>`<th scope="col">${label}${note?`<small>${note}</small>`:''}</th>`).join('')}</tr></thead><tbody>${currentRows.map(row=>`<tr><td>${nameCell(row)}</td>${contentCells(row).map(cell=>`<td>${cell}</td>`).join('')}<td>${replyCell(row)}</td></tr>`).join('')}</tbody></table>`;
  }
  function renderStatus() {
    // Same columns and sort options as the deployed submission list.
    return `<table class="status-table"><caption hidden>保護者連絡の提出状況一覧</caption><thead><tr>${['園児','クラス','提出状況','園返信','連絡内容','提出者','更新日時','操作'].map(x=>`<th scope="col">${x}</th>`).join('')}</tr></thead><tbody>${currentRows.map(row=>`<tr><td>${escape(row.name)}</td><td>${classes[row.classroom]}</td><td><span class="badge ${row.submitted?'':'missing'}">${row.submitted?'提出済み':'未提出'}</span></td><td>${replyCell(row)}</td><td>${row.submitted?typeLabel(row):'—'}</td><td>${row.submitted?escape(row.name.split(' ')[0])+' '+row.parent:'—'}</td><td>${row.submitted?state.date+' '+row.updated+' JST':'—'}</td><td><button data-detail="${row.id}" aria-label="${escape(row.name)}の連絡詳細">詳細</button></td></tr>`).join('')}</tbody></table>`;
  }
  function render() {
    currentRows = visibleRows();
    const total = currentRows.length, submitted = currentRows.filter(r=>r.submitted).length;
    const absent = currentRows.filter(r=>r.submitted && r.type !== 'present').length;
    $('counts').innerHTML = failed ? '' : `対象 <strong>${total}</strong>人　提出済み <strong>${submitted}</strong>人　未提出 <strong>${total-submitted}</strong>人　欠席 <strong>${absent}</strong>人`;
    $('table-title').textContent = `${state.date.replaceAll('-','/')}　${state.classroom === '' ? 'すべてのクラス' : $('classroom').querySelector(`option[value="${state.classroom}"]`).textContent}`;
    $('table-hint').textContent = state.view === 'content' ? '横にスクロールできます。名前と見出しは固定表示です。' : '現行と同じ項目で提出状況を確認できます。';
    document.querySelectorAll('[data-view]').forEach(button=>button.setAttribute('aria-pressed', String(button.dataset.view === state.view)));
    if (failed) {
      $('results').innerHTML = '<div class="error-state" role="alert"><strong>連絡内容を読み込めませんでした。</strong><p>日付・クラス・表示順は保持しています。</p><button id="retry">再試行</button></div>';
      $('retry').onclick = () => {failed=false; render();};
    } else if (!total) {
      $('results').innerHTML = '<div class="empty-state">対象の園児が見つかりません。クラスを変更して表示してください。</div>';
    } else {
      $('results').innerHTML = `<div class="table-scroll" tabindex="0" role="region" aria-label="連絡一覧。左右にスクロールできます">${state.view === 'content' ? renderContent() : renderStatus()}</div>`;
    }
  }
  function detailItem(label, value, full=false) {
    return `<div${full?' class="full"':''}><dt>${escape(label)}</dt><dd>${shown(value)}</dd></div>`;
  }
  function openDetail(id, button) {
    const row = currentRows.find(r=>r.id === id);
    if (!row) return;
    lastDetailButton = button;
    $('detail-title').textContent = row.name + ' の保護者連絡';
    $('detail-meta').textContent = `${state.date} / ${classes[row.classroom]}`;
    let body = '<h3>家庭からの連絡</h3>';
    if (!row.submitted) body += '<div class="detail-missing">保護者からの連絡は未提出です。</div>';
    else {
      body += `<p class="detail-context">提出者：${escape(row.name.split(' ')[0])} ${row.parent} / 更新：${state.date} ${row.updated} JST / ${typeLabel(row)}</p><dl>`;
      if (row.type === 'present') {
        [['体温',row.temperature+'℃'],['状態','提出済み'],['就寝',row.bedtime],['起床',row.wakeup],['睡眠メモ',row.sleep],['朝食・食欲',row.breakfast],['食べた内容',row.food],['機嫌',row.mood],['排便の性状（前日夕方から）',row.stool],['排便回数（前日夕方から）',row.count===null?'':row.count+'回'],['排便メモ',row.stoolNote],['咳',row.cough],['鼻水',row.nose],['服薬',row.medicine]].forEach(([label,value])=>body+=detailItem(label,value));
        body += detailItem('体調メモ',row.condition,true) + detailItem('園への連絡事項',row.note,true);
      } else {
        body += detailItem('欠席理由',typeLabel(row));
        if (row.type === 'sick') body += detailItem('現在の体温',row.absenceTemperature+'℃') + detailItem('症状',row.symptoms) + detailItem('医師から伝えられた診断名',row.diagnosis);
        body += detailItem('備考',row.absenceNote,true);
      }
      body += '</dl>';
    }
    if ((row.submitted && row.type === 'present') || row.independentPickup) body += '<h3>お迎え予定（出欠記録）</h3><dl>'+detailItem('降園予定時刻',row.pickup)+detailItem('お迎え予定の人',row.person)+detailItem('補食',row.snack)+'</dl>';
    body += `<h3>園からの連絡</h3><p class="detail-note">${replyLabel(row)}。このモックでは閲覧だけを試せます。本実装では既存の詳細画面で返信します。</p>`;
    if (row.reply !== 'none') body += '<dl>'+detailItem('お昼寝時間','12:30-14:00')+detailItem('体温','36.7')+detailItem('排便','あり')+detailItem('食欲','完食')+detailItem('連絡メモ','園庭で遊びました。好きな遊具を見つけて、楽しそうに繰り返し遊んでいました。',true)+'</dl>';
    $('detail-body').innerHTML = body;
    $('detail').showModal();
    $('detail').scrollTop=0;
  }
  $('results').addEventListener('click', event => {const button=event.target.closest('[data-detail]');if(button)openDetail(Number(button.dataset.detail),button);});
  $('close-detail').onclick = () => $('detail').close();
  $('detail').addEventListener('close',()=>lastDetailButton?.focus({preventScroll:true}));
  $('filters').addEventListener('submit',event=>{
    event.preventDefault();
    state.date=$('date').value;state.classroom=$('classroom').value;state.sort=$('sort').value;
    failed=state.scenario==='error';render();
  });
  document.querySelectorAll('[data-view]').forEach(button=>button.onclick=()=>{state.view=button.dataset.view;render();});
  $('scenario').onchange=()=>{state.scenario=$('scenario').value;failed=state.scenario==='error';render();};
  $('review-toggle').onclick=()=>{const expanded=$('review-toggle').getAttribute('aria-expanded')==='true';$('review-toggle').setAttribute('aria-expanded',String(!expanded));$('review-settings').hidden=expanded;};
  $('wide').onclick=()=>{const wide=document.body.classList.toggle('wide');$('wide').setAttribute('aria-pressed',String(wide));$('wide').textContent=wide?'メニューを表示':'一覧を広く表示';};
  $('reset').onclick=()=>{
    state={date:'2026-09-28',classroom:'',sort:'classroom',view:'content',scenario:'mixed'};
    $('date').value=state.date;$('classroom').value='';$('sort').value='classroom';$('scenario').value='mixed';
    failed=false;$('feedback').textContent='';render();
  };
  $('staff-sidebar').addEventListener('click',event=>{
    const link=event.target.closest('a');if(!link)return;event.preventDefault();
    if(link.textContent.trim()==='日次連絡'){state.view='content';render();}
    else $('feedback').textContent='このモックでは「日次連絡」の一覧と詳細を試せます。';
  });
  render();
})();
