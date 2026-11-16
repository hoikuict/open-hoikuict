  function reflectionKey(index){return `annual:${boot.document_id}:${index}`;}
  async function saveReflectionDraft(){
    if(!boot.document_id){
      const period=$('#reflection-review-period').value;
      const payload={document_id:boot.document_id,lock_version:boot.lock_version,
        classroom_id:boot.classroom_id,school_year:boot.school_year,owner_name:owner,
        origin:boot.sheet.origin,source_digest:boot.sheet.source_digest,
        fields:Object.fromEntries(Object.entries(cells).map(([key,c])=>[key,{body:c.body,start:c.start,confirmed:c.confirmed}]))};
      const data=await api('save',{method:'POST',body:JSON.stringify(payload)});
      data.reflection_draft=clone(reflection);
      adopt(data);
      $('#reflection-review-period').value=period;
      setBusy(true);
    }
    const result=await window.AnnualMock.saveReflection(boot,reflection);
    boot.reflection=clone(result.reflection);boot.reflection_saved_at=result.reflection_saved_at;
    savedReflection=JSON.stringify(reflection);
  }
  function reflectionStatus(text='',error=false){
    const filled=reflection.flat().filter(value=>value.trim()).length;
    $('.reflection-progress').textContent=`${filled} / 8欄 記入済み`;
    $('.reflection-state').textContent=dirtyReflection()?'未保存の変更あり':boot.reflection_saved_at?'保存済み · '+boot.reflection_saved_at:'未入力';
    $('.reflection-state').classList.toggle('reflection-dirty',dirtyReflection());
    root.querySelectorAll('[data-period-status]').forEach(el=>{el.textContent=window.ReflectionReview.label(reflectionKey(Number(el.dataset.periodStatus)));});
    if($('#reflection-review'))$('#reflection-review').textContent=window.ReflectionReview.isLocked(reflectionKey(Number($('#reflection-review-period').value)))?'承認状況を確認':'承認確認へ進む';
    if(text){$('.reflection-message').textContent=text;$('.reflection-message').setAttribute('role',error?'alert':'status');}
  }
  function renderReflection(){
    const area=$('#annual-reflection-editor');
    area.innerHTML=`<div class="reflection-top"><div><h3>年間指導計画反省</h3><span class="reflection-state"></span></div><div class="reflection-actions no-print"><button id="reflection-reset" type="button">入力を戻す</button><button id="reflection-save" type="button">下書き保存</button></div></div>
      <p class="reflection-meta">${esc(boot.school_year)}年度 · ${esc(boot.classroom_name)}（${boot.age}歳児） / 担任：${esc(boot.owner_name||'未入力')}</p>
      <p class="reflection-note no-print">各期の反省を入力し、承認確認へ進んで管理者へ依頼します。下書き保存では通知されません。年案の承認後も反省を記入できます。${boot.document_id?'':' 年案が未保存の場合は、ここから年案と反省の下書きを保存して進めます。'}</p>
      <div class="rd-scroll"><table class="reflection-grid" aria-label="年間指導計画反省の入力"><thead><tr><th>期</th>${boot.reflection_columns.map(label=>`<th>${esc(label)}</th>`).join('')}</tr></thead><tbody>${boot.reflection_periods.map((period,i)=>`<tr><th scope="row">${esc(period)}<small class="reflection-period-status" data-period-status="${i}"></small></th>${boot.reflection_columns.map((label,j)=>`<td><textarea class="rd-edit" maxlength="20000" data-reflection="${i}:${j}" aria-label="${esc(period)} ${esc(label)}の反省" placeholder="${esc(label)}の反省を記入">${esc(reflection[i][j])}</textarea></td>`).join('')}</tr>`).join('')}</tbody></table></div>
      <div class="reflection-review-controls no-print"><label>承認を依頼する期 <select id="reflection-review-period">${boot.reflection_periods.map((p,i)=>`<option value="${i}">${esc(p)}</option>`).join('')}</select></label><button class="reflection-save" id="reflection-review" type="button">承認確認へ進む</button></div>
      <p class="reflection-progress no-print"></p><p class="reflection-message no-print" role="status" aria-live="polite"></p>`;
    $('#creation-note').textContent=boot.created_at?`作成時のクラス名・保存した担任名を表示しています。作成日時：${boot.created_at}`:'クラスは選択中のクラス、担任は現在の登録内容を表示します。担任名は編集できます。初回保存時の情報を年案に保持します。';
    reflectionStatus();
  }
  root.addEventListener('input',e=>{
    if(e.target.hasAttribute('data-reflection')&&!busy&&boot.reflection_editable){const [i,j]=e.target.dataset.reflection.split(':').map(Number);reflection[i][j]=e.target.value;fit(e.target);reflectionStatus('未保存の変更があります。');}
  });
  root.addEventListener('click',async e=>{
    const button=e.target.closest('button');if(!button||busy)return;
    if(button.id==='reflection-reset'){
      if(dirtyReflection()&&!confirm('反省の未保存の入力を取り消して、最後に保存した内容へ戻しますか？'))return;
      reflection=JSON.parse(savedReflection);renderReflection();pack();setBusy(false);reflectionStatus('最後に保存した反省へ戻しました。');
    }
    if(button.id==='reflection-save'){
      setBusy(true);
      try{
        await saveReflectionDraft();
        reflectionStatus('反省の下書きを保存しました。管理者への通知はまだありません。');
      }catch(error){reflectionStatus(error.message,true);}finally{setBusy(false);}
    }
    if(button.id==='reflection-review'){
      const index=Number($('#reflection-review-period').value),key=reflectionKey(index);
      if(window.ReflectionReview.isLocked(key)){window.ReflectionReview.openRequest(key);return;}
      if(!reflection[index].some(value=>value.trim())){reflectionStatus('承認を依頼する期の反省を入力してください。',true);return;}
      setBusy(true);
      try{
        await saveReflectionDraft();reflectionStatus();
        window.ReflectionReview.openConfirmation({key:reflectionKey(index),kind:'annual',origin:'annual',title:`${boot.school_year}年度 年間指導計画反省（${boot.classroom_name}・${boot.reflection_periods[index]}）`,meta:`${boot.classroom_name}（${boot.age}歳児） / 担任：${boot.owner_name}`,columns:clone(boot.reflection_columns),values:clone(reflection[index])});
      }catch(error){reflectionStatus(error.message,true);}finally{setBusy(false);}
    }
  });
  root.addEventListener('change',e=>{if(e.target.id==='reflection-review-period')reflectionStatus();});
  window.addEventListener('reflection-review-updated',()=>{if($('#reflection-review')){reflectionStatus();setBusy(busy);}});
