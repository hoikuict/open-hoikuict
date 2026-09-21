// Review proposal only: omit all ten fields of an incomplete guardian slot.
var reviewSkipIncomplete = false;
function reviewMissingGuardian(g, slot) {
  const values = (g.guardians || []).slice(slot * 10, slot * 10 + 10);
  return Boolean((values.some(Boolean) || g.rawGuardians?.[slot]?.partial) && (!values[0] || !values[1]));
}
function reviewSkipGuardian(g, slot) {
  return reviewSkipIncomplete && reviewMissingGuardian(g, slot);
}
function reviewExportGuardians(g) {
  const values = Array.from({ length: 20 }, (_, i) => g.guardians?.[i] || '');
  for (let slot = 0; slot < 2; slot++) {
    if (reviewSkipGuardian(g, slot)) values.fill('', slot * 10, slot * 10 + 10);
  }
  return values;
}
