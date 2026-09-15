/* Pure conversion functions. No storage, network, credentials or application writes. */
export const norm = value => String(value ?? '').normalize('NFKC').trim();
const headerKey = value => norm(value).toLowerCase().replace(/[\s＿_()（）「」【】\[\]・/／-]/g, '');
export const kana = value => norm(value).replace(/[ぁ-ゖ]/g, ch => String.fromCharCode(ch.charCodeAt(0) + 96));
export const isId = header => /ID$/.test(header);
export const transforms = {
  copy: 'そのまま', surname: '姓名から姓を分ける', given: '姓名から名を分ける',
  surname_kana: 'フリガナから姓カナ', given_kana: 'フリガナから名カナ',
  kana: '全角カタカナにする', date: '日付を西暦にする', excel_date: 'Excelの日付番号を変換',
  sex: '性別を揃える', status: '在園状態を揃える',
};

export function dateValue(value, epoch = false, serialText = false) {
  if (value === '' || value == null) return '';
  if (typeof value === 'number' || serialText && /^\d+(?:\.\d+)?$/.test(norm(value))) {
    const number = Math.floor(Number(value));
    if (!Number.isFinite(number) || number < (epoch ? 0 : 1) || number > 2958465 || !epoch && number === 60) throw Error('Excelの日付番号を確認してください');
    const base = epoch ? Date.UTC(1904, 0, 1) : Date.UTC(1899, 11, number < 60 ? 31 : 30);
    const converted = new Date(base + number * 86400000).toISOString().slice(0, 10);
    if (!/^\d{4}-\d{2}-\d{2}$/.test(converted)) throw Error('日付の範囲を確認してください');
    return converted;
  }
  let text = norm(value), era = null;
  const eras = {令和: [2018, '2019-05-01', '9999-12-31'], R: [2018, '2019-05-01', '9999-12-31'], 平成: [1988, '1989-01-08', '2019-04-30'], H: [1988, '1989-01-08', '2019-04-30'], 昭和: [1925, '1926-12-25', '1989-01-07'], S: [1925, '1926-12-25', '1989-01-07']};
  const eraMatch = text.match(/^(令和|平成|昭和|R|H|S)\s*(元|\d+)[年.\/-](\d{1,2})[月.\/-](\d{1,2})日?$/i);
  if (eraMatch) {
    era = eras[eraMatch[1].toUpperCase()];
    text = `${era[0] + (eraMatch[2] === '元' ? 1 : Number(eraMatch[2]))}-${eraMatch[3]}-${eraMatch[4]}`;
  }
  if (/^\d{8}$/.test(text)) text = `${text.slice(0, 4)}-${text.slice(4, 6)}-${text.slice(6)}`;
  const match = text.match(/^(\d{4})[年/.-](\d{1,2})[月/.-](\d{1,2})日?(?:(?:T|\s)00:00(?::00(?:\.0+)?)?Z?)?$/);
  if (!match) throw Error('日付を YYYY-MM-DD に直してください');
  const year = Number(match[1]), month = Number(match[2]), day = Number(match[3]);
  const d = new Date(Date.UTC(year, month - 1, day));
  if (year < 1000 || d.getUTCFullYear() !== year || d.getUTCMonth() !== month - 1 || d.getUTCDate() !== day) throw Error('存在する日付を指定してください');
  const output = d.toISOString().slice(0, 10);
  if (era && (output < era[1] || output > era[2])) throw Error('元号と日付の組み合わせを確認してください');
  return output;
}

