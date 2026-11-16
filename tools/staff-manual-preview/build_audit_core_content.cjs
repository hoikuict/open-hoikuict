const fs=require('fs'),vm=require('vm'),path=require('path');
const file=path.join(__dirname,'dist/app.js');let s=fs.readFileSync(file,'utf8').replace(/\r\n/g,'\n');
const a=vm.runInNewContext(s.slice(s.indexOf('const manualArticles'),s.indexOf('// BEGIN PARENT GUIDE'))+';manualArticles');
const saved={title:'保存後の一覧を確認する',text:'保存後に月間一覧を開き直し、対象日の降園時刻が入っていることを確認します。空欄を埋めた日は「詳細・修正」から日別の画面を開けます。',image:'monthly-saved',alt:'一括補完後の月間一覧の見本。降園16:30が入り、日別ボタンは詳細・修正。',calls:['保存した日付と降園時刻を確かめます。','「詳細・修正」を押して、この日の履歴を開きます。'],note:'未打刻の空欄が残っている日は「補記する」、記録がそろった編集可能な日は「詳細・修正」です。編集できない日は「詳細」になります。'};
const history={title:'日別の修正履歴を確かめる',text:'画面の「補記・修正・取消の履歴」で、変更前後の時刻・理由・修正者を確かめます。見るだけなら、保存ボタンを押す必要はありません。',image:'monthly-history',alt:'10月26日の修正履歴の例。降園なしから16:30へ補記した理由と修正者。',calls:['履歴の変更前後・理由・修正者を確かめます。'],note:'時刻を保存すると、まだ確定していない延長料金が再計算されます。料金の確認が必要な場合は担当者に伝えます。'};
a.clock.steps=a.clock.steps.slice(0,3).concat([saved,history]);
a.phone.steps[0].alt=a.phone.steps[0].alt.replace('11月2日','11月4日');
a.phone.steps[0].text='「出欠確認」で対象日とクラスを確認し、園児の「詳細」を開きます。画像は開いた後の見本です。①〜④の受付欄を使います。';
a.phone.steps[0].calls=[...a.phone.steps[1].calls];
for(const step of a.phone.steps){
 if(step.states){step.stateCalls=Object.fromEntries(step.states.map(([key])=>[key,step.calls||[]]));}
}
// Generic completion advice is not a numbered screenshot explanation.
for(const step of a.password.steps)if(!step.image&&!step.states)delete step.calls;
for(const key of ['phone','clock','password']){
 const start=s.indexOf('  '+key+':');
 const end=key==='phone'?s.indexOf('  clock:',start):key==='clock'?s.indexOf('  password:',start):s.indexOf('\n};\n// BEGIN PARENT GUIDE',start);
 if(start<0||end<start)throw new Error('Core article boundary missing: '+key);
 s=s.slice(0,start)+'  '+key+':'+JSON.stringify(a[key],null,2)+(key==='password'?'':',\n')+s.slice(end);
}
const old='「園児別・月間修正」で対象の月・園児を選び、該当日の「詳細・修正」へ進みます。';
const next='「園児別・月間修正」で対象の月・園児を選びます。記録がそろった日は「詳細・修正」、未打刻の空欄がある日は「補記する」から日別の画面を開きます。';
s=s.replace(old,next);
fs.writeFileSync(file,s);
console.log('Updated monthly saved/history views and core state explanations.');
