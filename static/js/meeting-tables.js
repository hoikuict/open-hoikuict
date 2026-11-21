// Tables share the existing Y.Doc. Stable row/column IDs and one Y.Text per cell
// keep edits in different cells independent, including concurrent row/column insertions.
const TABLES_KEY = 'meeting-tables-v1';
const CELL_PREFIX = 'meeting-cell-v1:';
const MAX_ROWS = 20;
const MAX_COLUMNS = 8;
const MAX_CELL_TEXT = 4000;
const uid = () => crypto.randomUUID();
const validId = value => typeof value === 'string' && /^[\w-]{1,80}$/.test(value);

export function validateTable(value, forInsertion = false) {
  const rowLimit = forInsertion ? MAX_ROWS : 100;
  const colLimit = forInsertion ? MAX_COLUMNS : 32;
  if (!value || value.version !== 1 || typeof value.header !== 'boolean' ||
      !Array.isArray(value.rows) || !value.rows.length || value.rows.length > rowLimit) {
    throw new Error('表のデータを読み取れません。');
  }
  const columns = value.rows[0]?.length;
  if (!columns || columns > colLimit || value.rows.some(row => !Array.isArray(row) ||
      row.length !== columns || row.some(cell => typeof cell !== 'string' ||
      cell.length > (forInsertion ? MAX_CELL_TEXT : 16000) || /[\x00-\x08\x0b\x0c\x0e-\x1f]/.test(cell)))) {
    throw new Error(`表は${rowLimit}行・${colLimit}列以内で、セルの内容を確認してください。`);
  }
  return {version: 1, header: value.header, rows: value.rows.map(row => [...row])};
}

export function createTableStore(Y, doc, onCell = () => {}) {
  const tables = doc.getMap(TABLES_KEY);
  function model(id) {
    const table = tables.get(id);
    if (!validId(id) || !(table instanceof Y.Map) || !(table.get('rows') instanceof Y.Array) ||
        !(table.get('columns') instanceof Y.Array)) throw new Error('表の構造を読み取れません。');
    const rows = table.get('rows').toArray(), columns = table.get('columns').toArray();
    if (rows.length > 100 || columns.length > 32 || !rows.every(validId) || !columns.every(validId)) {
      throw new Error('表の大きさを確認してください。');
    }
    // Two writers can each delete a different last remaining row/column. A
    // deterministic empty cell keeps that merged table editable and saveable.
    if (!rows.length) rows.push('empty-row');
    if (!columns.length) columns.push('empty-column');
    return {table, rows, columns, header: table.get('header') === true};
  }
  function cell(id, row, column) {
    if (![id, row, column].every(validId)) throw new Error('セルの参照が不正です。');
    const key = `${CELL_PREFIX}${id}:${row}:${column}`;
    const text = doc.getText(key);
    onCell(text, key);
    return text;
  }
  function snapshot(id) {
    const data = model(id);
    return validateTable({version: 1, header: data.header,
      rows: data.rows.map(row => data.columns.map(column => cell(id, row, column).toString()))});
  }
  function create(value) {
    const data = validateTable(value, true), id = uid();
    const table = new Y.Map(), rows = new Y.Array(), columns = new Y.Array();
    const rowIds = data.rows.map(uid), colIds = data.rows[0].map(uid);
    table.set('rows', rows); table.set('columns', columns); table.set('header', data.header);
    tables.set(id, table); rows.insert(0, rowIds); columns.insert(0, colIds);
    data.rows.forEach((row, r) => row.forEach((value, c) => {
      if (value) cell(id, rowIds[r], colIds[c]).insert(0, value);
    }));
    return id;
  }
  return {tables, model, cell, snapshot, create};
}