export function transformValue(value, method = 'copy', epoch = false) {
  if (value === '' || value == null) return '';
  if (method === 'date' || method === 'excel_date') return dateValue(value, epoch, method === 'excel_date');
  if (['surname', 'given', 'surname_kana', 'given_kana'].includes(method)) {
    const parts = norm(value).split(/\s+/);
    if (parts.length !== 2) throw Error('姓と名を空白で分けるか、変換結果に直接入力してください');
    const part = parts[method.startsWith('surname') ? 0 : 1];
    return method.endsWith('_kana') ? kana(part) : part;
  }
  if (method === 'kana') return kana(value);
  if (method === 'sex') {
    const values = {'男': 'male', '男児': 'male', '男性': 'male', male: 'male', M: 'male', '女': 'female', '女児': 'female', '女性': 'female', female: 'female', F: 'female', '未設定': 'not_set', '不明': 'not_set', not_set: 'not_set'};
    if (!(norm(value) in values)) throw Error('性別の値を「値の置き換え」で指定してください');
    return values[norm(value)];
  }
  if (method === 'status') {
    const values = {'在園': 'enrolled', '在園中': 'enrolled', enrolled: 'enrolled', '卒園': 'graduated', '卒園済': 'graduated', graduated: 'graduated', '退園': 'withdrawn', '退園済': 'withdrawn', withdrawn: 'withdrawn'};
    if (!(norm(value) in values)) throw Error('在園状態の値を「値の置き換え」で指定してください');
    return values[norm(value)];
  }
  if (method !== 'copy') throw Error('変換方法を選び直してください');
  return norm(value);
}

function defaultTransform(header) {
  if (/生年月日|入園日|退園日/.test(header)) return 'date';
  if (/カナ/.test(header)) return 'kana';
  if (header === '性別') return 'sex';
  if (header === '在園状態') return 'status';
  return 'copy';
}

export function makeTargets(mode, childCount, schemas) {
  const specs = mode === 'combined' ? [['families', 0], ...Array.from({length: childCount}, (_, i) => ['children', i + 1])] : [[mode === 'guardian_rows' ? 'families' : mode, mode === 'children' ? 1 : 0]];
  return specs.flatMap(([dataset, slot]) => {
    const schema = schemas.find(item => item.id === dataset);
    if (!schema) throw Error('対応するデータを選択してください');
    return schema.headers.filter(header => (mode !== 'combined' || dataset !== 'children' || !['家庭ID', '家庭名', '住所', '電話番号'].includes(header)) && (mode !== 'guardian_rows' || !header.startsWith('保護者②'))).map(header => ({
      key: `${dataset}:${slot}:${header}`, dataset, slot, header, layout: mode,
      group: mode === 'combined' && dataset === 'children' ? `園児${slot}` : schema.label,
      defaultTransform: defaultTransform(header),
    }));
  });
}

const commonAliases = {
  家庭名: ['家庭名', '家族名', '世帯名'], 住所: ['住所', '自宅住所', '現住所'], 電話番号: ['電話番号', '自宅電話番号', '電話', '携帯電話番号', 'TEL'],
  クラス名: ['クラス名', 'クラス', '組', '所属クラス'], 表示名: ['表示名', '氏名', '名前', '職員名', '職員氏名'],
  メールアドレス: ['メールアドレス', 'メール', 'email', 'e-mail'], 生年月日: ['生年月日', '誕生日', 'birthdate', 'dateofbirth'],
  入園日: ['入園日', '入所日', '入園年月日', '入所年月日'], 退園日: ['退園日', '退所日', '退園年月日'], 性別: ['性別', '男女', 'sex', 'gender'],
  姓: ['姓', '苗字', '名字', '園児姓', '児童姓', 'lastname'], 名: ['名', '園児名(名)', '児童名(名)', 'firstname'],
  姓カナ: ['姓カナ', '姓フリガナ', '姓ふりがな', 'セイ'], 名カナ: ['名カナ', '名フリガナ', '名ふりがな', 'メイ'],
};

