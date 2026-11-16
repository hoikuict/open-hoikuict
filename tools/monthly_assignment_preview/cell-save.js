  // Inserted only into the isolated mock's copy of the existing editor script.
  const wireCell = cell => ({body:cell?.body || '',origins:(cell?.origins || []).map(o=>o.kind==='ai'
    ? {kind:'ai',token:o.token} : {source_key:o.source_key,phrase_id:o.phrase_id})});
  const sameCell = (a,b) => JSON.stringify(wireCell(a)) === JSON.stringify(wireCell(b));
  const valueFor = (context,key) => key==='@owner' ? context.owner_name : context.sheet.fields[key] || {body:'',origins:[]};
  const bodyFor = (context,key) => key==='@owner' ? context.owner_name : context.sheet.fields[key]?.body || '';
  function putValue(context,key,value) {
    if(key==='@owner') context.owner_name=value;
    else if(value?.body || value?.origins?.length) context.sheet.fields[key]=clone(value);
    else delete context.sheet.fields[key];
  }
  function keepLocalChanges(latest,base,working) {
    const result=clone(latest);
    for(const key of new Set([...Object.keys(base.sheet.fields),...Object.keys(working.sheet.fields)])) {
      if(!sameCell(base.sheet.fields[key],working.sheet.fields[key]))putValue(result,key,valueFor(working,key));
    }
    if(working.owner_name!==base.owner_name)result.owner_name=working.owner_name;
    return result;
  }
  function adoptMerged(item,latest,relativeTo,choices={}) {
    const active=document.activeElement, focusedKey=active?.dataset.cell, ownerFocus=active?.hasAttribute('data-owner');
    const selection=focusedKey || ownerFocus ? [active.selectionStart,active.selectionEnd] : null;
    const result=keepLocalChanges(latest,relativeTo,item.context);
    for(const [key,value] of Object.entries(choices))putValue(result,key,value);
    const importedChanges=latest.owner_name!==relativeTo.owner_name ||
      [...new Set([...Object.keys(latest.sheet.fields),...Object.keys(relativeTo.sheet.fields)])].some(key=>!sameCell(latest.sheet.fields[key],relativeTo.sheet.fields[key]));
    item.saved=clone(latest);item.context=result;if(importedChanges)item.undo=[];before=null;
    if(item===current) {
      paper();panel(false);status();
      const target=ownerFocus ? q('[data-owner]') : all('[data-cell]').find(el=>el.dataset.cell===focusedKey);
      if(target && selection){target.focus({preventScroll:true});target.setSelectionRange(...selection);}
    }
  }
  async function mergeRequest(path,payload) {
    const token=document.querySelector('meta[name="csrf-token"]').content;
    const response=await fetch('/preview/'+path,{method:'POST',credentials:'same-origin',
      headers:{'Content-Type':'application/json','X-CSRF-Token':token},body:JSON.stringify(payload)});
    let data;
    try {data=await response.json();} catch {throw new Error('応答を読み込めません。入力内容は保持しています。');}
    if(!response.ok){const error=new Error(typeof data.detail==='string' ? data.detail : data.detail?.kind==='cell_conflict' ? '同じ欄の変更を確認してください。' : '入力内容を確認してください。保存は完了していません。');error.detail=data.detail;throw error;}
    return data;
  }
  function showCellConflicts(item,detail) {
    document.querySelector('#cell-conflict-dialog')?.remove();
    const dialog=document.createElement('dialog');dialog.id='cell-conflict-dialog';dialog.setAttribute('aria-labelledby','conflict-heading');
    dialog.innerHTML='<h2 id="conflict-heading">同じ欄の変更を確認</h2><p>同じ欄をほかの担当者が先に保存しました。今回は保存していません。ほかの欄の入力も残っています。</p><div id="conflict-fields"></div><div class="conflict-actions"><button type="button" data-conflict-cancel>入力に戻る</button><button type="button" data-conflict-save disabled>選んだ内容で保存する</button></div>';
    const choices={}, accept=dialog.querySelector('[data-conflict-save]');
    for(const entry of detail.conflicts) {
      const row=document.createElement('section');row.className='conflict-field';
      row.innerHTML='<h3></h3><div class="conflict-columns"><div><strong>保存済みの内容</strong><pre></pre><button type="button" data-choice="theirs" aria-pressed="false">保存済みの内容を使う</button></div><div><strong>自分の入力（修正もできます）</strong><textarea rows="4"></textarea><button type="button" data-choice="mine" aria-pressed="false">自分の入力を使う</button></div></div>';
      row.querySelector('h3').textContent=entry.label;
      row.querySelector('pre').textContent=bodyFor(detail.latest,entry.key) || '（空欄）';
      const input=row.querySelector('textarea');input.value=bodyFor(item.context,entry.key);input.setAttribute('aria-label',entry.label+' / 保存する入力');
      const choose=side=>{
        if(side==='theirs')choices[entry.key]=clone(valueFor(detail.latest,entry.key));
        else choices[entry.key]=entry.key==='@owner' ? input.value : {...clone(valueFor(item.context,entry.key)),body:input.value,origins:input.value ? valueFor(item.context,entry.key).origins || [] : []};
        row.querySelectorAll('[data-choice]').forEach(button=>button.setAttribute('aria-pressed',String(button.dataset.choice===side)));
        accept.disabled=Object.keys(choices).length!==detail.conflicts.length;
      };
      row.querySelectorAll('[data-choice]').forEach(button=>button.onclick=()=>choose(button.dataset.choice));
      input.addEventListener('input',()=>choose('mine'));
      dialog.querySelector('#conflict-fields').append(row);
    }
    dialog.querySelector('[data-conflict-cancel]').onclick=()=>dialog.close();
    accept.onclick=async()=>{
      // Rebase only after an explicit choice. A newer same-cell write is checked again.
      adoptMerged(item,detail.latest,item.saved,choices);dialog.close();await save();
    };
    document.body.append(dialog);dialog.showModal();
  }
  async function save() {
    if(saving || !editable())return;
    commitEdit();
    const item=current,snapshot=clone(ctx());
    const payload={document_id:item.saved.document_id,lock_version:item.saved.lock_version,
      base_token:item.saved.preview_base_token,classroom_id:snapshot.classroom_id,
      target_month:snapshot.target_month,age:snapshot.age,owner_name:snapshot.owner_name,
      fields:Object.fromEntries(Object.entries(snapshot.sheet.fields).map(([key,value])=>[key,wireCell(value)]))};
    saving=true;status();
    try {
      const data=await mergeRequest('cell-save',payload);
      adoptMerged(item,data,snapshot);
      const remote=data.merged_remote_fields || [];
      announce((remote.length ? `保存しました。ほかの担当者の${remote.length}欄の変更も取り込みました。` : '下書きを保存しました。')+
        (dirty(item) ? ' 保存中に入力した変更はまだ未保存です。' : ''));
    } catch(error) {
      announce(error.message+' この画面の入力は残っています。',true);
      if(error.detail?.kind==='cell_conflict')showCellConflicts(item,error.detail);
    } finally {saving=false;status();}
  }
  let exampleNumber=0,exampleField=null;
  root.addEventListener('focusin',event=>{
    if(event.target.dataset.cell)exampleField=event.target.dataset.cell;
    else if(event.target.hasAttribute('data-owner'))exampleField='@owner';
  });
  document.querySelectorAll('[data-merge-example]').forEach(button=>button.onclick=async()=>{
    if(saving || !editable()){announce('担当者の編集できる月案で試してください。',true);return;}
    commitEdit();
    const key=exampleField==='@owner' || ctx().definitions[exampleField] ? exampleField : current.field;
    const other=button.dataset.mergeExample==='same' ? key : key==='common:home' ? 'common:goal' : 'common:home';
    const currentValue=valueFor(ctx(),key), count=++exampleNumber;
    remember();
    putValue(ctx(),key,key==='@owner' ? `自分の担任名（例${count}）` : {...currentValue,body:bodyFor(ctx(),key)+`\n【自分の入力例${count}】一人ひとりのペースを大切にする。`});
    paper();panel(false);status();
    document.querySelectorAll('[data-merge-example]').forEach(el=>el.disabled=true);
    try {
      const peer=await mergeRequest('cell-peer',{base_token:current.saved.preview_base_token,field:other,
        body:other==='@owner' ? `相手の担任名（例${count}）` : `【ほかの担当者の入力例${count}】安心して過ごせる環境を整える。`});
      const message=`${peer.name}さんが「${peer.field_label}」を先に保存しました。次に「下書きを保存」を押してください。`;
      document.querySelector('#mock-feedback').textContent=message;announce(message);
      document.dispatchEvent(new CustomEvent('preview-peer-saved'));
    } catch(error){announce(error.message,true);}
    finally {document.querySelectorAll('[data-merge-example]').forEach(el=>el.disabled=false);}
  });
