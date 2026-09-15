import {norm, isId, transforms, makeTargets, suggestMapping, convertRows, validateResult, csvText, saveProfile, loadProfile} from './core.js';
import {readSource, sourceTable} from './files.js';

const $ = id => document.getElementById(id);
const schemas = JSON.parse($('schemas').textContent);
const offline = document.body.dataset.offline === '1';
let book = null, table = null, targets = [], mappings = {}, result = null, issues = [], activeDataset = '', page = 0, sequence = 0, unsaved = false;
const PAGE_SIZE = 30;
function element(tag, text, className) { const node = document.createElement(tag); if (text != null) node.textContent = text; if (className) node.className = className; return node; }
function message(text = '', error = false) { $('message').textContent = text; $('message').className = error ? 'error' : ''; }
function options() { return {mode: $('mode').value, childCount: Number($('child-count').value), familyKey: $('family-key').value === '' ? null : Number($('family-key').value), guardianColumn: $('guardian-column').value === '' ? null : Number($('guardian-column').value), guardianFirst: $('guardian-first').value, guardianSecond: $('guardian-second').value, epoch: book?.epoch || false, allowIds: $('allow-ids').checked, headerDepth: Number($('header-depth').value)}; }
function option(value, label) { const node = element('option', label); node.value = String(value); return node; }
function invalidate() {
  result = null; issues = []; $('result-content').hidden = true;
  for (const id of ['result-table', 'result-tabs', 'result-issues', 'result-actions', 'pagination', 'result-warnings']) $(id).replaceChildren();
  $('result-status').textContent = '設定を変更しました。「変換結果を確認する」で作り直してください。'; $('review-warnings').checked = false;
}
function sourceOptions(select, selected = null) {
  select.replaceChildren(option('', '使わない / 補完値を使う'));
  table?.headers.forEach((h, i) => select.append(option(i, h.label)));
  select.value = selected == null ? '' : String(selected);
}
function updateUnused() {
  const used = new Set(targets.filter(t => !isId(t.header) || $('allow-ids').checked).map(t => mappings[t.key]?.column).filter(c => c != null));
  if (['combined', 'guardian_rows'].includes($('mode').value) && $('family-key').value !== '') used.add(Number($('family-key').value));
  if ($('mode').value === 'guardian_rows' && $('guardian-column').value !== '') used.add(Number($('guardian-column').value));
  const unused = (table?.headers || []).filter((_, i) => !used.has(i));
  $('unused-count').textContent = `対応していない元の列：${unused.length}列`;
  $('unused-columns').replaceChildren(...unused.map(h => element('span', h.label, 'chip')));
  return unused;
}

function renderSource() {
  const output = element('table'), head = element('thead'), body = element('tbody'), header = element('tr');
  header.append(element('th', '元の行'));
  for (const col of table.headers) header.append(element('th', col.label));
  head.append(header);
  for (const row of table.rows.slice(0, 4)) {
    const tr = element('tr'); tr.append(element('td', row.line));
    table.headers.forEach((_, i) => tr.append(element('td', String(row.values[i] ?? '').slice(0, 150)))); body.append(tr);
  }
  output.append(head, body); $('source-preview').replaceChildren(output);
  $('source-status').textContent = `${book.encoding} ・ ${table.rows.length}行 × ${table.headers.length}列。最初の4行を表示しています。`;
}

