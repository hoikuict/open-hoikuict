(function (root) {
  'use strict';
  const fields = [];
  const add = (group, key, required, help, type = 'text', options = []) => fields.push({group, key, required, help, type, options});
  add('園児と所属', 'きょうだいグループ', false, 'きょうだいだけ同じ文字を入力。例 A。空欄なら園児ごとに別家庭。整理番号と家庭名は読み込み後に自動設定します。');
  add('園児と所属', 'クラス名', false, '同じクラス名は1クラスとして登録する案です。空欄はクラス未設定。');
  add('園児と所属', 'クラス表示順', false, '1以上の整数。同じクラスでは同じ値。空欄はファイルの初出順。', 'integer');
  for (const key of ['姓', '名', '姓カナ', '名カナ']) add('園児と所属', key, true, key.includes('カナ') ? '園児の氏名をカタカナで入力。' : '園児の姓と名を別の列へ貼り付けます。');
  add('園児と所属', '生年月日', true, '西暦の日付。例 2022/04/10。', 'date');
  add('園児と所属', '入園日', true, '西暦の日付。例 2026/04/01。', 'date');
  add('園児と所属', '在園状態', true, '在園・卒園・退園から選択。', 'select', ['在園','卒園','退園']);
  add('園児と所属', '性別', false, '未設定・男・女から選択。空欄は未設定。', 'select', ['未設定','男','女']);
  add('園児と所属', '退園日', false, '必要な場合に西暦の日付で入力。', 'date');
  add('住所と連絡先', '家庭住所', false, '家庭共通の住所。');
  add('住所と連絡先', '家庭電話番号', false, '文字列で入力。先頭の0を維持します。', 'phone');
  add('住所と連絡先', '園児住所', false, '家庭と異なる場合だけ入力。空欄は家庭住所を利用する案です。');
  add('住所と連絡先', '園児電話番号', false, '家庭と異なる場合だけ入力。空欄は家庭電話番号を利用する案です。', 'phone');
  const guardianFields = ['姓','名','姓カナ','名カナ','続柄','メールアドレス','電話番号','勤務先','勤務先住所','勤務先電話番号'];
  for (const n of ['①','②']) for (const key of guardianFields) {
    let help = ['姓','名'].includes(key) ? 'この保護者の情報を入力する場合は姓・名の両方が必要です。' : '任意。同じ家庭の兄弟姉妹では同じ保護者情報にします。';
    if (key === 'メールアドレス') help = '連絡先として保存する案です。アカウント作成・招待送信は行いません。共用メールも記入できます。';
    add(`保護者${n}`, `保護者${n}${key}`, false, help, key.includes('電話番号') ? 'phone' : key === 'メールアドレス' ? 'email' : 'text');
  }
  add('任意の照合情報', '照合用氏名', false, '保護者の利用開始時に照合する園児名。空欄は園児氏名カナを使う案です。');
  add('任意の照合情報', '照合用氏名種別', false, '照合用氏名とセットで入力。カナ名は kana、英字名は latin。', 'select', ['kana','latin']);
  const groups = [...new Set(fields.map(f => f.group))];
  const blank = () => Object.fromEntries(fields.map(f => [f.key, '']));
  const sample = () => {
    const a = {...blank(), きょうだいグループ:'A', クラス名:'ひよこ組', クラス表示順:'1', 姓:'見本', 名:'花', 姓カナ:'ミホン', 名カナ:'ハナ', 生年月日:'2022-04-10', 入園日:'2026-04-01', 在園状態:'在園', 性別:'女', 家庭住所:'見本市サンプル町1-1', 家庭電話番号:'000-0000-0001', '保護者①姓':'見本', '保護者①名':'春', '保護者①姓カナ':'ミホン', '保護者①名カナ':'ハル', '保護者①続柄':'母', '保護者①メールアドレス':'sample-parent1@example.invalid', '保護者①電話番号':'000-0000-1001', '保護者①勤務先':'架空の勤務先', '保護者②姓':'見本', '保護者②名':'夏', '保護者②続柄':'父'};
    const b = {...a, 名:'空', 名カナ:'ソラ', 生年月日:'2024-05-20', 性別:'男'};
    const c = {...blank(), クラス名:'うさぎ組', クラス表示順:'2', 姓:'見本', 名:'光', 姓カナ:'ミホン', 名カナ:'ヒカリ', 生年月日:'2021-07-01', 入園日:'2026-04-01', 在園状態:'在園', 性別:'未設定', 家庭住所:'見本市サンプル町2-2', '保護者①姓':'見本', '保護者①名':'秋', '保護者①続柄':'保護者'};
    return [a,b,c];
  };
  function date(value, epoch1904 = false) {
    if (typeof value === 'number') {
      if (!Number.isFinite(value) || value < 1 || value > 100000) return '';
      return new Date(Date.UTC(epoch1904 ? 1904 : 1899, epoch1904 ? 0 : 11, epoch1904 ? 1 : 30) + Math.floor(value)*86400000).toISOString().slice(0,10);
    }
    const m = String(value || '').trim().match(/^(\d{4})[\/.-](\d{1,2})[\/.-](\d{1,2})$/);
    if (!m) return '';
    const d = new Date(Date.UTC(+m[1], +m[2]-1, +m[3]));
    return d.getUTCFullYear() === +m[1] && d.getUTCMonth()+1 === +m[2] && d.getUTCDate() === +m[3] ? d.toISOString().slice(0,10) : '';
  }
  const createAssignment = (sequence = {child:0, family:0}) => ({sequence, children:new Map(), families:new Map()});
  function validate(input, assignment = createAssignment()) {
    const errors = [], warnings = [], families = new Map(), classes = new Map(), children = new Map(), identities = new Map(), exactRows = new Map();
    const number = (map, key, type, prefix) => {
      if (!map.has(key)) map.set(key, prefix + String(++assignment.sequence[type]).padStart(3,'0'));
      return map.get(key);
    };
    const issue = (list, row, column, message) => list.push({row, column, message});
    const rows = input.map((raw, index) => ({...blank(), ...raw, _line: raw._line || index+5})).filter(r => fields.some(f => String(r[f.key] ?? '').trim()));
    const familyFields = ['家庭住所','家庭電話番号', ...fields.filter(f => f.group.startsWith('保護者')).map(f => f.key)];
    for (const raw of rows) {
      const r = Object.fromEntries(fields.map(f => [f.key, String(raw[f.key] ?? '').trim()]));
      const line = raw._line;
      r._line = line;
      r['園児整理番号'] = number(assignment.children,line,'child','C');
      const familyGroup = r['きょうだいグループ'] ? 'group:'+r['きょうだいグループ'] : 'child:'+r['園児整理番号'];
      r['家庭整理番号'] = number(assignment.families,familyGroup,'family','F');
      for (const f of fields) {
        const value = r[f.key];
        if (f.required && !value) issue(errors,line,f.key,'必須項目が空欄です。');
        if (value && f.type === 'date') { const parsed = date(raw[f.key], raw._epoch1904); if (!parsed) issue(errors,line,f.key,'存在する日付を西暦で入力してください。'); else r[f.key] = parsed; }
        if (value && f.type === 'select' && !f.options.includes(value)) issue(errors,line,f.key,`${f.options.join('・')}から選択してください。`);
        if (value && f.type === 'integer' && !/^[1-9]\d*$/.test(value)) issue(errors,line,f.key,'1以上の整数を入力してください。');
        if (value && f.type === 'email' && !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(value)) issue(errors,line,f.key,'メールアドレスの形式を確認してください。');
        if (value && f.type === 'phone' && typeof raw[f.key] === 'number') issue(errors,line,f.key,'数値の電話番号です。先頭の0を原本で確認し、文字列として貼り直してください。');
      }
      for (const n of ['①','②']) {
        if (guardianFields.some(k => r[`保護者${n}${k}`]) && (!r[`保護者${n}姓`] || !r[`保護者${n}名`])) issue(errors,line,`保護者${n}姓・名`,'保護者情報がある場合は姓と名の両方が必要です。');
      }
      if (!!r['照合用氏名'] !== !!r['照合用氏名種別']) issue(errors,line,'照合用氏名','氏名と種別をセットで入力してください。');
      if (r['入園日'] && r['生年月日'] && date(r['入園日']) && date(r['生年月日']) && r['入園日'] < r['生年月日']) issue(errors,line,'入園日','生年月日より前になっています。');
      if (date(r['退園日']) && date(r['入園日']) && r['退園日'] < r['入園日']) issue(errors,line,'退園日','入園日より前になっています。');
      if (r['在園状態'] !== '在園' && r['在園状態'] && !r['退園日']) issue(warnings,line,'退園日','卒園・退園ですが日付が空欄です。');
      const exact = JSON.stringify(fields.map(f => r[f.key]));
      if (exactRows.has(exact)) issue(errors,line,'姓',`${exactRows.get(exact)}行目と入力内容がすべて同じです。重複した行を原本で確認してください。`);
      else exactRows.set(exact,line);
      children.set(r['園児整理番号'], r);
      if (r['家庭整理番号']) {
        if (!families.has(r['家庭整理番号'])) families.set(r['家庭整理番号'], {key:r['家庭整理番号'], group:r['きょうだいグループ'], data:{}, children:[]});
        const family = families.get(r['家庭整理番号']);
        family.children.push(r['園児整理番号']);
        for (const key of familyFields) if (r[key]) {
          if (family.data[key] && family.data[key] !== r[key]) issue(errors,line,key,'同じきょうだいグループの別の行と内容が異なります。別家庭ならグループを分けてください。');
          else family.data[key] = r[key];
        }
      }
      if (r['クラス名']) {
        const previous = classes.get(r['クラス名']);
        if (previous && previous.explicit && r['クラス表示順'] && previous.explicit !== r['クラス表示順']) issue(errors,line,'クラス表示順','同じクラスで表示順が異なります。');
        else classes.set(r['クラス名'], {name:r['クラス名'], explicit:r['クラス表示順'] || previous?.explicit || '', order: r['クラス表示順'] || previous?.order || String(classes.size+1)});
      } else if (r['クラス表示順']) issue(errors,line,'クラス名','表示順を指定する場合はクラス名も入力してください。');
      const identity = [r['姓カナ'],r['名カナ'],r['生年月日']].join('|');
      if (r['姓カナ'] && r['名カナ'] && r['生年月日']) {
        if (identities.has(identity)) issue(warnings,line,'氏名カナ・生年月日','同じ氏名カナ・生年月日があります。自動では同一人物にまとめません。原本で確認してください。');
        else identities.set(identity,line);
      }
    }
    const surnameCounts = new Map();
    for (const family of families.values()) {
      const first = children.get(family.children[0]);
      family.representative = first;
      surnameCounts.set(first['姓'], (surnameCounts.get(first['姓']) || 0)+1);
    }
    const names = new Set();
    for (const family of families.values()) {
      const first = family.representative;
      const base = !first['姓'] ? '氏名入力後に自動設定' : surnameCounts.get(first['姓']) > 1 ? [first['姓'],first['名']].filter(Boolean).join(' ') : first['姓'];
      let name = base;
      if (names.has(name)) name = `${base}（${family.key}）`;
      while (names.has(name)) name += '（別家庭）';
      names.add(name);family.data['家庭名'] = name;
      for (const id of family.children) {
        const child = children.get(id);child['家庭名'] = name;
        if (child['姓'] && first['姓'] && child['姓'] !== first['姓']) issue(warnings,child._line,'きょうだいグループ','同じ家庭に異なる姓があります。家庭名は先頭行の園児を基準にしています。');
      }
    }
    return {rows, errors, warnings, families:[...families.values()], classes:[...classes.values()], children:[...children.values()], canCommit:rows.length>0 && errors.length===0};
  }
  const api = {fields, groups, blank, sample, date, validate, createAssignment};
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  root.InitialImport = api;
})(typeof globalThis === 'undefined' ? window : globalThis);
