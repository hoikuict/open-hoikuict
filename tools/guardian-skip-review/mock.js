// All state in this mock is fictional and confined to this page.
document.querySelector('.tag').textContent = '確認用モック・架空データ';
const reviewControls = document.createElement('section');
reviewControls.className = 'card';
reviewControls.style.border = '2px solid #14716b';
reviewControls.innerHTML = `<h2>確認用：姓名がない保護者を無視して続ける</h2>
  <p>架空データで操作を確認する画面です。実際の取り込みにはまだ使えません。保存するCSVも確認用です。</p>
  <label>確認する状態 <select id="reviewScenario">
    <option value="partial">一部入力：保護者①の姓名が未分割</option>
    <option value="complete">入力済み：保護者①②とも入力済み</option>
    <option value="empty">未入力：元表をまだ選んでいない</option>
    <option value="error">エラー：姓名不足と別の保護者のメール不正</option>
  </select></label><p class="hint">状態を切り替えると、この確認用画面の編集内容をリセットします。</p>`;
document.querySelector('main').prepend(reviewControls);
const reviewPanel = document.createElement('section');
reviewPanel.id = 'guardian-skip';
reviewPanel.className = 'card';
reviewPanel.innerHTML = `<h2>保護者の姓名が未入力の場合</h2>
  <label><input id="skipIncompleteGuardian" type="checkbox"> 姓名が未入力の保護者を無視して続ける</label>
  <p>チェックすると、姓または名が空欄の保護者は、電話・メール・勤務先を含むその人の情報すべてを今回のCSVに出しません。家庭・園児と、姓名が揃っている保護者は出力します。</p>
  <p class="hint">入力内容は画面に残ります。チェックを外すと元に戻せます。登録済みの保護者情報を削除する操作ではありません。</p>
  <p id="skipGuardianSummary" role="status"></p><ul id="skipGuardianList"></ul>`;
section.before(reviewPanel);
const reviewPreview = document.createElement('details');
reviewPreview.className = 'card';
reviewPreview.innerHTML = '<summary>保存した確認用CSVの内容</summary><pre id="reviewCSV" style="white-space:pre-wrap;overflow-wrap:anywhere">保存ボタンを押すと表示します。</pre>';
section.after(reviewPreview);
const originalReviewRender = render;
render = function() {
  originalReviewRender();
  const omitted = [], missing = [];
  selectedGroups().forEach((g, rowIndex) => {
    for (let slot = 0; slot < 2; slot++) {
      if (!reviewMissingGuardian(g, slot)) continue;
      const label = `${g.line}行・保護者${['①', '②'][slot]}`;
      missing.push(label);
      if (!reviewSkipGuardian(g, slot)) continue;
      omitted.push(label);
      const tr = $('familyBody').rows[rowIndex];
      const note = document.createElement('small');
      note.textContent = `保護者${['①', '②'][slot]}：今回は取り込まない`;
      note.className = 'warn';
      tr.cells[0].append(note);
      for (let field = 0; field < 10; field++) {
        const cell = tr.cells[6 + slot * 10 + field];
        cell.style.background = '#f1f3f3';
        cell.querySelector('input').readOnly = true;
        cell.querySelector('input').title = '今回は出力しません。編集するには上のチェックを外してください。';
      }
    }
  });
  $('skipIncompleteGuardian').checked = reviewSkipIncomplete;
  $('skipGuardianSummary').textContent = reviewSkipIncomplete
    ? `今回取り込まない保護者：${omitted.length}人。家庭・園児は除外しません。`
    : `姓名が未入力の保護者：${missing.length}人。チェックを入れると、この保護者を除いて保存できます。`;
  $('skipGuardianList').replaceChildren();
  for (const label of omitted) {
    const item = document.createElement('li');
    item.textContent = label + '：連絡先を含めて今回は取り込まない';
    $('skipGuardianList').append(item);
  }
  if (omitted.length) $('familyCount').textContent += ` ／ 今回取り込まない保護者 ${omitted.length}人`;
};
$('skipIncompleteGuardian').onchange = () => {
  reviewSkipIncomplete = $('skipIncompleteGuardian').checked;
  lastFamilyDownload = '';
  render();
};
const originalReviewSave = saveText;
saveText = function(text, name) {
  $('reviewCSV').textContent = text;
  reviewPreview.open = true;
  originalReviewSave(text, '確認用_' + name);
};
function loadReviewScenario(state) {
  reviewSkipIncomplete = false;
  lastFamilyDownload = '';
  existing = [];
  knownFamilies = [];
  familyLoadError = '';
  templateVerified = true;
  $('schemaStatus').textContent = '確認用：家庭24列のテンプレートを確認済みにしています。';
  $('enroll').value = state === 'empty' ? '' : '2026-04-01';
  const headers = ['お子様の名前', 'お子様の名前（ふりがな）', '生年月日', 'クラス', '自宅住所', '自宅電話番号',
    ...guardianSourceNames('①'), ...guardianSourceNames('②'),
    'お子様の名前②', 'お子様の名前（ふりがな）②', '生年月日②', 'クラス②'];
  const firstComplete = state === 'complete';
  const values = ['見本 花子', 'ミホン ハナコ', '2023-01-02', '架空クラス', '架空市の住所', '',
    firstComplete ? '見本 保護者' : '見本保護者', firstComplete ? 'ミホン ホゴシャ' : 'ミホンホゴシャ',
    '保護者', 'guardian1@example.test', '000-0000-0000', '架空の勤務先①', '架空の勤務先住所①', '',
    '見本 太一', 'ミホン タイチ', '保護者', state === 'error' ? 'invalid-mail' : 'guardian2@example.test',
    '000-0000-0001', '架空の勤務先②', '', '', '見本 次郎', 'ミホン ジロウ', '2024-02-03', '架空クラス'];
  const matrix = [{ line: 1, values: headers }, ...(state === 'empty' ? [] : [{ line: 2, values }])];
  book = { epoch: false, sheets: [{ name: '架空の緊急連絡表', target: 'fixture' }], read: async () => matrix };
  $('sheet').replaceChildren(new Option('架空の緊急連絡表', '0'));
  $('sheet').disabled = true;
  rows = convert(matrix, false);
  $('message').textContent = state === 'empty' ? '確認用：元表をまだ選んでいない状態です。' : '確認用の架空データ：1家庭・園児2人・保護者①②';
  $('reviewCSV').textContent = '保存ボタンを押すと表示します。';
  render();
}
$('reviewScenario').onchange = () => loadReviewScenario($('reviewScenario').value);
for (const input of document.querySelectorAll('input[type=file]')) {
  input.disabled = true;
  input.title = 'この確認用モックでは架空データだけを使います。';
}
loadReviewScenario('partial');