export function suggestMapping(target, headers) {
  const base = {column: null, transform: target.defaultTransform, fallback: '', replacements: ''};
  if (isId(target.header)) return base;
  let exact = commonAliases[target.header] || [target.header], full = [];
  let splitMethod = '';
  if (target.dataset === 'children') {
    const n = target.slot, suffix = n === 1 ? '' : String(n);
    exact = exact.flatMap(alias => n === 1 ? [alias, `園児1${alias}`, `${alias}1`, `お子様${alias}`] : [`${alias}${n}`, `園児${n}${alias}`, `子ども${n}${alias}`]);
    if (['姓', '名'].includes(target.header)) { full = ['お子様の名前', '園児氏名', '園児名', '児童氏名', '児童名', '氏名', '名前', 'childname'].map(h => h + suffix); splitMethod = target.header === '姓' ? 'surname' : 'given'; }
    if (['姓カナ', '名カナ'].includes(target.header)) { full = ['お子様の名前(ふりがな)', '園児氏名カナ', '園児名カナ', 'フリガナ', 'ふりがな', '氏名カナ'].map(h => h + suffix); splitMethod = target.header === '姓カナ' ? 'surname_kana' : 'given_kana'; }
  }
  const guardian = target.header.match(/^保護者([①②])(.+)$/);
  if (guardian) {
    const n = norm(guardian[1]), field = guardian[2];
    exact = [`保護者${n}${field}`];
    // 「保護者名①」は姓名。「保護者①名」だけが名の専用列。
    if (!['名', '名カナ'].includes(field)) exact.push(`保護者${field}${n}`);
    if (field === '電話番号') exact.push(`保護者${n}携帯電話番号`);
    if (field === '勤務先') exact.push(`保護者${n}勤務先名`);
    if (field === '続柄') exact.push(n === '1' ? '続柄' : '続柄2');
    if (['姓', '名'].includes(field)) { full = [`保護者名${n}`, `保護者${n}氏名`, `保護者${n}名前`]; splitMethod = field === '姓' ? 'surname' : 'given'; }
    if (['姓カナ', '名カナ'].includes(field)) { full = [`保護者名${n}(ふりがな)`, `保護者名カナ${n}`, `保護者${n}氏名カナ`, `保護者${n}ふりがな`]; splitMethod = field === '姓カナ' ? 'surname_kana' : 'given_kana'; }
    if (target.layout === 'guardian_rows') {
      exact.push(...(commonAliases[field] || [field]).filter(h => !/園児|児童/.test(h)));
      if (!['名', '名カナ'].includes(field)) exact.push(`保護者${field}`);
      if (['姓', '名'].includes(field)) full.push('氏名', '名前', '保護者名', '保護者氏名');
      if (['姓カナ', '名カナ'].includes(field)) full.push('フリガナ', 'ふりがな', '氏名カナ', '保護者名カナ');
    }
  }
  if (target.layout === 'guardian_rows' && target.header === '電話番号') exact = ['自宅電話番号', '家庭電話番号', '世帯電話番号'];
  for (const [aliases, method] of [[exact, target.defaultTransform], [full, splitMethod]]) {
    const keys = new Set(aliases.map(headerKey));
    const found = headers.map((h, i) => keys.has(headerKey(h.name)) ? i : -1).filter(i => i >= 0);
    if (found.length === 1) return {...base, column: found[0], transform: method};
    if (found.length > 1) return base;
  }
  return base;
}

function replacements(text) {
  const map = new Map();
  for (const line of text.split('\n').filter(line => line.trim())) {
    const at = line.indexOf('=');
    if (at < 1) throw Error('値の置き換えは「元の値=変更後」で1行ずつ入力してください');
    const key = norm(line.slice(0, at));
    if (map.has(key)) throw Error('値の置き換えに同じ元の値が重複しています');
    map.set(key, norm(line.slice(at + 1)));
  }
  return map;
}

