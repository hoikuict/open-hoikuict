/* Bounded, browser-only CSV/TSV and OOXML reader; formulas and macros never execute. */
const MAX_FILE = 20 * 1024 * 1024, MAX_EXPANDED = 80 * 1024 * 1024, MAX_ROWS = 5000, MAX_COLUMNS = 300;
export function columnName(index) { let name = ''; for (let n = index + 1; n; n = Math.floor((n - 1) / 26)) name = String.fromCharCode(65 + (n - 1) % 26) + name; return name; }
function columnIndex(reference) {
  const match = String(reference).match(/^([A-Z]+)\d+$/);
  if (!match) throw Error('Excelのセル位置を読み取れません');
  let index = 0;
  for (const char of match[1]) index = index * 26 + char.charCodeAt(0) - 64;
  if (index > MAX_COLUMNS) throw Error('列は300列以内に分けてください');
  return index - 1;
}

export function parseDelimited(text, delimiter = ',') {
  text = text.replace(/^\ufeff/, '');
  if (text.includes('\0')) throw Error('文字コードを確認してください');
  const rows = []; let values = [], value = '', quoted = false, closed = false, line = 1, start = 1;
  function cell() { values.push(value); value = ''; closed = false; if (values.length > MAX_COLUMNS) throw Error('列は300列以内に分けてください'); }
  function row() { cell(); rows.push({line: start, values}); values = []; if (rows.length > MAX_ROWS + 100) throw Error('1ファイルは見出しを含め5100行以内に分けてください'); }
  for (let i = 0; i < text.length; i++) {
    const ch = text[i];
    if (quoted) {
      if (ch === '"') { if (text[i + 1] === '"') { value += '"'; i++; } else { quoted = false; closed = true; } }
      else { value += ch; if (ch === '\n') line++; }
    } else if (ch === '"') {
      if (value || closed) throw Error(`${line}行目：CSVの引用符の位置を確認してください`);
      quoted = true;
    } else if (ch === delimiter) cell();
    else if (ch === '\r' || ch === '\n') { if (ch === '\r' && text[i + 1] === '\n') i++; row(); line++; start = line; }
    else if (closed) { if (!/\s/.test(ch)) throw Error(`${line}行目：閉じた引用符の後に文字があります`); }
    else value += ch;
  }
  if (quoted) throw Error('CSVの引用符が閉じられていません');
  if (value || values.length || closed) row();
  return rows;
}

function decode(buffer, choice) {
  const bytes = new Uint8Array(buffer);
  if (choice !== 'auto') return {text: new TextDecoder(choice, {fatal: true}).decode(bytes), encoding: choice};
  if (bytes[0] === 255 && bytes[1] === 254) return {text: new TextDecoder('utf-16le', {fatal: true}).decode(bytes), encoding: 'UTF-16 LE'};
  if (bytes[0] === 254 && bytes[1] === 255) return {text: new TextDecoder('utf-16be', {fatal: true}).decode(bytes), encoding: 'UTF-16 BE'};
  try { return {text: new TextDecoder('utf-8', {fatal: true}).decode(bytes), encoding: 'UTF-8'}; }
  catch { return {text: new TextDecoder('shift_jis', {fatal: true}).decode(bytes), encoding: 'Shift-JIS'}; }
}

function chooseDelimiter(text, requested) {
  if (requested !== 'auto') return requested === 'tab' ? '\t' : requested;
  let best = ',', bestScore = 0;
  for (const delimiter of [',', '\t', ';']) {
    try {
      const rows = parseDelimited(text, delimiter).filter(r => r.values.some(Boolean)).slice(0, 25);
      const counts = new Map();
      for (const row of rows) if (row.values.length > 1) counts.set(row.values.length, (counts.get(row.values.length) || 0) + 1);
      const score = Math.max(0, ...[...counts].map(([width, count]) => count * 1000 + width));
      if (score > bestScore) { best = delimiter; bestScore = score; }
    } catch { /* Another delimiter may explain quotes and columns correctly. */ }
  }
  return best;
}