function renderMappings() {
  $('combined-options').hidden = !['combined', 'guardian_rows'].includes($('mode').value);
  $('child-count-label').hidden = $('mode').value !== 'combined';
  $('guardian-options').hidden = $('mode').value !== 'guardian_rows';
  $('mapping-fields').replaceChildren();
  const groups = new Map();
  for (const target of targets) {
    const mapping = mappings[target.key] ||= {column: null, transform: target.defaultTransform, fallback: '', replacements: ''};
    const guardian = target.header.match(/^保護者([①②])/);
    const name = guardian ? `${target.group} / 保護者${guardian[1]}` : target.group;
    if (!groups.has(name)) {
      const details = element('details', null, 'map-section'); details.open = !guardian;
      details.append(element('summary', name)); groups.set(name, details); $('mapping-fields').append(details);
    }
    const row = element('div', null, 'map-grid'); row.dataset.search = `${target.group}${target.header}`;
    row.append(element('div', target.header, 'map-label'));
    const sourceLabel = element('label', '元の列'), source = element('select');
    source.setAttribute('aria-label', `${target.group} ${target.header} 元の列`); sourceOptions(source, mapping.column);
    source.disabled = isId(target.header) && !$('allow-ids').checked;
    const sample = element('small', '', 'hint');
    function showSample() { const value = mapping.column == null ? '' : table.rows.find(r => norm(r.values[mapping.column]))?.values[mapping.column]; sample.textContent = value == null || value === '' ? '' : `例：${String(value).slice(0, 80)}`; }
    source.onchange = () => { mapping.column = source.value === '' ? null : Number(source.value); showSample(); invalidate(); updateUnused(); unsaved = true; };
    sourceLabel.append(source, sample); showSample(); row.append(sourceLabel);
    const methodLabel = element('label', '変換方法'), method = element('select');
    method.setAttribute('aria-label', `${target.group} ${target.header} 変換方法`);
    Object.entries(transforms).forEach(([key, label]) => method.append(option(key, label))); method.value = mapping.transform;
    method.disabled = isId(target.header);
    method.onchange = () => { mapping.transform = method.value; invalidate(); unsaved = true; }; methodLabel.append(method); row.append(methodLabel);
    const fallbackLabel = element('label', '空欄の補完'), fallback = element('input'); fallback.value = mapping.fallback;
    fallback.setAttribute('aria-label', `${target.group} ${target.header} 空欄の補完`); fallback.placeholder = isId(target.header) ? '補完しません' : '必要な場合だけ'; fallback.disabled = isId(target.header);
    fallback.onchange = () => { mapping.fallback = fallback.value; invalidate(); unsaved = true; }; fallbackLabel.append(fallback); row.append(fallbackLabel);
    if (!isId(target.header)) {
      const replace = element('details'), summary = element('summary', '値の置き換え（クラス名・区分など）'), replacement = element('textarea');
      replacement.setAttribute('aria-label', `${target.group} ${target.header} 値の置き換え`); replacement.placeholder = '例：A組=あお組\nB組=きいろ組'; replacement.value = mapping.replacements;
      replacement.onchange = () => { mapping.replacements = replacement.value; invalidate(); unsaved = true; };
      replace.append(summary, replacement); row.append(replace);
    }
    groups.get(name).append(row);
  }
  filterMappings(); updateUnused();
}
function filterMappings() {
  const query = norm($('mapping-filter').value).toLowerCase();
  for (const row of $('mapping-fields').querySelectorAll('.map-grid')) row.hidden = query && !norm(row.dataset.search).toLowerCase().includes(query);
  for (const group of $('mapping-fields').children) { group.hidden = ![...group.querySelectorAll('.map-grid')].some(r => !r.hidden); if (query && !group.hidden) group.open = true; }
}
function rebuild(suggest = true) {
  targets = makeTargets($('mode').value, Number($('child-count').value), schemas);
  mappings = Object.fromEntries(targets.map(t => [t.key, suggest && table ? suggestMapping(t, table.headers) : {column: null, transform: t.defaultTransform, fallback: '', replacements: ''}]));
  sourceOptions($('family-key')); $('family-key').options[0].textContent = 'まとめない（1行を1家庭とする）';
  sourceOptions($('guardian-column')); $('guardian-column').options[0].textContent = '列を指定してください';
  renderMappings(); invalidate(); $('suggest').disabled = $('convert').disabled = $('save-profile').disabled = !table;
}

function guessHeader(sheet) {
  const known = new Set([...schemas.flatMap(s => s.headers), '氏名', '園児名', 'お子様の名前', '保護者名①', 'フリガナ', 'クラス'].map(norm));
  let best = sheet.rows[0]?.line || 1, score = -1;
  for (const row of sheet.rows.filter(r => r.line <= 30)) {
    const current = row.values.filter(v => known.has(norm(v))).length;
    if (current > score) { score = current; best = row.line; }
  }
  return Math.min(best, 100);
}
async function loadFile(fresh = false) {
  const current = ++sequence;
  book = null; table = null; targets = []; mappings = {}; invalidate(); $('source-preview').replaceChildren(); $('mapping-fields').replaceChildren();
  $('suggest').disabled = $('convert').disabled = $('save-profile').disabled = true; $('sheet').disabled = true;
  message('ファイルを端末内で読み込んでいます…');
  try {
    const loaded = await readSource($('source-file').files[0], {encoding: $('encoding').value, delimiter: $('delimiter').value});
    if (current !== sequence) return;
    const selected = fresh ? 0 : Math.min(Number($('sheet').value) || 0, loaded.sheets.length - 1);
    const sheet = await loaded.read(selected); if (current !== sequence) return;
    book = loaded; $('sheet').replaceChildren(...book.sheets.map((s, i) => option(i, s.name))); $('sheet').value = String(selected); $('sheet').disabled = book.sheets.length < 2;
    if (fresh) { $('header-row').value = String(guessHeader(sheet)); $('header-depth').value = '1'; }
    table = sourceTable(sheet, Number($('header-row').value), Number($('header-depth').value));
    renderSource(); rebuild(); message('読み込みました。元の列と変換先を確認してください。'); unsaved = true;
  } catch (error) { if (current === sequence) { book = null; table = null; $('source-status').textContent = '読み込めませんでした。ファイルや読込設定を確認してください。'; message(error.message, true); } }
}