export function convertRows(source, targets, mappings, options, schemas) {
  if (options.mode === 'guardian_rows' && (options.familyKey == null || options.guardianColumn == null || !norm(options.guardianFirst) || !norm(options.guardianSecond) || norm(options.guardianFirst) === norm(options.guardianSecond))) throw Error('保護者1人1行の表では、家族番号の列、保護者の区分の列、①・②を区別する値を指定してください');
  const outputs = {}, notes = new Set(), groups = new Map();
  for (const dataset of new Set(targets.map(t => t.dataset))) outputs[dataset] = {headers: schemas.find(s => s.id === dataset).headers, rows: []};
  const rules = new Map(targets.map(target => [target.key, replacements(mappings[target.key]?.replacements || '')]));
  const targetGroups = Map.groupBy ? Map.groupBy(targets, t => `${t.dataset}:${t.slot}`) : targets.reduce((map, t) => {const key = `${t.dataset}:${t.slot}`; if (!map.has(key)) map.set(key, []); map.get(key).push(t); return map;}, new Map());
  let rowNumber = 0;
  for (const row of source) {
    if (!row.values.some(value => norm(value))) continue;
    const pending = [];
    for (const group of targetGroups.values()) {
      const dataset = group[0].dataset, values = {}, inputErrors = {};
      for (const target of group) {
        const mapping = mappings[target.key] || {};
        let value = mapping.column == null ? '' : row.values[mapping.column] ?? '';
        if (isId(target.header) && !options.allowIds) value = '';
        else if (norm(value) === '') value = mapping.fallback || '';
        if (typeof value === 'number' && /電話/.test(target.header)) notes.add(`${row.line}行目：電話番号がExcelの数値です。先頭の0を原本と確認してください。`);
        if (typeof value === 'number' && (!Number.isSafeInteger(value) && !/年月日|園日/.test(target.header))) notes.add(`${row.line}行目：数値の桁・小数を原本と確認してください。`);
        if (mapping.column != null && row.formulaMissing?.includes(mapping.column)) inputErrors[target.header] = '計算結果が保存されていません。元のExcelで再計算するか、値を入力してください';
        if (mapping.column != null && row.formulas?.includes(mapping.column)) notes.add(`${row.line}行目：数式の保存済み計算結果を使用しています。原本の再計算結果を確認してください。`);
        try {
          const replacement = rules.get(target.key);
          if (replacement.has(norm(value))) value = replacement.get(norm(value));
          values[target.header] = transformValue(value, mapping.transform || target.defaultTransform, options.epoch);
        } catch (error) { values[target.header] = norm(value); inputErrors[target.header] = error.message; }
      }
      pending.push({id: `row-${++rowNumber}`, dataset, slot: group[0].slot, values, inputErrors, blockers: [], sourceLines: [row.line], include: true});
    }
    if (['combined', 'guardian_rows'].includes(options.mode)) {
      const family = pending.find(r => r.dataset === 'families');
      if (options.mode === 'guardian_rows') {
        const marker = norm(row.values[options.guardianColumn]);
        if (marker === norm(options.guardianSecond)) {
          family.values = Object.fromEntries(Object.entries(family.values).map(([key, value]) => [key.replace(/^保護者①/, '保護者②'), value]));
          family.inputErrors = Object.fromEntries(Object.entries(family.inputErrors).map(([key, value]) => [key.replace(/^保護者①/, '保護者②'), value]));
        } else if (marker !== norm(options.guardianFirst)) family.blockers.push(`保護者の区分「${marker || '空欄'}」を①・②に対応付けられません。区分の設定か元データを確認してください。3人目以降は対象外です`);
      }
      const keyValue = options.familyKey == null ? '' : norm(row.values[options.familyKey]);
      const key = keyValue ? `key:${keyValue}` : `line:${row.line}`;
      if (options.familyKey != null && !keyValue) family.blockers.push('家庭をまとめる番号が空欄です。元データを補うか、まとめない設定で確認してください');
      if (!family.values['家庭名']) {
        const name = pending.find(r => r.dataset === 'children' && r.values['姓'])?.values['姓'] || family.values['保護者①姓'] || family.values['保護者②姓'];
        family.values['家庭名'] = name ? `${name}家` : '';
        notes.add('家庭名の空欄を姓＋「家」で補っています。同名の別家庭は変換結果で区別してください。');
      }
      let shared = groups.get(key);
      if (!shared) { shared = family; groups.set(key, shared); outputs.families.rows.push(shared); }
      else {
        shared.sourceLines.push(row.line);
        shared.blockers.push(...family.blockers);
        for (const [header, value] of Object.entries(family.values)) {
          if (value && shared.values[header] && value !== shared.values[header]) shared.inputErrors[header] = `同じ家庭の${shared.sourceLines.join('・')}行で値が異なります。原本を確認して統一する値を入力してください`;
          else if (value) shared.values[header] = value;
        }
        Object.assign(shared.inputErrors, family.inputErrors);
      }
      for (const child of pending.filter(r => r.dataset === 'children')) {
        if (!['姓', '名', '姓カナ', '名カナ', '生年月日'].some(h => child.values[h])) continue;
        child.familyRef = shared.id;
        outputs.children.rows.push(child);
      }
    } else for (const converted of pending) outputs[converted.dataset].rows.push(converted);
  }
  return {outputs, notes: [...notes], mode: options.mode};
}

