export const TODAY = '2026-09-24';
export const STAFF = '見本 はなこ';
export const CLASSES = ['きいちご', 'どんぐり', 'くるみ', 'うめ', 'たけ', 'まつ'];
export const CLASS_SIZES = [7, 15, 20, 20, 17, 21];
export const STATUS = { in: '在園', out: '降園', absent: 'お休み', pending: '未登園' };
export const VERIFY = { present: '出席', private_absent: '私用休み', sick_absent: '病欠', unknown: '不明' };
export const FIELDS = { nap_time: 'お昼寝時間', temperature: '体温', bowel_movement: '排便', appetite: '食欲', message: '連絡メモ' };
export function makeChildren() {
  const surnames = ['青葉', '花野', '森川', '星丘', '若葉', '虹原', '月島', '春野', '風間', '朝日'];
  const names = ['はる', 'ゆい', 'そう', 'りん', 'あお', 'ひな', 'れん', 'こと', 'みお', 'ゆう'];
  let id = 0;
  return CLASSES.flatMap((classroom, c) => Array.from({ length: CLASS_SIZES[c] }, (_, i) => {
    const n = id++;
    const status = i < 2 ? 'in' : i === 2 ? 'out' : i === 3 ? 'absent' : i === 4 ? 'pending' : i % 9 === 0 ? 'absent' : i % 7 === 0 ? 'out' : 'in';
    return { id: n + 1, name: `${surnames[Math.floor(n / 10)]} ${names[n % 10]}`, classroom,
      status, checkIn: ['in', 'out'].includes(status) ? `08:${String(15 + i % 4 * 10).padStart(2, '0')}` : '',
      checkOut: status === 'out' ? '14:10' : '', verification: n === 0 ? 'private_absent' : status === 'absent' ? 'sick_absent' : status === 'pending' ? 'unknown' : 'present',
      parentType: status === 'absent' ? '病欠' : status === 'pending' ? '' : '出席',
      confirmed: null, logs: [] };
  }));
}
export function alarms(child) {
  const reasons = [];
  if (child.checkIn && ['private_absent', 'sick_absent'].includes(child.verification)) reasons.push('登園打刻あり・目視は欠席');
  if (!child.parentType && (!child.confirmed || child.confirmed.status !== child.verification) && child.verification !== 'present') reasons.push('保護者連絡なし');
  if (child.verification === 'present' && !child.checkIn) reasons.push('出席確認済み・登園打刻なし');
  return reasons;
}
export function category(child) {
  if (child.checkOut) return 'out';
  if (child.checkIn || child.verification === 'present') return 'in';
  if (['private_absent', 'sick_absent'].includes(child.verification)) return 'absent';
  return 'pending';
}
export function counts(children) {
  const result = { in: 0, out: 0, absent: 0, pending: 0, enrolled: children.length, alarm: 0 };
  children.forEach(c => { result[category(c)]++; if (alarms(c).length) result.alarm++; });
  result.arrived = result.in + result.out;
  return result;
}
export function blankReply() { return Object.fromEntries(Object.keys(FIELDS).map(key => [key, ''])); }
export function replyPreset(scenario) {
  if (scenario === 'empty') return blankReply();
  if (scenario === 'partial') return { ...blankReply(), nap_time: '12:30-14:00', temperature: '36.5' };
  return { nap_time: '12:30-14:00', temperature: '36.5', bowel_movement: 'あり', appetite: '完食', message: '園庭で落ち葉を集め、友だちと色の違いを楽しみました。' };
}
export function shiftDate(date, offset) {
  const d = new Date(`${date}T12:00:00Z`); d.setUTCDate(d.getUTCDate() + offset); return d.toISOString().slice(0, 10);
}
export function minutes(time) {
  if (!/^\d{2}:\d{2}$/.test(time)) return NaN;
  const [h, m] = time.split(':').map(Number); return h < 24 && m < 60 ? h * 60 + m : NaN;
}
export function allowedTime(time, close) { return Number.isFinite(minutes(time)) && minutes(time) < minutes(close); }
export function availableMinutes(hour, close) { return Array.from({ length: 60 }, (_, m) => String(m).padStart(2, '0')).filter(m => allowedTime(`${hour}:${m}`, close)); }
export function pickupErrors(pickup, close) {
  const errors = [];
  if (!pickup.hour || !pickup.minute) errors.push('降園予定時刻の時と分を両方選んでください。');
  else if (!allowedTime(`${pickup.hour}:${pickup.minute}`, close)) errors.push(`閉園時刻 ${close} 以降は選択できません。時刻を選び直してください。`);
  if (!pickup.person) errors.push('お迎え予定の人を選んでください。');
  if (!pickup.snack) errors.push('補食の必要・不要を選んでください。');
  return errors;
}