function buildResult() {
  if (!table || !book) return;
  try {
    result = convertRows(table.rows, targets, mappings, options(), schemas);
    const unused = updateUnused();
    if (unused.length) result.notes.unshift(`変換しない列：${unused.map(h => h.label).join('、')}`);
    result.sourceName = $('source-file').files[0]?.name || '';
    activeDataset = Object.keys(result.outputs)[0]; page = 0; $('review-warnings').checked = false; unsaved = true;
    $('result-content').hidden = false; renderResults(); message('変換結果を作成しました。要確認のセルは表で修正できます。'); $('results').scrollIntoView({behavior: 'smooth', block: 'start'});
  } catch (error) { invalidate(); message(error.message, true); }
}

function renderResults() {
  if (!result) return;
  issues = validateResult(result);
  const counts = Object.entries(result.outputs).map(([key, output]) => `${schemas.find(s => s.id === key).label} ${output.rows.filter(r => r.include).length}件`);
  $('result-status').textContent = `${counts.join(' / ')}　要確認 ${issues.length}項目`;
  $('result-warnings').textContent = result.notes.slice(0, 50).join('\n') + (result.notes.length > 50 ? `\nほか${result.notes.length - 50}件。レポートにすべて含みます。` : '');
  $('review-warnings').parentElement.hidden = !result.notes.length;
  $('result-tabs').replaceChildren();
  for (const [dataset, output] of Object.entries(result.outputs)) {
    const label = schemas.find(s => s.id === dataset).label;
    const button = element('button', `${label} ${output.rows.filter(r => r.include).length}件`, dataset === activeDataset ? 'active-tab' : 'secondary'); button.type = 'button';
    button.onclick = () => { activeDataset = dataset; page = 0; renderResults(); }; $('result-tabs').append(button);
  }
  const activeIssues = issues.filter(i => i.dataset === activeDataset), list = element('ul', null, 'issue-list');
  for (const issue of activeIssues.slice(0, 30)) list.append(element('li', `元の${issue.lines.join('・')}行 / ${issue.header}：${issue.message}`));
  if (activeIssues.length > 30) list.append(element('li', `ほか${activeIssues.length - 30}項目。該当セルにも表示します。`));
  $('result-issues').replaceChildren(list);
  const output = result.outputs[activeDataset], rows = output.rows;
  page = Math.max(0, Math.min(page, Math.ceil(rows.length / PAGE_SIZE) - 1));
  const tableNode = element('table'), head = element('thead'), body = element('tbody'), headings = element('tr');
  headings.append(element('th', '出力 / 元の行')); for (const header of output.headers) headings.append(element('th', header)); head.append(headings);
  const errorMap = new Map();
  for (const issue of activeIssues) { const key = `${issue.rowId}:${issue.header}`; if (!errorMap.has(key)) errorMap.set(key, []); errorMap.get(key).push(issue.message); }
  for (const row of rows.slice(page * PAGE_SIZE, (page + 1) * PAGE_SIZE)) {
    const tr = element('tr'), first = element('td'), include = element('input'), label = element('label', `${row.sourceLines.join('・')}行`); include.type = 'checkbox'; include.checked = row.include;
    include.setAttribute('aria-label', `${activeDataset} ${row.id} 出力`); include.onchange = () => { row.include = include.checked; $('review-warnings').checked = false; renderResults(); };
    label.prepend(include); first.append(label); tr.append(first);
    for (const header of output.headers) {
      const td = element('td'), input = element('input'); input.value = row.values[header] || ''; input.setAttribute('aria-label', `${activeDataset} ${row.id} ${header}`);
      input.disabled = !row.include || isId(header) && !$('allow-ids').checked;
      input.readOnly = !!row.familyRef && ['家庭ID', '家庭名', '住所', '電話番号'].includes(header);
      input.onchange = () => { row.values[header] = norm(input.value); delete row.inputErrors[header]; $('review-warnings').checked = false; unsaved = true; renderResults(); };
      td.append(input);
      const messages = errorMap.get(`${row.id}:${header}`);
      if (messages?.length) { td.className = 'error-cell'; input.setAttribute('aria-invalid', 'true'); td.append(element('small', [...new Set(messages)].join(' / '))); }
      tr.append(td);
    }
    body.append(tr);
  }
  tableNode.append(head, body); $('result-table').replaceChildren(tableNode);
  const prev = element('button', '前へ', 'secondary'), next = element('button', '次へ', 'secondary'); prev.type = next.type = 'button'; prev.disabled = page === 0; next.disabled = (page + 1) * PAGE_SIZE >= rows.length;
  prev.onclick = () => { page--; renderResults(); }; next.onclick = () => { page++; renderResults(); };
  $('pagination').replaceChildren(prev, element('span', `${rows.length ? page * PAGE_SIZE + 1 : 0}〜${Math.min((page + 1) * PAGE_SIZE, rows.length)} / ${rows.length}行`), next);
  renderActions();
}