export function refreshLinks(result) {
  if (result.mode !== 'combined') return;
  const families = new Map(result.outputs.families.rows.map(row => [row.id, row]));
  for (const child of result.outputs.children.rows) {
    const family = families.get(child.familyRef);
    for (const [to, from] of [['家庭ID', 'ID'], ['家庭名', '家庭名'], ['住所', '住所'], ['電話番号', '電話番号']]) child.values[to] = family?.values[from] || '';
  }
}

export function validateResult(result) {
  refreshLinks(result);
  const issues = [];
  const includedFamilies = new Set((result.outputs.families?.rows || []).filter(row => row.include).map(row => row.id));
  const add = (dataset, row, header, message) => issues.push({dataset, rowId: row.id, lines: row.sourceLines, header, message});
  for (const [dataset, output] of Object.entries(result.outputs)) {
    const active = output.rows.filter(row => row.include), identities = new Map();
    for (const row of active) {
      const values = row.values;
      for (const blocker of row.blockers || []) add(dataset, row, '元データ', blocker);
      for (const [header, message] of Object.entries(row.inputErrors)) add(dataset, row, header, message);
      const required = dataset === 'children' ? ['姓', '名', '姓カナ', '名カナ', '生年月日', '入園日'] : dataset === 'families' ? ['家庭名'] : dataset === 'classrooms' ? ['クラス名'] : dataset === 'staff_users' ? ['表示名', 'メールアドレス'] : dataset === 'parent_accounts' ? ['表示名', 'メールアドレス'] : [];
      for (const header of required) if (!norm(values[header])) add(dataset, row, header, '入力してください');
      for (const [header, value] of Object.entries(values)) {
        if (!value) continue;
        if (isId(header) && !(dataset === 'staff_users' && header === 'ID' ? /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(value) : /^[1-9]\d*$/.test(value))) add(dataset, row, header, 'open-hoikuictから書き出したIDを確認してください');
        if (/生年月日|入園日|退園日/.test(header)) { try { if (dateValue(value) !== value) throw Error(); } catch { add(dataset, row, header, 'YYYY-MM-DD の日付に直してください'); } }
        if (/カナ/.test(header) && !/^[ァ-ヺー ・]+$/.test(value)) add(dataset, row, header, '全角カタカナで入力してください');
        if (/メール/.test(header) && !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(value)) add(dataset, row, header, 'メールアドレスを確認してください');
        if (/^[=+@]/.test(value) && !(/電話/.test(header) && /^\+\d[\d\s().-]*$/.test(value))) add(dataset, row, header, '数式として扱われる先頭文字を確認し、値を入力してください');
      }
      if (dataset === 'families') for (const number of ['①', '②']) {
        if (Object.entries(values).some(([header, value]) => header.startsWith(`保護者${number}`) && value)) for (const part of ['姓', '名']) if (!values[`保護者${number}${part}`]) add(dataset, row, `保護者${number}${part}`, '保護者情報がある場合は姓と名の両方が必要です');
      }
      if (dataset === 'children' && row.familyRef && !includedFamilies.has(row.familyRef)) add(dataset, row, '家庭名', '所属する家庭が出力対象から外れています');
      let identity = values.ID ? `id:${values.ID}` : '';
      if (!identity && dataset === 'children' && values['姓カナ'] && values['名カナ'] && values['生年月日']) identity = ['姓カナ', '名カナ', '生年月日'].map(h => values[h]).join('|');
      if (!identity && dataset === 'families') identity = result.mode === 'combined' ? values['家庭名'] : `${values['家庭名']}|${values['電話番号']}`;
      if (!identity && ['staff_users', 'parent_accounts'].includes(dataset)) identity = values['メールアドレス']?.toLowerCase();
      if (!identity && dataset === 'classrooms') identity = values['クラス名'];
      if (identity) { if (!identities.has(identity)) identities.set(identity, []); identities.get(identity).push(row); }
    }
    for (const rows of identities.values()) if (rows.length > 1) for (const row of rows) add(dataset, row, dataset === 'families' ? '家庭名' : output.headers[0], '同じ対象が重複しています。家庭のまとめ方・ID・出力対象を確認してください');
  }
  return issues;
}

