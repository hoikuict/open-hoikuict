'use strict';

const $ = id => document.getElementById(id);
const sectionDefs = [
  ['overview', '対象期間の子どもの姿', '具体的な姿の要約'],
  ['growth', '育ちと変化', '前回からの育ちや変化'],
  ['support', '保育者の援助と振り返り', '有効だった援助と振り返り'],
  ['family', '家庭との連携', '家庭との共有や連携'],
  ['next-focus', '次の期間に大切にしたいこと', '次の計画につなぐ視点'],
];
const sampleText = [
  '砂場で「どうぞ」とカップを渡し、友だちと一緒に遊ぶ姿が増えた。',
  '自分から遊びに誘うようになった。',
  'カップを二つ置くと、友だちと交代して遊んだ。',
  '砂場でのやりとりをご家庭にも伝えた。',
  '友だちが誘いに応えたときの表情も見守りたい。',
];
const addition = '友だちが受け取ると、にっこり笑った。';
const baseMonth = '2026-09';
const states = { new: '未作成', draft: '下書き', returned: '差戻し', review: 'レビュー待ち' };
const hints = {
  edit: '「友だちが受け取ると、にっこり笑った。」と書き足した状態です。「詳細・承認へ」を押し、どの文章が残るか試してください。',
  recipient: '「レビュー依頼」を押してください。案内が出たら「試す条件を変える」で管理者を1人にして、もう一度依頼できます。',
  phone: '下の入力画面で「対象期間の子どもの記録」を押すと、参考にする記録に移動します。',
};
const records = new Map();
let currentMonth = baseMonth;
let view = 'editor';
let pending = null;
let lastField = null;
let surveyCase = '';