function xml(text) {
  if (!text || /<!DOCTYPE|<!ENTITY/i.test(text)) throw Error('通常のExcel XMLではありません');
  const doc = new DOMParser().parseFromString(text, 'application/xml');
  if (doc.getElementsByTagName('parsererror').length) throw Error('Excel内部のXMLを読み取れません');
  return doc;
}
const tags = (node, name) => Array.from(node.getElementsByTagNameNS('*', name));

const crcTable = Array.from({length: 256}, (_, n) => { let value = n; for (let i = 0; i < 8; i++) value = value >>> 1 ^ (value & 1 ? 0xedb88320 : 0); return value >>> 0; });
function crc32(bytes) { let crc = 0xffffffff; for (const byte of bytes) crc = crc >>> 8 ^ crcTable[(crc ^ byte) & 255]; return (crc ^ 0xffffffff) >>> 0; }
async function unpack(buffer) {
  const bytes = new Uint8Array(buffer), view = new DataView(buffer); let end = -1;
  for (let i = bytes.length - 22; i >= Math.max(0, bytes.length - 65557); i--) if (view.getUint32(i, true) === 0x06054b50 && i + 22 + view.getUint16(i + 20, true) === bytes.length) { end = i; break; }
  if (end < 0) throw Error('通常の.xlsxではありません。暗号化を解除し、.xlsxで保存し直してください');
  if (view.getUint16(end + 4, true) || view.getUint16(end + 6, true)) throw Error('分割ZIPには対応していません');
  let cursor = view.getUint32(end + 16, true), total = 0, expanded = 0;
  const entries = new Map(), count = view.getUint16(end + 10, true);
  if (count > 3000 || cursor + view.getUint32(end + 12, true) > end) throw Error('Excelのファイル構成が大きすぎるか不正です');
  for (let i = 0; i < count; i++) {
    if (cursor + 46 > end || view.getUint32(cursor, true) !== 0x02014b50) throw Error('Excelの圧縮構造を確認してください');
    const flags = view.getUint16(cursor + 8, true), method = view.getUint16(cursor + 10, true), crc = view.getUint32(cursor + 16, true), size = view.getUint32(cursor + 20, true), raw = view.getUint32(cursor + 24, true);
    const nl = view.getUint16(cursor + 28, true), el = view.getUint16(cursor + 30, true), cl = view.getUint16(cursor + 32, true), offset = view.getUint32(cursor + 42, true);
    if (cursor + 46 + nl + el + cl > end || offset + 30 > buffer.byteLength || flags & 1 || ![0, 8].includes(method)) throw Error('暗号化・特殊な圧縮形式のExcelには対応していません');
    total += raw;
    if (total > MAX_EXPANDED) throw Error('展開後80MB以内のExcelに分けてください');
    const name = new TextDecoder('utf-8', {fatal: true}).decode(bytes.slice(cursor + 46, cursor + 46 + nl));
    if (name.startsWith('/') || name.split('/').includes('..') || entries.has(name)) throw Error('Excel内のファイル名が不正です');
    if (view.getUint32(offset, true) !== 0x04034b50) throw Error('Excelのデータ位置が不正です');
    const start = offset + 30 + view.getUint16(offset + 26, true) + view.getUint16(offset + 28, true);
    if (start + size > view.getUint32(end + 16, true)) throw Error('Excelのデータサイズが不正です');
    entries.set(name, {method, crc, size, raw, start}); cursor += 46 + nl + el + cl;
  }
  const cache = new Map();
  return async name => {
    if (cache.has(name)) return cache.get(name);
    const entry = entries.get(name); if (!entry) return null;
    const packed = bytes.slice(entry.start, entry.start + entry.size); let data;
    if (entry.method === 0) data = packed;
    else {
      if (typeof DecompressionStream === 'undefined') throw Error('新しいChrome・Edgeで開いてください');
      const reader = new Blob([packed]).stream().pipeThrough(new DecompressionStream('deflate-raw')).getReader();
      const chunks = []; let length = 0;
      try { while (true) { const {done, value} = await reader.read(); if (done) break; length += value.length; if (length > entry.raw || expanded + length > MAX_EXPANDED) { await reader.cancel(); throw Error('Excelの展開サイズが上限を超えました'); } chunks.push(value); } }
      finally { reader.releaseLock(); }
      data = new Uint8Array(length); let offset = 0; for (const chunk of chunks) { data.set(chunk, offset); offset += chunk.length; }
    }
    expanded += data.length;
    if (data.length !== entry.raw || crc32(data) !== entry.crc || expanded > MAX_EXPANDED) throw Error('Excelの内容が破損しているか、サイズが不正です');
    const text = new TextDecoder('utf-8', {fatal: true}).decode(data); cache.set(name, text); return text;
  };
}

