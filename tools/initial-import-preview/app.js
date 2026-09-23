'use strict';
const model=InitialImport, $=id=>document.getElementById(id);
let rows=[], selected=0, workbook=null, plan=model.validate([]), revision=0, confirmedRevision=-1;
const sequence={child:0,family:0}, assignments=new Map();
let assignment=model.createAssignment(sequence);
const simulatedChildren=new Map(), simulatedFamilies=new Map(), simulatedClasses=new Map();
const el=(tag,text,cls)=>{const node=document.createElement(tag);if(text!=null)node.textContent=text;if(cls)node.className=cls;return node;};
function invalidate(){revision++;confirmedRevision=-1;$('confirmation').hidden=true;$('agree').checked=false;$('commit').disabled=true;$('result').hidden=true;}
function refresh(){
  plan=model.validate(rows,assignment);$('counts').replaceChildren();
  for(const [label,value,cls]of[['園児',plan.rows.length,''],['家庭',plan.families.length,''],['クラス',plan.classes.length,''],['エラー',plan.errors.length,'error'],['確認',plan.warnings.length,'']]){const box=el('div',label,'stat '+cls);box.append(el('strong',value));$('counts').append(box);}
  $('issues').replaceChildren();
  for(const [title,list,cls]of[['修正が必要です',plan.errors,'issues'],['原本で確認してください',plan.warnings,'issues warning']])if(list.length){const box=el('div',null,cls);box.append(el('strong',title));const ul=el('ul');for(const issue of list){const li=el('li');const button=el('button',`${issue.row}行目 / ${issue.column}：${issue.message}`);button.onclick=()=>{const index=rows.findIndex((r,i)=>(r._line||i+5)===issue.row);if(index>=0){selected=index;renderEditor();const field=model.fields.findIndex(f=>f.key===issue.column);const target=document.getElementById('field-'+field);(target||$('editor')).scrollIntoView({behavior:'smooth',block:'center'});target?.focus();}};li.append(button);ul.append(li);}box.append(ul);$('issues').append(box);}
  $('families').replaceChildren();
  for(const family of plan.families){const tr=el('tr');const names=plan.children.filter(c=>c['家庭整理番号']===family.key).map(c=>`${c['姓']} ${c['名']} (${c['園児整理番号']})`).join('、');for(const text of[family.key,family.data['家庭名'],names,[family.data['保護者①姓'],family.data['保護者①名']].filter(Boolean).join(' ')||'未入力',[family.data['保護者②姓'],family.data['保護者②名']].filter(Boolean).join(' ')||'未入力'])tr.append(el('td',text));$('families').append(tr);}
  if(!plan.families.length){const tr=el('tr'),td=el('td','まだ家庭データがありません。');td.colSpan=5;tr.append(td);$('families').append(tr);}
  const child=plan.children.find(c=>c._line===(rows[selected]?._line||selected+5));
  for(const [index,key]of ['園児整理番号','家庭整理番号','家庭名'].entries())if($('auto-'+index))$('auto-'+index).textContent=child?.[key]||'入力後に自動設定';
  if(rows[selected]&&$('child-select').options[selected])$('child-select').options[selected].textContent=`${rows[selected]._line||selected+5}行目 / ${rows[selected]['姓']||''} ${rows[selected]['名']||''} / ${child?.['園児整理番号']||'自動採番'}`;
  $('review').disabled=!plan.canCommit;
}
function renderEditor(){
  $('child-select').replaceChildren();rows.forEach((r,i)=>{const child=plan.children.find(c=>c._line===(r._line||i+5));const option=el('option',`${r._line||i+5}行目 / ${r['姓']||''} ${r['名']||''} / ${child?.['園児整理番号']||'自動採番'}`);option.value=i;$('child-select').append(option);});
  $('child-select').disabled=!rows.length;$('editor').replaceChildren();if(!rows.length){$('editor').append(el('p','Excelを選ぶか、架空データの状態を選んでください。','empty'));return;}
  selected=Math.min(selected,rows.length-1);$('child-select').value=String(selected);const row=rows[selected];
  const generated=el('div',null,'generated');generated.append(el('h3','自動で設定する内容'));
  const values=el('div',null,'generated-values'), child=plan.children.find(c=>c._line===(row._line||selected+5));
  for(const [index,key]of ['園児整理番号','家庭整理番号','家庭名'].entries()){const item=el('div');item.append(el('span',key));const value=el('strong',child?.[key]||'入力後に自動設定');value.id='auto-'+index;item.append(value);values.append(item);}
  generated.append(values,el('p','番号は入力不要です。家庭名は先頭行の園児の姓。同姓の別家庭がある場合は姓名、姓名も重なる場合は番号を添えます。','muted'));$('editor').append(generated);
  for(const group of model.groups){const section=el('div',null,'field-group');section.append(el('h3',group));const grid=el('div',null,'field-grid');
    model.fields.forEach((field,index)=>{if(field.group!==group)return;const label=el('label');label.htmlFor='field-'+index;const name=el('span',field.key);if(field.required)name.append(el('span','必須','required'));label.append(name);let input;
      if(field.type==='select'){input=el('select');input.append(el('option',''));field.options.forEach(value=>input.append(el('option',value)));}else{input=el('input');input.type=field.type==='date'?'date':field.type==='email'?'email':'text';}
      input.id='field-'+index;input.value=field.type==='date'?model.date(row[field.key],row._epoch1904):String(row[field.key]??'');
      input.oninput=input.onchange=()=>{row[field.key]=input.value;invalidate();refresh();};label.append(input,el('small',field.help));grid.append(label);
    });section.append(grid);$('editor').append(section);
  }
}
function setRows(next){
  const signature=JSON.stringify(next.map(r=>model.fields.map(f=>f.type==='date'&&r[f.key]?model.date(r[f.key],r._epoch1904):String(r[f.key]??'').trim())));
  if(!assignments.has(signature))assignments.set(signature,model.createAssignment(sequence));
  assignment=assignments.get(signature);rows=next;selected=0;invalidate();refresh();renderEditor();
}
for(const button of document.querySelectorAll('[data-scenario]'))button.onclick=()=>{
  workbook=null;$('file').value='';$('sheet').replaceChildren(el('option','架空データ'));$('sheet').disabled=true;
  const type=button.dataset.scenario;let data=type==='empty'?[]:model.sample();
  if(type==='partial'){data[0]['生年月日']='';data[2]['保護者①名']='';}
  if(type==='error'){data[1]['家庭電話番号']='000-0000-9999';data[2]['保護者①メールアドレス']='メール未確認';}
  $('file-status').textContent='架空データの試用です。実際の台帳は変更しません。';setRows(data);
};
$('add-row').onclick=()=>{rows.push({...model.blank(),_line:Math.max(4,...rows.map((r,i)=>r._line||i+5))+1});selected=rows.length-1;invalidate();refresh();renderEditor();};
$('child-select').onchange=()=>{selected=Number($('child-select').value);renderEditor();};
async function loadSelectedSheet(){try{setRows(await workbook.read($('sheet').value));$('file-status').textContent=`「${$('sheet').value}」をブラウザー内で読み込みました。`;}catch(error){setRows([]);$('file-status').textContent=error.message;}}
$('file').onchange=async()=>{workbook=null;setRows([]);$('sheet').disabled=true;try{const file=$('file').files[0];if(!file)return;workbook=await readInitialWorkbook(file);const sheets=workbook.sheets.filter(s=>['入力用','記入例'].includes(s.name));if(!sheets.length)throw Error('このテンプレートの「入力用」シートがありません。');$('sheet').replaceChildren();sheets.forEach(s=>$('sheet').append(el('option',s.name)));$('sheet').disabled=false;$('sheet').value=sheets.some(s=>s.name==='入力用')?'入力用':sheets[0].name;await loadSelectedSheet();}catch(error){$('file-status').textContent=error.message;}};
$('sheet').onchange=loadSelectedSheet;
$('review').onclick=()=>{refresh();if(!plan.canCommit)return;confirmedRevision=revision;$('confirmation-text').textContent=`クラス ${plan.classes.length}件、家庭 ${plan.families.length}件、園児 ${plan.children.length}人をまとめて登録する案です。エラーがあれば全体を保存せず、修正後に再確認します。`;$('confirmation').hidden=false;$('confirmation').scrollIntoView({behavior:'smooth',block:'start'});};
$('agree').onchange=()=>{$('commit').disabled=!$('agree').checked||revision!==confirmedRevision;};
$('back').onclick=()=>{invalidate();$('editor').scrollIntoView({behavior:'smooth',block:'start'});};
$('commit').onclick=()=>{
  plan=model.validate(rows,assignment);if(!plan.canCommit||!$('agree').checked||revision!==confirmedRevision)return;
  let created=0,changed=0,same=0;for(const child of plan.children){const key=child['園児整理番号'],value=JSON.stringify(child);if(!simulatedChildren.has(key))created++;else if(simulatedChildren.get(key)!==value)changed++;else same++;simulatedChildren.set(key,value);}
  const currentFamilies=new Set(plan.families.map(f=>f.key));for(const key of assignment.families.values())if(!currentFamilies.has(key))simulatedFamilies.delete(key);
  plan.families.forEach(f=>simulatedFamilies.set(f.key,JSON.stringify(f.data)));plan.classes.forEach(c=>simulatedClasses.set(c.name,JSON.stringify(c)));
  $('confirmation').hidden=true;confirmedRevision=-1;$('agree').checked=false;$('commit').disabled=true;
  $('result').textContent=`モックの登録を試しました。園児：新規 ${created}人、変更 ${changed}人、変更なし ${same}人。モック内の合計は園児 ${simulatedChildren.size}人・家庭 ${simulatedFamilies.size}件です。実データの保存・アカウント作成・メール送信はしていません。`;$('result').hidden=false;$('result').scrollIntoView({behavior:'smooth',block:'center'});
};
$('cancel').onclick=()=>{workbook=null;$('file').value='';$('sheet').disabled=true;$('sheet').replaceChildren(el('option','ファイル選択後に表示'));$('file-status').textContent='今回の読み込みを取り消しました。元のExcelは変更されません。';setRows([]);};
setRows([]);
