// The server owns source metadata; only editable values are submitted.
(() => {
  'use strict';
  const root = document.getElementById('annual-plan-sheet');
  if (!root) return;
  const $ = s => root.querySelector(s);
  const esc = x => String(x ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const clone = x => JSON.parse(JSON.stringify(x));
  let boot = JSON.parse(document.getElementById('annual-library-boot').textContent);
  let cells = {}, defs = new Map(), selected = 'development-2', owner = '', undo = [];
  let focusBefore = null, showRef = true, diff = true, busy = false, saved = '';
  const value = () => JSON.stringify({cells, owner});
  const dirty = () => boot.sheet && value() !== saved;
  const editable = () => boot.editable && root.dataset.detail !== 'true';
  const message = (text, error = false) => {
    $('#annual-message').textContent = text;
    $('#annual-message').setAttribute('role', error ? 'alert' : 'status');
  };
  const label = x => x.kind ? `${x.kind === 'development' ? '発達の過程' : '保育士の関わり'} / ${x.category} / ${x.id.split('-')[1]}` :
    x.label + (x.period !== undefined ? ' / ' + boot.sheet.periods[x.period].label : '');
  const time = (x, n) => n === 'annual' ? '通年' : x.kind === 'development' || x.axis === 'age' ?
    `${Math.floor(n / 12)}歳${n % 12}か月頃` : `${(n + 3) % 12 + 1}月頃`;
  const timing = x => `${cells[x.id].confirmed ? '確認済み：' : '推定：'}${time(x, cells[x.id].start)}${cells[x.id].start === 'annual' ? '' : 'から'}`;
  const changed = id => {
    const before = boot.sheet.baseline[id], now = cells[id];
    return now.body !== before.body || now.start !== before.start;
  };
  function fit(el) {
    el.style.height = 'auto';
    el.style.height = Math.max(38, el.scrollHeight + 1) + 'px';
  }
  function remember() {
    undo.push(clone({cells, owner}));
    if (undo.length > 30) undo.shift();
  }
  function setBusy(flag) {
    busy = flag;
    root.querySelectorAll('button,select,input').forEach(el => {
      const editControl = el.matches('[data-start],[data-confirm],#annual-save,#annual-import,#annual-undo');
      el.disabled = flag || (editControl && !editable());
    });
    root.querySelectorAll('textarea').forEach(el => { el.readOnly = flag || !editable(); });
    if ($('#annual-undo')) $('#annual-undo').disabled = flag || !editable() || !undo.length;
    if ($('#annual-save')) $('#annual-save').disabled = flag || !editable() || !boot.sheet;
    if ($('#annual-import')) $('#annual-import').disabled = flag || !editable() || !!boot.document_id || !$('#annual-origin').value;
  }
  function status() {
    root.dataset.diff = String(diff);
    $('.rd-change-count').textContent = `引き継ぎ元から ${[...defs.keys()].filter(changed).length}欄変更`;
    $('.rd-pending').textContent = `開始目安：未確認 ${[...defs.values()].filter(x => x.kind && !cells[x.id].confirmed).length}件`;
    root.querySelectorAll('[data-id]').forEach(el => {
      el.dataset.selected = String(el.dataset.id === selected);
      el.dataset.changed = String(changed(el.dataset.id));
    });
    $('[data-action="diff"]').setAttribute('aria-pressed', String(diff));
    $('[data-action="reference"]').setAttribute('aria-pressed', String(showRef));
    setBusy(busy);
  }
  function reference() {
    const x = defs.get(selected);
    $('.rd-reference').hidden = !showRef || !x;
    if (!x) return;
    $('.rd-reference').innerHTML = `<div class="rd-reference-top"><strong>${esc(label(x))}</strong><small>${esc(boot.sheet.baseline_label)}</small></div>
      <div class="rd-source-text">${esc(boot.sheet.baseline[x.id].body)}</div>
      ${x.kind ? `<small>引き継ぎ元の開始目安：${time(x, boot.sheet.baseline[x.id].start)}</small>` : ''}
      <details><summary>取り込み元の原文を確認（${esc(x.sourceCell)}${x.sourceLine ? '・' + x.sourceLine + '行目' : ''}）</summary><div class="rd-raw-line">${esc(x.rawLine || x.text)}</div></details>`;
  }
  function field(x) {
    return `<div class="rd-field" data-id="${esc(x.id)}"><textarea class="rd-edit" maxlength="20000" data-edit="${esc(x.id)}" aria-label="${esc(label(x))}">${esc(cells[x.id].body)}</textarea><span class="rd-field-source">${esc(x.sourceCell)}</span></div>`;
  }
  function entry(x, section) {
    const options = section.ticks.map(t => `<option value="${t.value}" ${cells[x.id].start === t.value ? 'selected' : ''}>${time(x, t.value)}から</option>`).join('') +
      (x.kind === 'support' ? `<option value="annual" ${cells[x.id].start === 'annual' ? 'selected' : ''}>通年</option>` : '');
    return `<div class="rd-entry" data-id="${esc(x.id)}" data-line="${x.sourceLine}"><span class="rd-anchor" aria-hidden="true"></span>
      <button type="button" class="rd-entry-label" data-select="${esc(x.id)}" aria-label="${esc(label(x))}の開始目安">${timing(x)}</button>
      <textarea class="rd-edit" maxlength="20000" data-edit="${esc(x.id)}" aria-label="${esc(label(x))}">${esc(cells[x.id].body)}</textarea>
      <div class="rd-entry-controls no-print"><label>開始目安<select data-start="${esc(x.id)}" aria-label="${esc(label(x))}の開始目安を変更">${options}</select></label>
      <label><input type="checkbox" data-confirm="${esc(x.id)}" ${cells[x.id].confirmed ? 'checked' : ''}>時期を確認</label></div></div>`;
  }
  function sectionMarkup(s) {
    const groups = [...new Set(s.items.map(x => x.category))];
    const ticks = s.axis === 'age' ? s.ticks.filter(t => [5,9,12,15,18,21,23].includes(t.value)) :
      s.kind === 'development' ? s.ticks.filter(t => [12,18,24,30,35].includes(t.value)) : s.ticks;
    const ratio = t => (t.x - s.ticks[0].x) / (s.ticks.at(-1).x - s.ticks[0].x) * 100;
    const title = s.kind === 'development' ? '発達の過程' : '保育士の関わり';
    return `<div class="rd-section-title"><strong>${title}</strong><small>${s.items.length}文</small></div><table aria-label="${title}"><colgroup><col style="width:79px"><col></colgroup><tbody>
      <tr><th>${s.kind === 'development' || s.axis === 'age' ? '月齢' : '年度内の月'}</th><td><div class="rd-axis">${ticks.map(t => `<span style="left:${ratio(t)}%">${time(s.items[0], t.value).replace('頃', '')}</span>`).join('')}</div></td></tr>
      ${groups.map(category => `<tr><th class="rd-category" scope="row">${esc(category)}</th><td><div class="rd-board"><div class="rd-grid" aria-hidden="true">${ticks.map(t => `<i style="left:${ratio(t)}%"></i>`).join('')}</div>${s.items.filter(x => x.category === category).map(x => entry(x, s)).join('')}</div></td></tr>`).join('')}</tbody></table>`;
  }
  function gridMarkup(grid, title) {
    const total = grid.widths.reduce((a, b) => a + b, 0);
    return `<table class="rd-source-grid" aria-label="${esc(title)}"><colgroup>${grid.widths.map(w => `<col style="width:${100 * w / total}%">`).join('')}</colgroup><tbody>${grid.rows.map(row => `<tr>${row.map(c => `<td rowspan="${c.rowspan}" colspan="${c.colspan}"${c.field ? '' : ' class="rd-grid-text"'}>${c.field ? field(defs.get(c.field)) : esc(c.text)}</td>`).join('')}</tr>`).join('')}</tbody></table>`;
  }
  function renderReferences() {
    const refs = boot.references || [];
    $('.annual-reflections').hidden = !refs.length;
    $('.annual-reflections').innerHTML = refs.length ? `<h3>Driveから取り込んだ反省・参考資料</h3><p>原本の記入済みの文章を表示しています。未記入の期は空欄です。</p>${refs.map(r => `<details ${r.primary ? 'open' : ''}><summary>${esc(r.status)} · ${esc(r.source.title)} · ${esc(r.source.sheet)}</summary><div class="rd-source no-print"><a href="${esc(r.source.url)}" target="_blank" rel="noopener noreferrer">Driveの原本を開く</a><span>${esc(r.source.range)}</span></div><div class="rd-scroll">${gridMarkup(r.grid, r.status)}</div></details>`).join('')}` : '';
  }
  function pack() {
    root.querySelectorAll('.rd-board').forEach(board => {
      const w = board.clientWidth;
      if (!w) return;
      const boxes = [];
      let line = null, bandTop = 6;
      board.querySelectorAll('.rd-entry').forEach(el => {
        const x = defs.get(el.dataset.id), anchor = Math.max(0, Math.min(1, cells[x.id].position_ratio)) * w;
        const width = Math.min(310, Math.max(220, w - anchor)), left = Math.max(0, Math.min(anchor, w - width));
        el.style.width = width + 'px'; el.style.left = left + 'px';
        el.querySelector('.rd-anchor').style.left = (anchor - left) + 'px';
        fit(el.querySelector('textarea'));
        if (line !== null && line !== x.sourceLine) bandTop = Math.max(bandTop, ...boxes.map(r => r.bottom + 6));
        line = x.sourceLine;
        let top = bandTop;
        const height = el.getBoundingClientRect().height;
        for (let pass = 0; pass <= boxes.length; pass++) {
          const hit = boxes.filter(r => left < r.right + 8 && left + width + 8 > r.left && top < r.bottom + 5 && top + height + 5 > r.top);
          if (!hit.length) break;
          top = Math.max(...hit.map(r => r.bottom + 6));
        }
        el.style.top = top + 'px';
        boxes.push({left, right:left + width, top, bottom:top + height});
      });
      board.style.height = (Math.max(0, ...boxes.map(r => r.bottom)) + 7) + 'px';
    });
    root.querySelectorAll('.rd-field textarea,#annual-owner').forEach(fit);
  }
  function renderSheet() {
    if (!boot.sheet) return;
    const source = boot.sheet.source;
    $('.rd-context').textContent = `${boot.school_year}年度 · ${boot.classroom_name} · ${boot.age}歳児`;
    $('.rd-sheet-title').textContent = `${boot.school_year}年度\n${boot.nursery_name}\n年間指導計画`;
    $('.annual-class-label').textContent = boot.classroom_name + `\n（${boot.age}歳児）`;
    $('#annual-owner').value = owner;
    $('.rd-annual').innerHTML = (source.annualFields || ['annual']).map(id => field(defs.get(id))).join('');
    $('.rd-development').innerHTML = ''; $('.rd-support').innerHTML = '';
    source.sections.forEach(s => { $('.rd-' + s.kind).innerHTML = sectionMarkup(s); });
    $('.rd-terms').innerHTML = source.grid ? gridMarkup(source.grid, '各期の年間指導計画') : `<table aria-label="各期の年間指導計画"><colgroup><col style="width:79px"><col><col><col><col></colgroup><thead><tr><th>期</th>${boot.sheet.periods.map(p => `<th>${esc(p.label)}</th>`).join('')}</tr></thead><tbody>${['goal','content','care'].map(k => `<tr><th scope="row">${esc(defs.get(k + ':0').label)}</th>${[0,1,2,3].map(i => `<td>${field(defs.get(k + ':' + i))}</td>`).join('')}</tr>`).join('')}</tbody></table>`;
    $('.annual-source-link').textContent = source.source.title;
    $('.annual-source-link').href = source.source.url;
    $('.annual-source-range').textContent = source.source.sheet + ' · ' + source.source.range;
    $('.rd-coverage').textContent = `本文${source.fields.length}欄・発達と関わり${source.sections.reduce((n, s) => n + s.items.length, 0)}文を反映`;
    $('.rd-legend').hidden = !source.sections.length;
    renderReferences();
    reference(); status(); requestAnimationFrame(pack);
  }
  function adopt(data) {
    boot = data;
    cells = clone(data.sheet?.fields || {}); owner = data.owner_name; undo = []; focusBefore = null;
    defs = new Map(data.sheet ? [...data.sheet.source.fields, ...data.sheet.source.sections.flatMap(s => s.items.map(x => ({...x, ticks:s.ticks})))].map(x => [x.id, x]) : []);
    if (!defs.has(selected)) selected = defs.keys().next().value;
    saved = value();
    $('.annual-status').textContent = data.status + (data.editable ? '' : ' · 閲覧のみ');
    if ($('.annual-age-label')) $('.annual-age-label').textContent = data.age === null ? '' : `${data.age}歳児の様式`;
    $('.annual-document-link').hidden = !data.document_id;
    $('.annual-document-link').href = '/plans/documents/' + data.document_id;
    $('.annual-editor').hidden = !data.sheet;
    $('.annual-empty').hidden = !!data.sheet;
    if ($('#annual-classroom')) {
      $('#annual-classroom').value = data.classroom_id;
      $('#annual-year').value = data.school_year;
      $('.annual-origin').hidden = !!data.document_id;
      $('#annual-origin').innerHTML = '<option value="">年案を選択</option>' +
        data.previous.map(p => `<option value="previous:${p.document_id}:${p.revision_id}">${esc(p.title)}（${esc(p.status)}）</option>`).join('') +
        data.sources.map(s => `<option value="${esc('source:' + s.key)}">${esc(s.title)}（${s.year}年度・${esc(s.class_name)}）</option>`).join('');
      if (data.sheet && !data.document_id) {
        const origin = data.sheet.origin;
        $('#annual-origin').value = origin.kind === 'source' ? 'source:' + origin.key :
          `previous:${origin.document_id}:${origin.revision_id}`;
      }
      $('.annual-source-warning').textContent = data.source_error || (!data.sources.length && !data.previous.length ? '取り込み元が未登録です。管理者が確認済みの年案データを設定してください。' : '');
    }
    if (data.document_id && root.dataset.detail !== 'true') history.replaceState(null, '', '/plans/annual-library?document_id=' + data.document_id);
    renderSheet(); setBusy(false);
  }
  async function api(path, options = {}) {
    const response = await fetch('/plans/annual-library/' + path, {credentials:'same-origin', ...options});
    if (response.redirected || !response.headers.get('content-type')?.includes('application/json')) throw new Error('職員のログイン状態を確認してください。入力内容は保持されています。');
    const data = await response.json();
    if (!response.ok) throw new Error(typeof data.detail === 'string' ? data.detail : '入力内容を確認してください。入力内容は保持されています。');
    return data;
  }
  async function load(params) {
    if (busy) return;
    if (dirty() && !window.confirm('未保存の入力があります。保存せずに別の年案を開きますか？')) {
      $('#annual-classroom').value = boot.classroom_id; $('#annual-year').value = boot.school_year; return;
    }
    setBusy(true);
    try {
      const data = await api('context?' + new URLSearchParams(params));
      adopt(data);
      if (!data.document_id) history.replaceState(null, '', '/plans/annual-library?' + new URLSearchParams({classroom_id:data.classroom_id, school_year:data.school_year}));
      message(data.sheet ? '本文と開始目安を読み込みました。' : '引き継ぐ年案を選択してください。');
    } catch (e) {
      message(e.message, true);
      $('#annual-classroom').value = boot.classroom_id; $('#annual-year').value = boot.school_year;
    } finally { setBusy(false); }
  }
  async function save() {
    if (busy || !boot.sheet || !editable()) return;
    setBusy(true);
    try {
      const payload = {document_id:boot.document_id, lock_version:boot.lock_version,
        classroom_id:boot.classroom_id, school_year:boot.school_year, owner_name:owner,
        origin:boot.sheet.origin, source_digest:boot.sheet.source_digest,
        fields:Object.fromEntries(Object.entries(cells).map(([key, c]) => [key, {body:c.body, start:c.start, confirmed:c.confirmed}]))};
      const data = await api('save', {method:'POST', headers:{'Content-Type':'application/json', 'X-CSRF-Token':document.querySelector('meta[name="csrf-token"]')?.content || ''}, body:JSON.stringify(payload)});
      adopt(data); message('保存しました。承認・文書情報から確認を依頼できます。');
    } catch (e) { message(e.message, true); }
    finally { setBusy(false); }
  }
  function select(id) {
    if (selected === id) return;
    selected = id; reference(); status(); requestAnimationFrame(pack);
  }
  root.addEventListener('focusin', e => {
    const id = e.target.dataset.edit;
    if (id) select(id);
    if ((id || e.target.id === 'annual-owner') && editable()) focusBefore = clone({cells, owner});
  });
  root.addEventListener('focusout', e => {
    if (!(e.target.dataset.edit || e.target.id === 'annual-owner') || !focusBefore) return;
    if (JSON.stringify(focusBefore) !== value()) { undo.push(focusBefore); if (undo.length > 30) undo.shift(); }
    focusBefore = null; if (boot.sheet) status();
  });
  root.addEventListener('input', e => {
    if (!editable() || busy) return;
    if (e.target.dataset.edit) cells[e.target.dataset.edit].body = e.target.value;
    else if (e.target.id === 'annual-owner') owner = e.target.value;
    else return;
    fit(e.target); status(); pack(); message('未保存の変更があります。');
  });
  root.addEventListener('change', e => {
    const id = e.target.dataset.start || e.target.dataset.confirm;
    if (id && editable() && !busy) {
      remember();
      const cell = cells[id], x = defs.get(id);
      if (e.target.dataset.start) {
        cell.start = e.target.value === 'annual' ? 'annual' : Number(e.target.value);
        cell.confirmed = false;
        const before = boot.sheet.baseline[id];
        const ticks = x.ticks;
        cell.position_ratio = cell.start === before.start ? before.position_ratio : cell.start === 'annual' ? 0 :
          (ticks.find(t => t.value === cell.start).x - ticks[0].x) / (ticks.at(-1).x - ticks[0].x);
        e.target.closest('.rd-entry').querySelector('[data-confirm]').checked = false;
      } else cell.confirmed = e.target.checked;
      e.target.closest('.rd-entry').querySelector('.rd-entry-label').textContent = timing(x);
      status(); pack(); message('未保存の変更があります。');
    } else if (['annual-year','annual-classroom'].includes(e.target.id)) {
      load({classroom_id:$('#annual-classroom').value, school_year:$('#annual-year').value});
    } else if (e.target.id === 'annual-origin') setBusy(busy);
  });
  root.addEventListener('click', e => {
    const button = e.target.closest('button');
    if (!button || busy) return;
    if (button.dataset.select) { select(button.dataset.select); return; }
    if (button.id === 'annual-save') save();
    else if (button.id === 'annual-print') { pack(); window.print(); }
    else if (button.id === 'annual-import') {
      const chosen = $('#annual-origin').value;
      const params = {classroom_id:boot.classroom_id, school_year:boot.school_year};
      if (chosen.startsWith('source:')) params.source_key = chosen.slice(7);
      else if (chosen.startsWith('previous:')) [params.previous_id, params.revision_id] = chosen.split(':').slice(1);
      else return;
      load(params);
    } else if (button.id === 'annual-undo' && undo.length) {
      const before = undo.pop(); cells = before.cells; owner = before.owner; focusBefore = null;
      renderSheet(); message(dirty() ? '直前の変更を戻しました。未保存の変更があります。' : '保存済みの内容に戻りました。');
    } else if (button.dataset.action === 'diff') { diff = !diff; status(); }
    else if (button.dataset.action === 'reference') { showRef = !showRef; reference(); status(); }
  });
  window.addEventListener('beforeunload', e => { if (dirty()) { e.preventDefault(); e.returnValue = ''; } });
  window.addEventListener('beforeprint', pack);
  window.addEventListener('afterprint', () => requestAnimationFrame(pack));
  adopt(boot);
  let width = 0;
  new ResizeObserver(entries => { const next = entries[0].contentRect.width; if (next !== width) { width = next; requestAnimationFrame(pack); } }).observe($('.rd-sheet'));
})();