function sheetPath(target) {
  if (!target || /^[a-z]+:/i.test(target)) throw Error('外部のExcelシートは読み込みません');
  const path = target.startsWith('/') ? target.slice(1) : `xl/${target}`;
  const parts = [];
  for (const part of path.split('/')) { if (part === '..') { if (!parts.length) throw Error('Excelの参照先が不正です'); parts.pop(); } else if (part && part !== '.') parts.push(part); }
  if (parts[0] !== 'xl') throw Error('Excelの参照先が不正です');
  return parts.join('/');
}

async function readWorkbook(buffer) {
  const get = await unpack(buffer), workbook = xml(await get('xl/workbook.xml')), relationships = xml(await get('xl/_rels/workbook.xml.rels'));
  const stringsXml = await get('xl/sharedStrings.xml');
  const strings = stringsXml ? tags(xml(stringsXml), 'si').map(item => tags(item, 't').map(t => t.textContent).join('')) : [];
  const relations = new Map(tags(relationships, 'Relationship').filter(r => r.getAttribute('TargetMode') !== 'External').map(r => [r.getAttribute('Id'), r.getAttribute('Target')]));
  const stylesXml = await get('xl/styles.xml'); let formats = [];
  if (stylesXml) {
    const styles = xml(stylesXml), custom = new Map(tags(styles, 'numFmt').map(item => [item.getAttribute('numFmtId'), item.getAttribute('formatCode')]));
    formats = tags(styles, 'cellXfs').flatMap(node => tags(node, 'xf')).map(item => custom.get(item.getAttribute('numFmtId')) || '');
  }
  const epoch = ['1', 'true'].includes(tags(workbook, 'workbookPr')[0]?.getAttribute('date1904'));
  const sheets = tags(workbook, 'sheet').map(item => ({name: item.getAttribute('name'), target: relations.get(item.getAttributeNS('http://schemas.openxmlformats.org/officeDocument/2006/relationships', 'id'))}));
  if (!sheets.length || sheets.length > 100) throw Error('シート数を確認してください');
  return {sheets, epoch, encoding: 'Excel', async read(index) {
    const sheet = xml(await get(sheetPath(sheets[index]?.target)));
    const xmlRows = tags(sheet, 'row');
    if (xmlRows.length > MAX_ROWS + 100) throw Error('1シートは見出しを含め5100行以内に分けてください');
    const rows = xmlRows.map(row => {
      const line = Number(row.getAttribute('r')), values = [], formulaMissing = [], formulas = [];
      if (!Number.isInteger(line) || line < 1) throw Error('Excelの行番号が不正です');
      const seen = new Set();
      for (const cell of tags(row, 'c')) {
        const col = columnIndex(cell.getAttribute('r'));
        if (seen.has(col)) throw Error('Excelに同じセル位置が重複しています'); seen.add(col);
        const type = cell.getAttribute('t'), raw = tags(cell, 'v')[0]?.textContent;
        if (tags(cell, 'f').length) { formulas.push(col); if (raw === undefined) formulaMissing.push(col); }
        let value = type === 's' ? strings[Number(raw)] : type === 'inlineStr' ? tags(cell, 't').map(t => t.textContent).join('') : raw === undefined ? '' : ['str', 'd', 'e'].includes(type) ? raw : type === 'b' ? raw === '1' ? 'true' : 'false' : Number(raw);
        if (type === 's' && value === undefined) throw Error('Excelの共有文字列が見つかりません');
        if (typeof value === 'number' && !Number.isFinite(value)) throw Error('Excelの数値が不正です');
        const format = formats[Number(cell.getAttribute('s'))] || '';
        if (typeof value === 'number' && Number.isInteger(value) && value >= 0 && /^0{2,30}$/.test(format)) value = String(value).padStart(format.length, '0');
        values[col] = value;
      }
      return {line, values, formulaMissing, formulas};
    });
    const lines = rows.map(r => r.line); if (new Set(lines).size !== lines.length) throw Error('Excelの行が重複しています');
    const merges = tags(sheet, 'mergeCell').map(item => item.getAttribute('ref')).filter(Boolean);
    return {rows, merges};
  }};
}

