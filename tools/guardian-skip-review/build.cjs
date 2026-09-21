// Build a separate review mock. Never rewrite the working converter.
const fs = require('node:fs');
const path = require('node:path');
const { createHash } = require('node:crypto');
const { execFileSync } = require('node:child_process');
const root = path.resolve(__dirname, '../..');
// Keep the approved mock reproducible after the working converter is updated.
const baseline = '7a411e28bba20ccb8b566bc673dcd618c1a45d4c';
const source = execFileSync('git', ['show', baseline + ':tools/family-child-csv-converter.html'], { cwd: root, encoding: 'utf8' });
let html = source.replaceAll('\r\n', '\n');
function replaceOnce(before, after) {
  if (html.split(before).length !== 2) throw Error('Converter baseline changed; review the patch: ' + before);
  html = html.replace(before, after);
}
replaceOnce('<title>緊急連絡表 → 家庭・園児CSV</title>', '<title>確認用：保護者の姓名不足を無視する</title>');
replaceOnce("<script>\n'use strict';", "<script>\n'use strict';\n" + fs.readFileSync(path.join(__dirname, 'omission.js'), 'utf8') + '\n');
replaceOnce('...(g.guardians||Array(20).fill(\'\'))', '...reviewExportGuardians(g)');
replaceOnce('for(let slot=0;slot<2;slot++){\n    const v=(g.guardians||[])', 'for(let slot=0;slot<2;slot++){\n    if(reviewSkipGuardian(g,slot))continue;\n    const v=(g.guardians||[])');
html += '\n<script>\n' + fs.readFileSync(path.join(__dirname, 'mock.js'), 'utf8') + '\n</script>\n';
const destination = path.join(root, '.local-dev/guardian-skip-review');
fs.mkdirSync(destination, { recursive: true });
fs.writeFileSync(path.join(destination, 'index.html'), html);
console.log(JSON.stringify({ output: path.join(destination, 'index.html'), baselineSha256: createHash('sha256').update(source).digest('hex') }));
