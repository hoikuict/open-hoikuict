/* The server validates every edit again and owns all IDs and registrations. */
(() => {
  'use strict';
  const $ = id => document.getElementById(id), dataNode = $('ledger-page-data');
  if (!dataNode) return;
  const {rows, children, fields, groups} = JSON.parse(dataNode.textContent);
  let selected = 0, dirty = false;
  const el = (tag, text, cls) => {const node=document.createElement(tag);if(text!=null)node.textContent=text;if(cls)node.className=cls;return node;};
  const closeConfirmation = () => {if($('ledger-confirmation'))$('ledger-confirmation').hidden=true;if($('ledger-agree'))$('ledger-agree').checked=false;if($('ledger-commit'))$('ledger-commit').disabled=true;};
  const changed = () => {dirty=true;$('ledger-dirty').hidden=false;closeConfirmation();if($('ledger-review'))$('ledger-review').disabled=true;};
  function options() {
    $('ledger-child-select').replaceChildren();
    rows.forEach((row,index)=>{const option=el('option',`${row._line}行目 / ${row['姓']||''} ${row['名']||''}`);option.value=index;$('ledger-child-select').append(option);});
    $('ledger-child-select').value=String(selected);$('ledger-child-select').disabled=!rows.length;$('ledger-remove-row').disabled=!rows.length;
  }
  function render() {
    selected=Math.min(selected,Math.max(0,rows.length-1));options();$('ledger-editor').replaceChildren();
    if(!rows.length){$('ledger-editor').append(el('p','Excelに入力するか、園児を1行追加してください。'));return;}
    const row=rows[selected], child=children.find(c=>c._line===row._line), automatic=el('div',null,'ledger-auto');
    automatic.append(el('h3','自動で設定する内容'));
    const values=el('div',null,'ledger-auto-values');
    for(const [label,value] of [['園児整理番号',child?`C-${String(child.id).padStart(5,'0')}`:'再確認後に自動設定'],['家庭整理番号',child?`F-${String(child.family_id).padStart(5,'0')}`:'再確認後に自動設定'],['家庭名',child?.family_name||'再確認後に自動設定']]){
      const box=el('div',label);box.append(el('strong',value));values.append(box);
    }
    automatic.append(values,el('p','確認時点の登録予定です。氏名やグループを編集したら、編集内容を再確認してください。','ledger-help'));$('ledger-editor').append(automatic);
    for(const group of groups){
      const section=el('div',null,'ledger-group'), grid=el('div',null,'ledger-fields');section.append(el('h3',group));
      fields.forEach((field,index)=>{
        if(field.group!==group)return;
        const label=el('label');label.htmlFor='ledger-field-'+index;const heading=el('span',field.key);if(field.required)heading.append(el('span','必須','ledger-required'));label.append(heading);
        const input=el(field.type==='select'?'select':'input');input.id='ledger-field-'+index;
        if(field.type==='select'){input.append(el('option',''));field.options.forEach(value=>input.append(el('option',value)));}else{input.type=field.type==='email'?'email':'text';input.maxLength=1000;if(field.type==='date')input.placeholder='2026/04/01';}
        input.value=String(row[field.key]??'');input.oninput=input.onchange=()=>{row[field.key]=input.value;changed();options();};
        label.append(input,el('small',field.help));grid.append(label);
      });section.append(grid);$('ledger-editor').append(section);
    }
  }
  $('ledger-child-select').onchange=()=>{selected=Number($('ledger-child-select').value);render();};
  $('ledger-add-row').onclick=()=>{if(rows.length>=1000)return;rows.push({...Object.fromEntries(fields.map(f=>[f.key,''])),_line:Math.max(4,...rows.map(r=>r._line))+1});selected=rows.length-1;changed();render();};
  $('ledger-remove-row').onclick=()=>{rows.splice(selected,1);changed();render();};
  $('ledger-edit-form').onsubmit=()=>{$('ledger-rows-json').value=JSON.stringify(rows);};
  document.querySelectorAll('.ledger-issue').forEach(button=>button.onclick=()=>{
    const index=rows.findIndex(r=>r._line===Number(button.dataset.line));if(index<0)return;selected=index;render();
    const field=fields.findIndex(f=>f.key===button.dataset.column), target=$('ledger-field-'+field)||$('ledger-editor');target.scrollIntoView({block:'center',behavior:'smooth'});target.focus();
  });
  if($('ledger-review'))$('ledger-review').onclick=()=>{if(dirty)return;$('ledger-confirmation').hidden=false;$('ledger-confirmation').scrollIntoView({block:'start',behavior:'smooth'});};
  if($('ledger-agree'))$('ledger-agree').onchange=()=>{$('ledger-commit').disabled=dirty||!$('ledger-agree').checked;};
  if($('ledger-back'))$('ledger-back').onclick=()=>{closeConfirmation();$('ledger-editor').scrollIntoView({block:'start',behavior:'smooth'});};
  if($('ledger-commit-form'))$('ledger-commit-form').onsubmit=event=>{if(dirty){event.preventDefault();return;}$('ledger-commit').disabled=true;};
  render();
})();
