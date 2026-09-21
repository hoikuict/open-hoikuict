const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const root = path.resolve(__dirname, '../..');
const html = fs.readFileSync(path.join(root, '.local-dev/guardian-skip-review/index.html'), 'utf8');
for (const [, script] of html.matchAll(/<script>([\s\S]*?)<\/script>/g)) new vm.Script(script);
const ctx = vm.createContext({});
vm.runInContext(fs.readFileSync(path.join(__dirname, 'omission.js'), 'utf8'), ctx);
// Run the actual mock's family validation and CSV functions without a browser or DB.
const validator = html.slice(html.indexOf('familyProblems=function(g){'), html.indexOf('const renderFamilies=render;'));
vm.runInContext(`
  var templateVerified=true, knownFamilies=[];
  const norm=v=>String(v??'').normalize('NFKC').trim();
  const basicFamilyProblems=g=>g.conflict?[g.conflict]:[];
  const GF=['姓','名','姓カナ','名カナ','続柄','メールアドレス','電話番号','勤務先','勤務先住所','勤務先電話番号'];
  const FH=['ID','家庭名','住所','電話番号',...['①','②'].flatMap(n=>GF.map(h=>'保護者'+n+h))];
  var groups=[];
  function selectedGroups(){return groups;}
  ${validator}
  ${html.slice(html.indexOf('function csvMatrix('), html.indexOf('function saveText('))}
`, ctx);
vm.runInContext(`
  var g={id:'41',name:'架空家庭',address:'架空住所',phone:'',guardians:[
    '', '', '', '', '保護者','first@example.test','000-0000-0000','架空会社','架空勤務先住所','',
    '見本','太一','ミホン','タイチ','保護者','second@example.test','000-0000-0001','会社②','',''
  ],rawGuardians:[{partial:true,full:'見本保護者',reading:'ミホンホゴシャ'}, {partial:true,full:'見本 太一',reading:'ミホン タイチ'}],review:[]};
  groups=[g];
`, ctx);
const run = code => vm.runInContext(code, ctx);
assert.match(run('familyProblems(g).join()'), /保護者①の姓・名/);
const original = run('JSON.stringify(g.guardians)');
run('reviewSkipIncomplete=true');
assert.equal(run('familyProblems(g).length'), 0);
assert.equal(run('reviewExportGuardians(g).slice(0,10).every(x=>x===\'\')'), true);
assert.equal(run('JSON.stringify(reviewExportGuardians(g).slice(10))'), run('JSON.stringify(g.guardians.slice(10))'));
assert.equal(run('JSON.stringify(g.guardians)'), original);
assert.equal(run('familyCSV().includes("first@example.test")'), false);
assert.equal(run('familyCSV().includes("second@example.test")'), true);
assert.equal(run('familyCSV().includes("架空家庭")'), true);
run('reviewSkipIncomplete=false');
assert.match(run('familyProblems(g).join()'), /保護者①の姓・名/);
assert.equal(run('JSON.stringify(reviewExportGuardians(g))'), original);
run('reviewSkipIncomplete=true;g.guardians[0]="見本";g.guardians[1]="保護者";g.guardians[2]="ミホン";g.guardians[3]="ホゴシャ"');
assert.equal(run('reviewSkipGuardian(g,0)'), false);
assert.equal(run('reviewExportGuardians(g)[5]'), 'first@example.test');
run('g.guardians[1]="";g.guardians[15]="invalid-mail"');
assert.match(run('familyProblems(g).join()'), /保護者②のメールアドレス/);
run('templateVerified=false');
assert.match(run('familyProblems(g).join()'), /24列/);
run('g.conflict="家庭の重複";g.review=["自宅電話の原本確認"]');
assert.match(run('familyProblems(g).join()'), /家庭の重複/);
assert.match(run('familyProblems(g).join()'), /原本/);
run('g.guardians=Array(20).fill(\'\');g.rawGuardians=[{partial:false},{partial:false}]');
assert.equal(run('reviewMissingGuardian(g,0)'), false);
run('g.rawGuardians[1]={partial:true,full:"未分割"}');
assert.equal(run('reviewSkipGuardian(g,1)'), true);
assert.equal(run('reviewExportGuardians(g).length'), 20);
console.log('Review checks passed: slot omission, reversal, source preservation, other guardian, CSV output, template/conflict/review validation, both slots, script syntax.');