export function registerMeetingTable(Quill) {
  const BlockEmbed = Quill.import('blots/block/embed');
  class MeetingTable extends BlockEmbed {
    static create(value) {
      const node = super.create();
      node.dataset.tableId = validId(value) ? value : '';
      node.setAttribute('contenteditable', 'false');
      node.setAttribute('aria-label', '議事録の表');
      return node;
    }
    static value(node) { return node.dataset.tableId; }
    // The cell DOM is controlled by Y.Text, not by Quill's paragraph observer.
    update() {}
  }
  MeetingTable.blotName = 'meetingTable';
  MeetingTable.tagName = 'DIV';
  MeetingTable.className = 'meeting-table-block';
  Quill.register(MeetingTable);
}

export function installMeetingTables({Y, Quill, editor, ydoc, ytext, ymeta, binding, canEdit, onExcerpt}) {
  const $ = selector => document.querySelector(selector);
  const root = editor.root, toolbar = $('#meeting-table-toolbar');
  const origin = {}, cellObservers = new Map();
  let enabled = false, selected = null, anchor = null, rendering = false, scheduled = false;
  let composing = null, queuedUpdates = [], waiters = [], deleteAction = null;
  let undoManager;
  const store = createTableStore(Y, ydoc, watchCell);
  undoManager = new Y.UndoManager([ytext, ymeta, store.tables], {trackedOrigins: new Set([null, binding, origin])});
  const selectionPanel = $('#meeting-table-selection');
  const message = text => { if (!toolbar) return; $('#meeting-table-message').textContent = text; $('#meeting-table-message').hidden = !text; };
  const run = callback => { try { return callback(); } catch (error) { message(error.message); return null; } };
  const editable = () => canEdit && enabled;
  function transact(callback) {
    if (!editable()) return;
    // QuillBinding must recognize edits that already changed Quill's DOM. An
    // outer transaction with another origin would replay the embed into Quill.
    undoManager.stopCapturing(); ydoc.transact(callback, binding); undoManager.stopCapturing();
    render(); updateControls();
  }
  function cellElement(key) { return root.querySelector(`[data-cell-key="${key}"]`); }
  function setCellContent(element, value) {
    element.replaceChildren(document.createTextNode(value));
    // A trailing newline needs a visible empty line for Chromium's caret.
    // BR contributes no textContent, so it never enters the stored cell value.
    if (value.endsWith('\n')) element.append(document.createElement('br'));
  }
  function offsets(element) {
    const selection = window.getSelection();
    if (!selection.rangeCount || !element.contains(selection.anchorNode) || !element.contains(selection.focusNode)) return null;
    const offset = (node, index) => { const range = document.createRange(); range.selectNodeContents(element); range.setEnd(node, index); return range.toString().length; };
    return {anchor: offset(selection.anchorNode, selection.anchorOffset), focus: offset(selection.focusNode, selection.focusOffset)};
  }
  function caret(element, start, end = start) {
    if (!element || !editable()) return;
    if (!element.firstChild) element.append(document.createTextNode(''));
    element.focus({preventScroll: true});
    const length = element.textContent.length, selection = window.getSelection();
    selection.setBaseAndExtent(element.firstChild, Math.min(start, length), element.firstChild, Math.min(end, length));
  }
  function transform(index, delta) {
    let old = 0, position = index;
    for (const op of delta) {
      if (op.retain) old += op.retain;
      else if (op.insert !== undefined) { if (old <= index) position += String(op.insert).length; }
      else if (op.delete) { position -= Math.max(0, Math.min(op.delete, index - old)); old += op.delete; }
    }
    return Math.max(0, position);
  }
  function watchCell(text, key) {
    if (cellObservers.has(key)) return;
    undoManager?.addToScope(text);
    const observer = event => {
      const element = cellElement(key);
      if (!element || composing?.element === element) return;
      const value = text.toString();
      if (element.textContent === value) return;
      const range = offsets(element);
      setCellContent(element, value);
      if (range) caret(element, transform(range.anchor, event.delta), transform(range.focus, event.delta));
    };
    text.observe(observer); cellObservers.set(key, observer);
  }
  function selectedModel() {
    if (!selected || !store.tables.has(selected.id)) return null;
    const data = store.model(selected.id);
    if (!data.rows.includes(selected.row) || !data.columns.includes(selected.column)) return null;
    return data;
  }
  function updateControls() {
    if (!toolbar) return;
    const data = run(selectedModel);
    if (!data) selected = null;
    selectionPanel.hidden = !data;
    $('#meeting-table-insert').disabled = !editable() || Boolean(data);
    $('#meeting-table-paste').disabled = !editable() || Boolean(data);
    $('#meeting-undo').disabled = !editable() || !undoManager.undoStack.length;
    $('#meeting-redo').disabled = !editable() || !undoManager.redoStack.length;
    if (!data) return;
    $('#meeting-table-position').textContent = `${data.rows.indexOf(selected.row) + 1}行 ${data.columns.indexOf(selected.column) + 1}列を選択中 · ${data.rows.length}行 × ${data.columns.length}列`;
    $('#meeting-table-header').checked = data.header;
    toolbar.querySelectorAll('[data-table-action]').forEach(button => {
      const action = button.dataset.tableAction;
      button.disabled = (action.startsWith('row-') && !action.endsWith('delete') && data.rows.length >= MAX_ROWS) ||
        (action.startsWith('column-') && !action.endsWith('delete') && data.columns.length >= MAX_COLUMNS);
    });
  }
  function scheduleRender() { if (!scheduled) { scheduled = true; requestAnimationFrame(() => {scheduled = false; render();}); } }
  function render() {
    if (rendering || composing) return;
    rendering = true;
    try {
      root.querySelectorAll('.meeting-table-block').forEach(block => {
        const id = block.dataset.tableId;
        try {
          const data = store.model(id), signature = JSON.stringify([data.rows, data.columns, data.header]);
          if (block.dataset.structure !== signature) {
            const active = document.activeElement?.closest('.meeting-table-cell');
            const previous = active && block.contains(active) ? {key: active.dataset.cellKey, range: offsets(active)} : null;
            const table = document.createElement('table'); table.setAttribute('aria-label', '議事録の表');
            table.style.minWidth = Math.max(320, data.columns.length * 130) + 'px';
            const body = document.createElement('tbody'), head = document.createElement('thead');
            if (data.header) table.append(head); table.append(body);
            data.rows.forEach((row, r) => {
              const tr = document.createElement('tr');
              data.columns.forEach(column => {
                const td = document.createElement(data.header && r === 0 ? 'th' : 'td');
                if (td.tagName === 'TH') td.scope = 'col';
                const cell = document.createElement('div'); cell.className = 'meeting-table-cell';
                Object.assign(cell.dataset, {tableId: id, rowId: row, columnId: column, cellKey: `${CELL_PREFIX}${id}:${row}:${column}`});
                cell.setAttribute('role', 'textbox'); cell.setAttribute('aria-multiline', 'true');
                cell.setAttribute('aria-label', `${r + 1}行 ${data.columns.indexOf(column) + 1}列`);
                setCellContent(cell, store.cell(id, row, column).toString()); td.append(cell); tr.append(td);
              });
              (data.header && r === 0 ? head : body).append(tr);
            });
            block.replaceChildren(table); block.dataset.structure = signature;
            if (previous?.range) { const el = cellElement(previous.key); if (el) caret(el, previous.range.anchor, previous.range.focus); }
          }
          block.querySelectorAll('.meeting-table-cell').forEach(cell => {
            cell.contentEditable = editable() ? 'plaintext-only' : 'false';
            cell.tabIndex = editable() ? 0 : -1;
            const text = store.cell(id, cell.dataset.rowId, cell.dataset.columnId);
            if (cell.textContent !== text.toString()) setCellContent(cell, text.toString());
          });
        } catch (error) {
          if (!block.querySelector('table')) block.textContent = '表を読み込めません。画面を開き直してください。';
          message(error.message);
        }
      });
      updateControls();
    } finally { rendering = false; }
  }
  function focusCell(id, row, column) {
    render(); const element = cellElement(`${CELL_PREFIX}${id}:${row}:${column}`);
    if (element) { selected = {id, row, column}; updateControls(); caret(element, element.textContent.length); requestAnimationFrame(ensureVisible); }
  }
  function ensureVisible() {
    const element = document.activeElement?.closest('.meeting-table-cell');
    if (!element || !toolbar) return;
    const cell = element.getBoundingClientRect(), top = toolbar.getBoundingClientRect().bottom + 12;
    if (cell.top < top) window.scrollBy(0, cell.top - top);
    else if (cell.bottom > innerHeight - 24 && cell.height < innerHeight - top - 24) window.scrollBy(0, cell.bottom - innerHeight + 24);
  }
  function currentIndex() {
    const absolute = anchor && Y.createAbsolutePositionFromRelativePosition(anchor, ydoc);
    return Math.min(Math.max(absolute?.index ?? editor.getLength() - 1, 0), editor.getLength() - 1);
  }
  function blockIndex(id) {
    const block = root.querySelector(`.meeting-table-block[data-table-id="${id}"]`);
    return block ? editor.getIndex(Quill.find(block)) : -1;
  }
  function insert(value) {
    if (!editable() || selectedModel()) return;
    if (root.querySelectorAll('.meeting-table-block').length >= 20) throw new Error('一つの議事録に作成できる表は20個までです。');
    let id;
    transact(() => {
      id = store.create(value);
      const index = currentIndex();
      editor.insertEmbed(index, 'meetingTable', id, Quill.sources.USER);
      const at = blockIndex(id);
      if (at >= editor.getLength() - 1) editor.insertText(at + 1, '\n', Quill.sources.USER);
    });
    const data = store.model(id); focusCell(id, data.rows[0], data.columns[0]);
    message('表を追加しました。入力内容は自動保存されます。');
  }
  function replaceCell(element, start, end, value) {
    if (/[\x00-\x08\x0b\x0c\x0e-\x1f]/.test(value)) throw new Error('セルに貼り付ける文字を確認してください。');
    const {tableId: id, rowId: row, columnId: column} = element.dataset;
    const data = store.model(id);
    if (!data.rows.includes(row) || !data.columns.includes(column)) return;
    const text = store.cell(id, row, column);
    if (text.length - (end - start) + value.length > MAX_CELL_TEXT) {message('セルは4,000文字以内で入力してください。');element.textContent = text.toString();return;}
    ydoc.transact(() => { if (end > start) text.delete(start, end - start); if (value) text.insert(start, value); }, origin);
    setCellContent(element, text.toString()); caret(element, start + value.length);
  }
  function commitCell(element) {
    if (!editable() || !element || !root.contains(element)) return;
    const {tableId: id, rowId: row, columnId: column} = element.dataset;
    const data = store.model(id); if (!data.rows.includes(row) || !data.columns.includes(column)) return;
    const text = store.cell(id, row, column), before = text.toString(), after = element.textContent.replace(/\r/g, '');
    if (before === after) return;
    if (after.length > MAX_CELL_TEXT) {element.textContent = before;message('セルは4,000文字以内で入力してください。');return;}
    let start = 0, endBefore = before.length, endAfter = after.length;
    while (start < endBefore && start < endAfter && before[start] === after[start]) start++;
    while (endBefore > start && endAfter > start && before[endBefore - 1] === after[endAfter - 1]) {endBefore--;endAfter--;}
    ydoc.transact(() => {if (endBefore > start) text.delete(start, endBefore - start); if (endAfter > start) text.insert(start, after.slice(start, endAfter));}, origin);
  }
  function finishComposition() {
    if (!composing) return;
    const element = composing.element; composing = null;
    run(() => commitCell(element));
    const updates = queuedUpdates; queuedUpdates = [];
    updates.forEach(([update, source]) => Y.applyUpdate(ydoc, update, source));
    render(); waiters.splice(0).forEach(resolve => resolve());
  }
  function paragraph(after) {
    if (!selectedModel()) return;
    const index = blockIndex(selected.id) + (after ? 1 : 0);
    transact(() => editor.insertText(index, '\n', Quill.sources.USER));
    selected = null; updateControls(); editor.setSelection(index, 0, Quill.sources.USER);
  }
  async function copy() {
    const data = store.snapshot(selected.id);
    const wrapper = document.createElement('div'); wrapper.dataset.hoikuictTable = JSON.stringify(data);
    const table = document.createElement('table'); wrapper.append(table);
    data.rows.forEach((row, r) => { const tr = document.createElement('tr'); row.forEach(value => {const td = document.createElement(data.header && r === 0 ? 'th' : 'td');td.textContent = value;tr.append(td);});table.append(tr); });
    if (navigator.clipboard?.write && window.ClipboardItem) {
      await navigator.clipboard.write([new ClipboardItem({'text/html': new Blob([wrapper.outerHTML], {type: 'text/html'}),
        'text/plain': new Blob([data.rows.map(row => row.join('\t')).join('\n')], {type: 'text/plain'})})]);
    } else {
      await navigator.clipboard.writeText('HOIKUICT_TABLE_V1\n' + JSON.stringify(data));
    }
    message('表をコピーしました。別の議事録の本文で「表を貼り付け」を押してください。');
  }
  function parseClipboard(html, text) {
    let raw;
    if (html) {const template = document.createElement('template');template.innerHTML = html;raw = template.content.querySelector('[data-hoikuict-table]')?.getAttribute('data-hoikuict-table');}
    if (!raw && text?.startsWith('HOIKUICT_TABLE_V1\n')) raw = text.slice(18);
    if (!raw) return null;
    if (raw.length > 800000) throw new Error('コピーされた表が大きすぎます。');
    return validateTable(JSON.parse(raw), true);
  }
  async function pasteButton() {
    let html = '', text = '';
    if (navigator.clipboard?.read) {
      for (const item of await navigator.clipboard.read()) {
        if (item.types.includes('text/html')) html = await (await item.getType('text/html')).text();
        if (item.types.includes('text/plain')) text = await (await item.getType('text/plain')).text();
      }
    } else text = await navigator.clipboard.readText();
    const value = parseClipboard(html, text);
    if (!value) throw new Error('議事録の「表をコピー」でコピーした表を貼り付けてください。');
    insert(value);
  }
  function action(name) {
    if (!editable()) return;
    const data = selectedModel(); if (!data) return;
    const target = {...selected};
    if (name === 'copy') {copy().catch(() => message('コピーできませんでした。ブラウザーのクリップボードへのアクセスを許可して再試行してください。'));return;}
    if (name.startsWith('paragraph-')) {paragraph(name.endsWith('after'));return;}
    if (name === 'delete' || name.endsWith('-delete')) {
      const axis = name.startsWith('row') ? 'rows' : 'columns', key = axis === 'rows' ? 'row' : 'column';
      const whole = name === 'delete' || data[axis].length === 1;
      $('#meeting-table-delete-title').textContent = whole ? '表全体を削除しますか？' : `${data[axis].indexOf(target[key]) + 1}${axis === 'rows' ? '行目' : '列目'}を削除しますか？`;
      deleteAction = () => transact(() => {
        const current = store.model(target.id);
        if (whole) {const index = blockIndex(target.id);if (index >= 0) editor.deleteText(index, 1, Quill.sources.USER);store.tables.delete(target.id);selected = null;}
        else {const at = current[axis].indexOf(target[key]);if (at >= 0) current.table.get(axis).delete(at, 1);selected = null;}
      });
      $('#meeting-table-delete-dialog').showModal(); return;
    }
    const axis = name.startsWith('row') ? 'rows' : 'columns', key = axis === 'rows' ? 'row' : 'column';
    if (data[axis].length >= (axis === 'rows' ? MAX_ROWS : MAX_COLUMNS)) return;
    const id = uid(), at = data[axis].indexOf(target[key]) + (name.endsWith('after') ? 1 : 0);
    transact(() => {
      const items = data.table.get(axis);
      if (!items.length) items.insert(0, data[axis]);
      items.insert(at, [id]);
    });
    focusCell(target.id, axis === 'rows' ? id : target.row, axis === 'columns' ? id : target.column);
  }
  // Ignore Quill's native clipboard interpretation of our opaque embeds.
  editor.clipboard.addMatcher('.meeting-table-block', () => new (Quill.import('delta'))());
  editor.on('selection-change', range => {
    if (range && !document.activeElement?.closest('.meeting-table-cell')) anchor = Y.createRelativePositionFromTypeIndex(ytext, range.index);
  });
  editor.on('text-change', scheduleRender); ydoc.on('update', scheduleRender);
  for (const event of ['stack-item-added', 'stack-item-popped', 'stack-item-updated', 'stack-cleared']) undoManager.on(event, updateControls);
  root.addEventListener('focusin', event => {
    const element = event.target.closest('.meeting-table-cell'); if (!element) return;
    selected = {id: element.dataset.tableId, row: element.dataset.rowId, column: element.dataset.columnId};
    document.querySelector('.meeting-editor .ql-toolbar')?.classList.remove('is-visible');
    updateControls(); requestAnimationFrame(ensureVisible);
  });
  root.addEventListener('pointerdown', event => {if (!event.target.closest('.meeting-table-block')) {selected = null;updateControls();}});
  root.addEventListener('compositionstart', event => {const element = event.target.closest('.meeting-table-cell');if (element && editable()) composing = {element};}, true);
  root.addEventListener('compositionend', finishComposition, true);
  root.addEventListener('focusout', event => {if (composing?.element === event.target) finishComposition();}, true);
  root.addEventListener('input', event => {const element = event.target.closest('.meeting-table-cell');if (element) {event.stopPropagation();if (!composing) run(() => commitCell(element));}}, true);
  root.addEventListener('beforeinput', event => {
    const element = event.target.closest('.meeting-table-cell');
    if (element && editable() && ['insertParagraph', 'insertLineBreak'].includes(event.inputType)) {
      event.preventDefault();const range = offsets(element);if (range) run(() => replaceCell(element, Math.min(range.anchor, range.focus), Math.max(range.anchor, range.focus), '\n'));
    }
  }, true);
  root.addEventListener('keydown', event => {
    const element = event.target.closest('.meeting-table-cell');
    if (!element) return;
    event.stopPropagation();
    if (event.key === 'Tab') {
      event.preventDefault();const cells = [...element.closest('table').querySelectorAll('.meeting-table-cell')], next = cells[cells.indexOf(element) + (event.shiftKey ? -1 : 1)];
      if (next) focusCell(next.dataset.tableId, next.dataset.rowId, next.dataset.columnId); else paragraph(!event.shiftKey);
    }
    if ((event.ctrlKey || event.metaKey) && ['b','i','u'].includes(event.key.toLowerCase())) event.preventDefault();
  }, true);
  document.addEventListener('keydown', event => {
    if (!editable() || !(event.ctrlKey || event.metaKey) || !['z','y'].includes(event.key.toLowerCase())) return;
    if (!root.contains(event.target) && event.target !== $('#note-title')) return;
    event.preventDefault();event.stopImmediatePropagation();finishComposition();
    (event.key.toLowerCase() === 'y' || event.shiftKey ? undoManager.redo() : undoManager.undo());render();
  }, true);
  root.addEventListener('paste', event => {
    const html = event.clipboardData.getData('text/html'), text = event.clipboardData.getData('text/plain');
    const cell = event.target.closest('.meeting-table-cell');
    const isTable = /<table\b|data-hoikuict-table/i.test(html) || text.includes('\t') || text.startsWith('HOIKUICT_TABLE_V1\n');
    if (!cell && !isTable) return;
    event.preventDefault();event.stopImmediatePropagation();
    if (!editable()) return;
    run(() => {
      if (isTable) {if (cell) throw new Error('表の中には表を貼り付けできません。本文の挿入位置を選んでください。');const value = parseClipboard(html, text);if (!value) throw new Error('Excel等の表は未対応です。議事録の「表をコピー」でコピーしてください。');selected = null;insert(value);}
      else {const range = offsets(cell);if (range) replaceCell(cell, Math.min(range.anchor, range.focus), Math.max(range.anchor, range.focus), text);}
    });
  }, true);
  root.addEventListener('drop', event => {if (event.target.closest('.meeting-table-block')) event.preventDefault();}, true);
  document.addEventListener('selectionchange', () => {
    const selection = window.getSelection();
    const node = selection.anchorNode?.nodeType === 1 ? selection.anchorNode : selection.anchorNode?.parentElement;
    if (node?.closest('.meeting-table-cell') && selection.toString().trim()) onExcerpt(selection.toString().trim());
  });
  window.addEventListener('resize', () => requestAnimationFrame(ensureVisible));
  if (toolbar) {
    toolbar.querySelectorAll('[data-table-action]').forEach(button => button.addEventListener('click', () => run(() => action(button.dataset.tableAction))));
    $('#meeting-table-header').addEventListener('change', () => run(() => {const data = selectedModel();if (data) transact(() => data.table.set('header', $('#meeting-table-header').checked));}));
    $('#meeting-table-insert').addEventListener('click', () => {if (editable()) $('#meeting-table-insert-dialog').showModal();});
    $('#meeting-table-insert-form').addEventListener('submit', event => {
      event.preventDefault();const rows = Number($('#meeting-table-rows').value), columns = Number($('#meeting-table-columns').value);
      if (!Number.isInteger(rows) || rows < 1 || rows > MAX_ROWS || !Number.isInteger(columns) || columns < 1 || columns > MAX_COLUMNS) return;
      $('#meeting-table-insert-dialog').close();run(() => insert({version: 1, header: $('#meeting-table-new-header').checked, rows: Array.from({length: rows}, () => Array(columns).fill(''))}));
    });
    document.querySelectorAll('[data-table-close]').forEach(button => button.addEventListener('click', () => {deleteAction = null;button.closest('dialog').close();}));
    $('#meeting-table-delete-dialog').addEventListener('cancel', () => deleteAction = null);
    $('#meeting-table-delete-confirm').addEventListener('click', () => {const action = deleteAction;deleteAction = null;$('#meeting-table-delete-dialog').close();run(() => action?.());});
    $('#meeting-table-paste').addEventListener('click', () => pasteButton().catch(error => message(error.name === 'NotAllowedError' ? 'クリップボードを読み取れません。本文を選んでCtrl+Vで貼り付けるか、ブラウザーでアクセスを許可してください。' : error.message)));
    $('#meeting-undo').addEventListener('click', () => {finishComposition();undoManager.undo();render();});
    $('#meeting-redo').addEventListener('click', () => {finishComposition();undoManager.redo();render();});
  }
  return {
    enable(value) {enabled = value;if (toolbar) toolbar.hidden = !value;render();},
    clearHistory() {undoManager.clear();updateControls();},
    readyToSave() {return composing ? new Promise(resolve => waiters.push(resolve)) : Promise.resolve();},
    applyUpdate(update, source) {if (composing) queuedUpdates.push([update, source]);else Y.applyUpdate(ydoc, update, source);},
    exportOps() {return editor.getContents().ops.map(op => op.insert?.meetingTable ? {insert: {meeting_table: store.snapshot(op.insert.meetingTable)}} : op);},
    plainText() {return editor.getContents().ops.map(op => typeof op.insert === 'string' ? op.insert : op.insert?.meetingTable ? store.snapshot(op.insert.meetingTable).rows.map(row => row.join('\t')).join('\n') + '\n' : '').join('');},
  };
}