export async function readSource(file, {encoding = 'auto', delimiter = 'auto'} = {}) {
  if (!file || file.size === 0 || file.size > MAX_FILE) throw Error('データの入った20MB以内のファイルを選択してください');
  const extension = file.name.split('.').pop().toLowerCase(), buffer = await file.arrayBuffer();
  if (extension === 'xlsx') return readWorkbook(buffer);
  if (!['csv', 'tsv', 'txt'].includes(extension)) throw Error('.xlsx・.csv・.tsvを選択してください');
  let decoded;
  try { decoded = decode(buffer, encoding); } catch { throw Error('文字コードを読み取れません。文字コードを選び直してください'); }
  const separator = chooseDelimiter(decoded.text, delimiter), rows = parseDelimited(decoded.text, separator);
  return {sheets: [{name: file.name}], epoch: false, encoding: decoded.encoding + ' / ' + (separator === '\t' ? 'タブ区切り' : separator === ';' ? 'セミコロン区切り' : 'カンマ区切り'), async read() { return {rows, merges: []}; }};
}

export function sourceTable(sheet, headerLine, depth = 1) {
  if (!Number.isInteger(headerLine) || headerLine < 1 || headerLine > 100 || ![1, 2, 3].includes(depth)) throw Error('見出しは1〜100行目から、1〜3行で指定してください');
  const head = Array.from({length: depth}, (_, i) => [...(sheet.rows.find(row => row.line === headerLine + i)?.values || [])]);
  for (const reference of sheet.merges) {
    const match = reference.match(/^([A-Z]+)(\d+):([A-Z]+)(\d+)$/); if (!match) continue;
    const firstLine = Number(match[2]), lastLine = Number(match[4]);
    if (firstLine < headerLine || lastLine >= headerLine + depth) continue;
    const first = columnIndex(match[1] + '1'), last = columnIndex(match[3] + '1'), text = head[firstLine - headerLine][first];
    for (let line = firstLine; line <= lastLine; line++) for (let col = first; col <= last; col++) if (!head[line - headerLine][col]) head[line - headerLine][col] = text;
  }
  const width = Math.max(0, ...sheet.rows.map(row => row.values.length));
  if (!width || width > MAX_COLUMNS) throw Error('データのある列を確認してください');
  const headers = Array.from({length: width}, (_, col) => {
    const name = [...new Set(head.map(row => String(row[col] ?? '').trim()).filter(Boolean))].join(' / ');
    return {name, label: `${columnName(col)}：${name || '見出しなし'}`};
  });
  if (!headers.some(h => h.name)) throw Error('見出しが見つかりません。開始行を指定してください');
  const rows = sheet.rows.filter(row => row.line >= headerLine + depth && row.values.some(value => value !== '' && value != null));
  if (rows.length > MAX_ROWS) throw Error('変換するデータは5000行以内に分けてください');
  if (!rows.length) throw Error('見出しの下にデータがありません');
  return {headers, rows};
}