export function csvText(output) {
  const matrix = [output.headers, ...output.rows.filter(row => row.include).map(row => output.headers.map(header => row.values[header] || ''))];
  return '\ufeff' + matrix.map(row => row.map(value => '"' + String(value).replaceAll('"', '""') + '"').join(',')).join('\r\n') + '\r\n';
}

export function saveProfile(headers, targets, mappings, options) {
  return {kind: 'open-hoikuict-migration', version: 1, mode: options.mode, childCount: options.childCount, headerDepth: options.headerDepth,
    familyKey: options.familyKey == null ? null : {name: headers[options.familyKey].name, index: options.familyKey},
    guardianColumn: options.guardianColumn == null ? null : {name: headers[options.guardianColumn].name, index: options.guardianColumn}, guardianFirst: options.guardianFirst || '1', guardianSecond: options.guardianSecond || '2',
    mappings: targets.map(target => { const mapping = mappings[target.key] || {}; return {target: target.key, source: mapping.column == null ? null : {name: headers[mapping.column].name, index: mapping.column}, transform: mapping.transform || target.defaultTransform, replacements: mapping.replacements || ''}; }),
  };
}

export function loadProfile(profile, headers, targets) {
  if (!profile || profile.kind !== 'open-hoikuict-migration' || profile.version !== 1 || !Array.isArray(profile.mappings) || profile.mappings.length > 200) throw Error('このアプリの変換設定ファイルを選択してください');
  const allowed = new Set(targets.map(t => t.key)), mapping = {}, missing = [];
  function resolve(source) {
    if (source == null) return null;
    if (typeof source.name !== 'string') throw Error('変換設定の列情報を確認してください');
    const matches = headers.map((h, i) => h.name === source.name ? i : -1).filter(i => i >= 0);
    if (matches.length === 1) return matches[0];
    missing.push(source.name + (matches.length > 1 ? '（同名列が複数）' : '（元データにない列）'));
    return null;
  }
  for (const item of profile.mappings) {
    if (!allowed.has(item.target) || Object.hasOwn(mapping, item.target) || !Object.hasOwn(transforms, item.transform) || typeof item.replacements !== 'string' || item.replacements.length > 10000) throw Error('変換設定の項目・変換方法を確認してください');
    replacements(item.replacements);
    mapping[item.target] = {column: resolve(item.source), transform: item.transform, replacements: item.replacements, fallback: ''};
  }
  if (typeof (profile.guardianFirst ?? '1') !== 'string' || typeof (profile.guardianSecond ?? '2') !== 'string') throw Error('保護者区分の設定を確認してください');
  return {mapping, familyKey: resolve(profile.familyKey), guardianColumn: resolve(profile.guardianColumn), guardianFirst: profile.guardianFirst ?? '1', guardianSecond: profile.guardianSecond ?? '2', missing};
}