function downloadable(dataset) {
  return !!result && result.outputs[dataset].rows.some(r => r.include) && !issues.some(i => i.dataset === dataset || dataset === 'children' && result.mode === 'combined' && i.dataset === 'families') && (!result.notes.length || $('review-warnings').checked);
}
function download(text, filename, type = 'text/csv;charset=utf-8') {
  const url = URL.createObjectURL(new Blob([text], {type})), link = element('a'); link.href = url; link.download = filename; link.click(); setTimeout(() => URL.revokeObjectURL(url), 1000);
}
function previewInApp(dataset) {
  if (offline) return;
  issues = validateResult(result); if (!downloadable(dataset)) return;
  const form = element('form'); form.action = `/data-transfers/import/${dataset}/preview`; form.method = 'post'; form.enctype = 'multipart/form-data'; form.target = '_blank'; form.rel = 'noopener'; form.hidden = true;
  const file = element('input'); file.type = 'file'; file.name = 'file';
  const transfer = new DataTransfer(); transfer.items.add(new File([csvText(result.outputs[dataset])], `converted-${dataset}.csv`, {type: 'text/csv'})); file.files = transfer.files;
  const token = element('input'); token.type = 'hidden'; token.name = 'csrf_token'; token.value = document.querySelector('meta[name="csrf-token"]').content;
  form.append(file, token); document.body.append(form); form.requestSubmit(); setTimeout(() => form.remove(), 1000);
  message('別タブで事前検証を開きました。内容を確認し、アプリの「インポート実行」で確定してください。');
}
function renderActions() {
  $('result-actions').replaceChildren();
  for (const [dataset, output] of Object.entries(result.outputs)) {
    const label = schemas.find(s => s.id === dataset).label;
    const save = element('button', `${label}CSVを保存`, 'secondary'), preview = element('button', `${label}をアプリで事前検証`);
    save.type = preview.type = 'button'; save.disabled = preview.disabled = !downloadable(dataset);
    save.onclick = () => { issues = validateResult(result); if (downloadable(dataset)) download(csvText(output), `converted-${dataset}.csv`); };
    preview.onclick = () => previewInApp(dataset); $('result-actions').append(save); if (!offline) $('result-actions').append(preview);
  }
  const report = element('button', '変換レポートを保存', 'secondary'); report.type = 'button';
  report.onclick = () => download(JSON.stringify({kind: 'open-hoikuict-conversion-report', version: 1, sourceFile: result.sourceName,
    omittedColumns: updateUnused().map(h => h.label), notes: result.notes, issues,
    outputs: Object.fromEntries(Object.entries(result.outputs).map(([dataset, output]) => { let line = 1; return [dataset, {columns: output.headers, rows: output.rows.map(row => ({outputRow: row.include ? ++line : null, sourceLines: row.sourceLines, included: row.include}))}]; })),
  }, null, 2), 'conversion-report.json', 'application/json');
  $('result-actions').append(report);
}