function blankRecord() {
  return { status: 'new', body: sectionDefs.map(() => ''), checked: false, awaiting: [] };
}
function record() {
  if (!records.has(currentMonth)) records.set(currentMonth, blankRecord());
  return records.get(currentMonth);
}
function setMessage(id, message = '') {
  $(id).textContent = message;
  $(id).hidden = !message;
}
function show(viewName, focus = true) {
  view = viewName;
  const recipients = record().awaiting;
  $('notice-count').textContent = 'この児童票の未確認の依頼通知（見本）：' + recipients.length + '件' + (recipients.length ? '（' + recipients.join('、') + '）' : '');
  for (const name of ['editor', 'detail', 'listing']) $(name).hidden = name !== viewName;
  if (focus) {
    const heading = $({ editor: 'edit-title', detail: 'detail-title', listing: 'list-title' }[viewName]);
    heading.focus({ preventScroll: true });
    heading.scrollIntoView({ block: 'start' });
  }
}
function initFields() {
  for (const [index, [id, title, purpose]] of sectionDefs.entries()) {
    const card = document.createElement('section');
    card.className = 'card';
    const label = document.createElement('label');
    label.htmlFor = id;
    label.textContent = title;
    if (!index) {
      const star = document.createElement('span');
      star.className = 'required';
      star.textContent = ' *';
      label.append(star);
    }
    const field = document.createElement('textarea');
    field.id = id;
    field.rows = index === 0 ? 7 : 5;
    field.maxLength = 5000;
    field.required = index === 0;
    field.placeholder = purpose;
    card.append(label, field);
    $('body-fields').append(card);
  }
}
function iso(date) { return date.toISOString().slice(0, 10); }
function endMonth(value, offset = 0) {
  const [year, month] = value.split('-').map(Number);
  return iso(new Date(Date.UTC(year, Math.floor(month / 3) * 3 + offset, 0))).slice(0, 7);
}
function period() {
  const [year, month] = currentMonth.split('-').map(Number);
  const start = iso(new Date(Date.UTC(year, month - 3, 1)));
  const end = iso(new Date(Date.UTC(year, month, 0)));
  return { start, end, range: (start + '〜' + end).replaceAll('-', '/'), year: month <= 3 ? year - 1 : year };
}
function readBody() { return sectionDefs.map(([id]) => $(id).value); }
function dirty() {
  return record().checked !== $('evidence').checked || readBody().some((body, i) => body !== record().body[i]);
}
function updateDirty() {
  $('dirty-label').textContent = dirty() ? '未保存の変更があります' : record().status === 'new' ? '新しい下書き' : '保存済み';
}
function cancelPending() {
  pending = null;
  $('unsaved').hidden = true;
  $('month').value = currentMonth;
}
function drawEditor(focus = true) {
  cancelPending();
  lastField = null;
  $('overview').removeAttribute('aria-invalid');
  $('overview').removeAttribute('aria-describedby');
  const doc = record();
  const dates = period();
  $('latest-tag').hidden = currentMonth !== baseMonth;
  $('period-note').textContent = dates.range + ' · ' + dates.year + '年度 · 3か月周期';
  $('start-date').value = dates.start;
  $('end-date').value = dates.end;
  $('created').textContent = '対象年度：' + dates.year + '年度 · 作成日時：' + (doc.status === 'new' ? '保存した日時を記録' : '2026/11/08（見本）');
  $('log-range').textContent = dates.range;
  $('log-item').hidden = currentMonth !== baseMonth;
  $('no-logs').hidden = currentMonth === baseMonth;
  $('saved-bar').hidden = doc.status === 'new';
  $('saved-desc').textContent = '保存済みの' + states[doc.status] + 'を開いています。変更はこの児童票に上書き保存されます。';
  sectionDefs.forEach(([id], i) => { $(id).value = doc.body[i]; });
  $('evidence').checked = doc.checked;
  setMessage('saved-notice');
  setMessage('save-error');
  updateDirty();
  show('editor', focus);
}
function drawDetail(focus = true) {
  const doc = record();
  const dates = period();
  $('detail-title').textContent = '見本 あおい 児童票（' + dates.range + '）';
  $('detail-period').textContent = '対象期間: ' + dates.start + '〜' + dates.end;
  $('detail-status').textContent = $('report-status').textContent = states[doc.status];
  $('detail-status').dataset.status = doc.status;
  $('report-year').textContent = dates.year + '年度';
  $('edit').hidden = $('request').hidden = doc.status === 'review';
  $('withdraw').hidden = doc.status !== 'review';
  $('return-reason').hidden = doc.status !== 'returned';
  setMessage('review-error');
  setMessage('review-result');
  $('report-body').replaceChildren();
  sectionDefs.forEach(([, title], index) => {
    const item = document.createElement('section');
    item.className = 'report-part';
    const heading = document.createElement('h3');
    heading.textContent = title;
    const body = document.createElement('p');
    body.textContent = doc.body[index];
    item.append(heading, body);
    if (doc.checked) {
      const tag = document.createElement('small');
      tag.textContent = '子どもの記録';
      item.append(tag);
    }
    $('report-body').append(item);
  });
  show('detail', focus);
}
function drawList(target) {
  const status = record().status;
  $('list-title').textContent = target === 'list' ? '児童票作成状況' : '見本 あおいの児童票一覧';
  $('list-period').textContent = '対象期間　' + period().range;
  $('list-status').textContent = '状態　' + states[status];
  $('open-record').textContent = { new: '入力する', draft: '続きを入力', returned: '続きを入力', review: '開く' }[status];
  show('listing');
}
function go(target) {
  cancelPending();
  if (target.month) {
    currentMonth = target.month;
    return record().status === 'review' ? drawDetail() : drawEditor();
  }
  if (target.page === 'detail') return drawDetail();
  drawList(target.page);
}
function navigate(target) {
  if (view === 'editor' && dirty()) {
    pending = target;
    $('unsaved').hidden = false;
    $('unsaved-title').focus();
    return;
  }
  go(target);
}
function save(target) {
  const field = $('overview');
  if (!field.value.trim()) {
    setMessage('save-error', '対象期間の子どもの姿を入力してください。入力したほかの欄は残っています。');
    field.setAttribute('aria-invalid', 'true');
    field.setAttribute('aria-describedby', 'save-error');
    field.focus();
    field.reportValidity();
    return;
  }
  if ($('fail').checked) {
    $('fail').checked = false;
    setMessage('save-error', '保存できませんでした。入力内容は残っています。もう一度保存してください。');
    $('save-error').scrollIntoView({ block: 'center' });
    return;
  }
  const doc = record();
  doc.body = readBody();
  doc.checked = $('evidence').checked;
  if (doc.status === 'new') doc.status = 'draft';
  if (target) return go(target);
  drawEditor();
  setMessage('saved-notice', '下書きを保存しました。対象期間は ' + period().range + ' です。');
}
function tryMonth(value) {
  if (!value || !$('month').validity.valid) {
    $('month').reportValidity();
    return;
  }
  const month = endMonth(value);
  if (month === currentMonth) { $('month').value = currentMonth; return; }
  navigate({ month });
}
function loadExample(example, detail = false) {
  records.clear();
  currentMonth = baseMonth;
  const doc = record();
  if (example !== 'new') {
    doc.status = example === 'returned' ? 'returned' : 'draft';
    doc.body = example === 'partial' ? [sampleText[0], '', '', '', ''] : [...sampleText];
    doc.checked = true;
  }
  $('example').value = example;
  drawEditor(false);
  if (example === 'partial') {
    $('overview').value += '\n' + addition;
    updateDirty();
  }
  if (detail && example !== 'new' && example !== 'partial') drawDetail(false);
}
function startCase(name) {
  surveyCase = Object.hasOwn(hints, name) ? name : 'edit';
  const recipient = surveyCase === 'recipient', phone = surveyCase === 'phone';
  document.querySelectorAll('[data-case]').forEach(button => button.setAttribute('aria-pressed', String(button.dataset.case === surveyCase)));
  $('settings').open = recipient;
  $('admins').value = recipient ? '0' : '1';
  $('fail').checked = false;
  $('phone').checked = phone;
  $('surface').classList.toggle('phone-width', phone);
  $('instruction').textContent = hints[surveyCase];
  loadExample(surveyCase === 'edit' ? 'partial' : 'filled', recipient);
}

