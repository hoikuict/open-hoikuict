/* Fictional preview only. No persistence or external I/O. */
(function (root) {
  'use strict';
  const minute = value => /^([01]\d|2[0-3]):[0-5]\d$/.test(value || '') ? Number(value.slice(0, 2)) * 60 + Number(value.slice(3)) : NaN;
  const clock = value => String(Math.floor(value / 60)).padStart(2, '0') + ':' + String(value % 60).padStart(2, '0');
  const integer = (value, min, max = Infinity) => String(value).trim() !== '' && Number.isInteger(Number(value)) && Number(value) >= min && Number(value) <= max;
  const dateOK = value => /^\d{4}-\d{2}-\d{2}$/.test(value || '') && !Number.isNaN(Date.parse(value + 'T00:00:00Z')) && new Date(value + 'T00:00:00Z').toISOString().slice(0, 10) === value;
  const title = side => side === 'morning' ? '前延長' : 'あと延長';
  function validate(plan) {
    const errors = [];
    const add = (message, field, side, id) => errors.push({ message, field, side, id });
    if (!plan.name.trim()) add('ルール名を入力してください。', 'name');
    if (!dateOK(plan.from)) add('適用開始日を入力してください。', 'from');
    if (plan.to && (!dateOK(plan.to) || plan.to < plan.from)) add('適用終了日は開始日以降にしてください。', 'to');
    const start = minute(plan.normalStart), end = minute(plan.normalEnd);
    if (!Number.isFinite(start)) add('通常保育の開始時刻を入力してください。', 'normalStart');
    if (!Number.isFinite(end)) add('通常保育の終了時刻を入力してください。', 'normalEnd');
    if (start >= end) add('通常保育の終了は開始より後にしてください。', 'normalEnd');
    if (plan.cap !== '' && !integer(plan.cap, 0)) add('日別上限額は0円以上の整数にしてください。', 'cap');
    for (const side of ['morning', 'evening']) {
      if (typeof plan[side + 'Enabled'] !== 'boolean') { add(title(side) + 'を使用するか選択してください。', side + 'Enabled'); continue; }
      if (!plan[side + 'Enabled']) continue;
      if (!integer(plan[side + 'Grace'], 0, 120)) add(title(side) + 'の猶予は0〜120分の整数にしてください。', side + 'Grace');
      const rows = plan[side + 'Bands'];
      if (!rows.length) { add(title(side) + 'の時間帯を1つ以上追加してください。', side + 'Enabled'); continue; }
      let validTimes = true;
      rows.forEach((band, index) => {
        const label = title(side) + (index + 1), a = minute(band.start), b = minute(band.end);
        if (!Number.isFinite(a)) { add(label + 'の開始時刻を入力してください。', 'start', side, band.id); validTimes = false; }
        if (!Number.isFinite(b) || a >= b) { add(label + 'の終了は開始より後にしてください。', 'end', side, band.id); validTimes = false; }
        if (side === 'morning' && b > start) add(label + 'は通常保育の開始までにしてください。', 'end', side, band.id);
        if (side === 'evening' && a < end) add(label + 'は通常保育の終了以降にしてください。', 'start', side, band.id);
        if (!['unit', 'flat'].includes(band.mode)) add(label + 'の料金方式を選択してください。', 'mode', side, band.id);
        if (band.mode === 'unit' && !integer(band.unit, 1, 120)) add(label + 'の課金単位は1〜120分の整数にしてください。', 'unit', side, band.id);
        if (!integer(band.price, 0)) add(label + 'の料金は0円以上の整数で入力してください。', 'price', side, band.id);
      });
      if (validTimes) {
        const ordered = [...rows].sort((a, b) => minute(a.start) - minute(b.start));
        ordered.forEach((band, index) => {
          if (!index) return;
          const previous = ordered[index - 1];
          if (minute(band.start) < minute(previous.end)) add(title(side) + 'の時間帯が重複しています。', 'start', side, band.id);
          if (minute(band.start) > minute(previous.end)) add(title(side) + 'の時間帯に空白があります。無料の時間は0円の時間帯として入力してください。', 'start', side, band.id);
        });
        if (side === 'morning' && Number.isFinite(start) && minute(ordered.at(-1).end) !== start) add('前延長の最後の終了時刻を、通常保育の開始に合わせてください。', 'end', side, ordered.at(-1).id);
        if (side === 'evening' && Number.isFinite(end) && minute(ordered[0].start) !== end) add('あと延長の最初の開始時刻を、通常保育の終了に合わせてください。', 'start', side, ordered[0].id);
      }
    }
    return errors;
  }
  function calculate(plan, day, arrival, departure) {
    const errors = validate(plan).map(item => item.message), warnings = [], lines = [];
    if (!dateOK(day)) errors.push('利用日を入力してください。');
    else if (day < plan.from || (plan.to && day > plan.to)) errors.push('利用日がこのルールの適用期間外です。');
    if (!plan.active) errors.push('このルールは無効です。有効な期間のルールを確認してください。');
    const a = minute(arrival), b = minute(departure);
    if (!Number.isFinite(a) || !Number.isFinite(b)) errors.push('登園・降園時刻を入力してください。');
    else if (a >= b) errors.push('同じ日の登園より後の降園時刻で試してください。日付をまたぐ利用は仮仕様の対象外です。');
    if (errors.length) return { errors: [...new Set(errors)], warnings, lines, total: null, subtotal: 0 };
    const nStart = minute(plan.normalStart), nEnd = minute(plan.normalEnd);
    for (const side of ['morning', 'evening']) {
      const grace = plan[side + 'Enabled'] ? Number(plan[side + 'Grace']) : 0;
      const begin = side === 'morning' ? a : Math.max(a, nEnd + grace);
      const finish = side === 'morning' ? Math.min(b, nStart - grace) : b;
      const duration = Math.max(0, finish - begin);
      if (!duration) continue;
      if (!plan[side + 'Enabled']) { warnings.push(title(side) + 'を使用しない設定ですが、通常保育の外に' + duration + '分の利用があります。'); continue; }
      let covered = 0;
      const bands = [...plan[side + 'Bands']].sort((x, y) => minute(x.start) - minute(y.start));
      bands.forEach((band, index) => {
        const left = Math.max(begin, minute(band.start)), right = Math.min(finish, minute(band.end));
        const used = Math.max(0, right - left);
        if (!used) return;
        covered += used;
        const units = band.mode === 'flat' ? 1 : Math.ceil(used / Number(band.unit));
        lines.push({ label: title(side) + (index + 1), range: band.start + '〜' + band.end,
          usedRange: clock(left) + '〜' + clock(right), used, units,
          method: band.mode === 'flat' ? '時間帯ごと定額' : band.unit + '分ごと（切り上げ）',
          price: Number(band.price), amount: units * Number(band.price) });
      });
      if (covered < duration) warnings.push(title(side) + 'の設定時間帯の外に' + (duration - covered) + '分の利用があります。扱いを確認してください。');
    }
    const subtotal = lines.reduce((sum, line) => sum + line.amount, 0);
    const cap = plan.cap === '' ? null : Number(plan.cap);
    const total = warnings.length ? null : cap === null ? subtotal : Math.min(subtotal, cap);
    return { errors, warnings, lines, subtotal, total, cap, capped: total !== null && total < subtotal };
  }
  const api = { minute, clock, integer, dateOK, validate, calculate };
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  else root.FeePreviewCalculator = api;
})(typeof window === 'undefined' ? globalThis : window);