$('source-file').onchange = () => loadFile(true);
$('reload').onclick = () => loadFile(false);
$('mode').onchange = () => { if (table) rebuild(); else { $('combined-options').hidden = !['combined', 'guardian_rows'].includes($('mode').value); $('child-count-label').hidden = $('mode').value !== 'combined'; $('guardian-options').hidden = $('mode').value !== 'guardian_rows'; } };
$('child-count').onchange = () => { if (table) rebuild(); };
$('allow-ids').onchange = () => { invalidate(); if (table) renderMappings(); };
$('family-key').onchange = () => { invalidate(); updateUnused(); };
for (const id of ['guardian-column', 'guardian-first', 'guardian-second']) $(id).onchange = () => { invalidate(); updateUnused(); };
$('mapping-filter').oninput = filterMappings;
$('suggest').onclick = () => { if (table) { rebuild(); message('列名から候補を入れ直しました。補完値と修正した対応付けは確認し直してください。'); } };
$('convert').onclick = buildResult;
$('review-warnings').onchange = renderActions;
$('save-profile').onclick = () => {
  if (!table) return;
  download(JSON.stringify(saveProfile(table.headers, targets, mappings, {...options(), childCount: Number($('child-count').value)}), null, 2), 'migration-settings.json', 'application/json');
  message('列の対応と変換方法を保存しました。補完値・行データ・修正結果は含みません。');
};
$('load-profile-button').onclick = () => { if (!table) { message('先に元のファイルを選択してください。', true); return; } $('load-profile').click(); };
$('load-profile').onchange = async () => {
  const file = $('load-profile').files[0], current = sequence;
  try {
    if (!file || file.size > 300000) throw Error('300KB以内の変換設定ファイルを選択してください');
    const profile = JSON.parse(await file.text()); if (current !== sequence || !table) return;
    if (!['combined', 'guardian_rows'].includes(profile.mode) && !schemas.some(s => s.id === profile.mode) || ![1, 2, 3, 4].includes(profile.childCount) || ![1, 2, 3].includes(profile.headerDepth)) throw Error('変換設定のデータ種別を確認してください');
    const nextTargets = makeTargets(profile.mode, profile.childCount, schemas), loaded = loadProfile(profile, table.headers, nextTargets);
    $('mode').value = profile.mode; $('child-count').value = String(profile.childCount); $('allow-ids').checked = false;
    targets = nextTargets; mappings = loaded.mapping; sourceOptions($('family-key'), loaded.familyKey);
    sourceOptions($('guardian-column'), loaded.guardianColumn); $('guardian-column').options[0].textContent = '列を指定してください'; $('guardian-first').value = loaded.guardianFirst; $('guardian-second').value = loaded.guardianSecond;
    $('family-key').options[0].textContent = 'まとめない（1行を1家庭とする）'; invalidate(); renderMappings();
    const depthWarning = profile.headerDepth !== Number($('header-depth').value) ? '\n保存時と見出しの行数が違います。読込設定を確認してください。' : '';
    message(`変換設定を読み込みました。補完値とIDの指定は、今回のデータに合わせて確認してください。${loaded.missing.length ? '\n再指定が必要：' + [...new Set(loaded.missing)].join('、') : ''}${depthWarning}`, loaded.missing.length > 0); unsaved = true;
  } catch (error) { message(error.message, true); }
  $('load-profile').value = '';
};
$('clear').onclick = () => {
  if (unsaved && !window.confirm('読み込んだデータ・変換結果・修正内容をこの端末から消します。必要なCSVや設定は保存しましたか？')) return;
  sequence++; book = null; table = null; mappings = {}; targets = []; result = null; issues = []; unsaved = false;
  $('source-file').value = ''; $('load-profile').value = ''; $('mapping-filter').value = ''; $('allow-ids').checked = false;
  $('source-preview').replaceChildren(); $('mapping-fields').replaceChildren(); $('result-content').hidden = true;
  invalidate(); $('family-key').replaceChildren(option('', 'まとめない（1行を1家庭とする）'));
  $('guardian-column').replaceChildren(option('', '列を指定してください')); $('guardian-first').value = '1'; $('guardian-second').value = '2';
  $('sheet').replaceChildren(option('', 'ファイルを選択してください')); $('sheet').disabled = true;
  $('source-status').textContent = 'ファイルはまだ選択されていません。'; $('result-status').textContent = '作業内容を消しました。';
  $('suggest').disabled = $('convert').disabled = $('save-profile').disabled = true; updateUnused(); message('この端末の作業内容を消しました。アプリの登録データには影響しません。');
};
window.addEventListener('beforeunload', event => { if (unsaved) { event.preventDefault(); event.returnValue = ''; } });