initFields();
document.querySelectorAll('[data-case]').forEach(button => button.onclick = () => startCase(button.dataset.case));
document.querySelectorAll('[data-to]').forEach(button => button.onclick = () => navigate({ page: button.dataset.to }));
$('example').onchange = () => {
  const example = $('example').value;
  loadExample(example, surveyCase === 'recipient');
  $('instruction').textContent = example === 'new' ? '「対象期間の子どもの姿」を書いて「下書きを保存」を押してください。' :
    example === 'partial' ? hints.edit : view === 'detail' ? '「レビュー依頼」を押して、児童票の状態を確かめてください。' : '児童票に書き足して、保存やレビュー依頼を試せます。';
};
$('phone').onchange = () => $('surface').classList.toggle('phone-width', $('phone').checked);
$('entry-form').oninput = event => {
  lastField = event.target;
  $('overview').removeAttribute('aria-invalid');
  $('overview').removeAttribute('aria-describedby');
  setMessage('save-error');
  setMessage('saved-notice');
  updateDirty();
};
$('entry-form').onsubmit = event => { event.preventDefault(); save(null); };
$('save-go').onclick = () => save(pending);
$('discard').onclick = () => { if (pending) go(pending); };
$('stay').onclick = () => { cancelPending(); (lastField || $('overview')).focus(); };
$('month').onchange = () => tryMonth($('month').value);
$('show-month').onclick = () => tryMonth($('month').value);
for (const [id, offset] of [['prev', -3], ['next', 3]]) {
  $(id).onclick = () => navigate({ month: endMonth(currentMonth, offset) });
}
$('latest').onclick = () => { if (currentMonth !== baseMonth) navigate({ month: baseMonth }); };
$('edit').onclick = () => drawEditor();
$('open-record').onclick = () => record().status === 'review' ? drawDetail() : drawEditor();
$('print').onclick = () => window.print();
$('request').onclick = () => {
  const doc = record();
  if (doc.status !== 'draft' && doc.status !== 'returned') return;
  if ($('admins').value === '0') {
    setMessage('review-result');
    setMessage('review-error', '確認を頼める管理者がいません。園のアカウント担当者にお知らせください。');
    return;
  }
  doc.status = 'review';
  doc.awaiting = ['見本 園長'];
  drawDetail(false);
  setMessage('review-result', 'レビューを依頼しました。');
  $('detail-title').focus();
};
$('withdraw').onclick = () => {
  record().status = 'draft';
  record().awaiting = [];
  drawDetail(false);
  setMessage('review-result', 'レビューを取り下げました。');
  $('edit').focus();
};
startCase(new URLSearchParams(location.search).get('case'));
