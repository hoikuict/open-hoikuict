(() => {
  'use strict';
  const $ = s => document.querySelector(s);
  const esc = v => String(v ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const copy = v => JSON.parse(JSON.stringify(v));
  const same = (a,b) => JSON.stringify(a) === JSON.stringify(b);
  const categoryName = v => ({standard:'保育標準時間',short:'保育短時間'}[v] || '未選択');
  const reasons = [['employment','就労'],['pregnancy_childbirth','妊娠・出産'],['illness_disability','保護者の疾病・負傷・障害'],['family_care_nursing','同居または長期入院等している親族の介護・看護'],['disaster_recovery','災害復旧'],['job_search_startup','求職活動・起業準備'],['education_training','就学・職業訓練'],['abuse_dv','虐待・DVのおそれ'],['childcare_leave_continuation','育児休業取得時の継続利用'],['other_municipal','その他、市町村が認める事由']];
  let state=JSON.parse($('#family-care').dataset.state);
  let children=state.children;
  const endpoint='/families/'+state.familyId+'/care-certifications/';
  async function send(action, body){
    const response=await fetch(endpoint+action,{method:'POST',headers:{'Content-Type':'application/json','X-CSRF-Token':$('#family-care').dataset.csrf},body:JSON.stringify(body)});
    let result;try{result=await response.json();}catch{throw new Error('保存結果を確認できませんでした。入力を控えて、画面を再読み込みしてください。');}
    if(!response.ok)throw new Error(typeof result.detail==='string'?result.detail:'保存できませんでした。入力を確認してください。');
    return result;
  }
  function loadState(value){
    state=value;children=value.children;store=copy(value.store);
    draft={common:copy(store.common||blank()),children:copy(store.children)};
    children.forEach(c=>{draft.children[c.id].cert ||= blank();});
    operation=store.common?'correct':'new';editReason='';showErrors=false;remember();render();
  }
  function blank(){return {category:'',from:'',to:'',reason1:'',other1:'',reason2:'',other2:'',note:''};}
  let store, draft, baseline, operation='new', editReason='', showErrors=false, pendingDiscard=null, pendingSave=null;
  const period = p => p ? `${p.from || '開始日未入力'} 〜 ${p.to || '終了日なし'}` : '未登録';
  const dirty = () => !same({draft,operation,editReason},baseline);
  function remember(){baseline=copy({draft,operation,editReason});}
  function fields(scope,p){
    const prefix=scope==='common'?'家族共通':children.find(c=>c.id===scope).name;
    const accessible=(key,label)=>prefix+' '+(/^(other|reason)[12]$/.test(key)?'保護者'+key.slice(-1)+' ':'')+label;
    const input=(key,label,type='text',extra='')=>`<label>${label}<input type="${type}" data-scope="${scope}" data-field="${key}" aria-label="${esc(accessible(key,label))}" value="${esc(p[key])}" ${extra}></label>`;
    const select=(key,label,options)=>`<label>${label}<select data-scope="${scope}" data-field="${key}" aria-label="${esc(accessible(key,label))}">${[['','選択してください'],...options].map(([v,t])=>`<option value="${v}" ${p[key]===v?'selected':''}>${esc(t)}</option>`).join('')}</select></label>`;
    return `<div class="fields">${select('category','保育必要量',[['standard','保育標準時間'],['short','保育短時間']])}<div class="dates">${input('from','適用開始日','date',scope==='common'&&operation==='correct'?'readonly':'')}${input('to','適用終了日','date')}</div>${[1,2].filter(i=>i<=state.guardians.length||p['reason'+i]).map(i=>`<div class="guardian"><h3>${esc(state.guardians[i-1]?.name||'保護者'+i)}（${esc(state.guardians[i-1]?.relationship||'')}）</h3><p>保護者${i}</p>${select('reason'+i,'保育を必要とする事由',reasons)}${input('other'+i,'「その他」の具体名','text','maxlength="200"')}<span class="hint">「その他」を選んだときに入力します。</span></div>`).join('')}<label class="span">施設内メモ <span class="optional">任意・500文字まで</span><textarea rows="2" maxlength="500" data-scope="${scope}" data-field="note" aria-label="${esc(prefix)} 施設内メモ">${esc(p.note)}</textarea></label></div>`;
  }
  function current(c){
    const item=store.children[c.id],p=item.cert;
    if(!p)return null;
    return {...p,from:[p.from,c.enrolled,c.joined].sort().at(-1),to:[p.to,c.left].filter(Boolean).sort()[0]||''};
  }
  function resolved(c,source=draft){
    const item=source.children[c.id],p=item.mode==='individual'?item.cert:source.common;
    if(!p?.from)return {p,from:'',to:'',eligible:!c.excluded,label:'適用開始日を入力してください'};
    const from=[p.from,c.enrolled,c.joined].sort().at(-1),to=[p.to,c.left].filter(Boolean).sort()[0]||'';
    return {p,from,to,eligible:!to||from<=to,label:`${from} 〜 ${to||'終了日なし'}`};
  }
  function renderChildren(){
    $('#children').innerHTML=children.map(c=>{
      const d=draft.children[c.id],old=current(c),r=resolved(c),retired=c.excluded;
      return `<article class="child ${retired?'excluded':''}"><div class="child-top"><div><h3>${esc(c.name)}</h3><span class="badge ${d.mode==='individual'?'individual':'neutral'}">${c.status}</span><p>${esc(c.classroom)} ／ 入園 ${c.enrolled}${c.left?' ／ 卒園 '+c.left:''}</p><p>登録済み：${old?categoryName(old.category)+' ／ '+(store.children[c.id].mode==='individual'?'個別設定':'家族共通'):'未登録'}</p></div>${retired?'<span class="badge neutral">卒園・退園のため対象外</span>':`<div class="choice" role="group" aria-label="${esc(c.name)}の設定方法">${[['inherit','家族共通を使う'],['individual','個別に設定']].map(([v,t])=>`<label><input type="radio" name="mode-${c.id}" data-child-mode="${c.id}" value="${v}" ${d.mode===v?'checked':''}><span>${t}</span></label>`).join('')}</div>`}</div>${!retired&&d.mode==='individual'?`<div class="child-body"><p class="muted">この園児は、家族共通を変更しても下の設定を維持します。</p>${fields(c.id,d.cert)}</div>`:`<div class="inherit-line" data-inherit="${c.id}">${retired?'卒園前の履歴はそのまま残します。':esc(r.label)}</div>`}</article>`;
    }).join('');
  }
  function impactMarkup(){return children.map(c=>{
    const old=current(c),d=draft.children[c.id],r=resolved(c),excluded=c.excluded||!r.eligible;
    const before=old?`${categoryName(old.category)}<small>${period(old)}</small>`:'未登録';
    const after=c.excluded?'変更なし<small>卒園・退園前の記録を保持</small>':!r.eligible?'この期間は認定なし<small>以前の共通設定は新しい開始日の前日まで</small>':`${categoryName(r.p?.category)} <span class="badge ${d.mode==='individual'?'individual':''}">${d.mode==='individual'?'個別':'家族共通'}</span><small>${r.label}</small>${store.children[c.id].mode==='individual'&&d.mode==='inherit'?'<small>個別設定から家族共通へ切替</small>':''}`;
    return `<div class="impact-row"><div><strong>${esc(c.name)}</strong><small>${c.status}</small></div><div>${before}</div><span>→</span><div class="after">${after}</div></div>`;
  }).join('');}
  function refresh(){
    const commonCount=children.filter(c=>!c.excluded&&draft.children[c.id].mode==='inherit'&&resolved(c).eligible).length;
    const individualCount=children.filter(c=>!c.excluded&&draft.children[c.id].mode==='individual').length;
    $('#counts').textContent=`共通 ${commonCount}名 ／ 個別 ${individualCount}名`;
    $('#impact').innerHTML=impactMarkup();
    children.forEach(c=>{const el=$(`[data-inherit="${c.id}"]`);if(el&&!c.excluded){const r=resolved(c);el.textContent=r.eligible?`反映する内容：${categoryName(r.p?.category)} ／ ${r.label}`:'この適用期間には在籍していません。';}});
    $('#common-state').textContent=dirty()?'未保存の変更':operation==='new'?'新しい期間の入力':'登録済み';
    $('#dirty-state').textContent=dirty()?'まだ保存されていません。':'内容を確認してから、家族と園児へまとめて保存します。';
    if(showErrors)renderErrors();
  }
  function render(){
    $('#operation').value=operation;$('#operation').querySelector('[value=correct]').disabled=!store.common;
    $('#current-common').innerHTML=store.common?`<strong>現在の共通設定</strong>${categoryName(store.common.category)} ／ ${period(store.common)}`:'家族共通の認定はまだ登録されていません。';
    $('#operation-help').textContent=operation==='correct'?'この登録済み期間の内容を訂正します。変更前の内容と訂正理由を履歴へ残します。':'開始日から新しい認定に切り替えます。以前の共通設定は開始日の前日まで残します。';
    $('#correction-row').hidden=operation!=='correct';$('#correction-reason').value=editReason;
    $('#common-fields').innerHTML=fields('common',draft.common);renderChildren();renderHistory();refresh();
    if(!showErrors)$('#errors').hidden=true;
  }
  function validDate(v){return /^\d{4}-\d{2}-\d{2}$/.test(v)&&!Number.isNaN(Date.parse(v+'T00:00:00Z'))&&new Date(v+'T00:00:00Z').toISOString().slice(0,10)===v;}
  function validate(){
    const errors=[];
    const check=(p,scope,label)=>{
      const add=(field,message)=>errors.push({scope,field,message:label+'：'+message});
      if(!['standard','short'].includes(p.category))add('category','保育必要量を選択してください。');
      if(!validDate(p.from))add('from','適用開始日を入力してください。');
      if(p.to&&(!validDate(p.to)||p.to<p.from))add('to','適用終了日は開始日以降にしてください。');
      [1,2].filter(i=>i<=state.guardians.length||p['reason'+i]).forEach(i=>{if(!p['reason'+i])add('reason'+i,`保護者${i}の事由を選択してください。`);if(p['reason'+i]==='other_municipal'&&!p['other'+i].trim())add('other'+i,`保護者${i}の「その他」の具体名を入力してください。`);});
    };
    check(draft.common,'common','家族共通');
    if(operation==='new'&&store.common&&draft.common.from<=store.common.from)errors.push({scope:'common',field:'from',message:'新しい期間は登録済み期間の開始日より後にしてください。同じ期間の修正は「登録済みの期間を訂正」を選びます。'});
    if(operation==='correct'&&!editReason.trim())errors.push({message:'訂正理由を入力してください。'});
    children.filter(c=>!c.excluded&&draft.children[c.id].mode==='individual').forEach(c=>check(draft.children[c.id].cert,c.id,c.name));
    return errors;
  }
  function renderErrors(){
    const errors=validate();$('#errors').hidden=!errors.length;
    $('#errors').innerHTML='<strong>入力を確認してください</strong><ul>'+errors.map(e=>'<li>'+esc(e.message)+'</li>').join('')+'</ul>';
    document.querySelectorAll('[aria-invalid]').forEach(el=>el.removeAttribute('aria-invalid'));
    errors.forEach(e=>{if(e.scope)$(`[data-scope="${e.scope}"][data-field="${e.field}"]`)?.setAttribute('aria-invalid','true');});return errors;
  }
  function summary(p){return `<dl><dt>保育必要量</dt><dd>${categoryName(p.category)}</dd><dt>適用期間</dt><dd>${period(p)}</dd>${[1,2].filter(i=>i<=state.guardians.length||p['reason'+i]).map(i=>`<dt>保護者${i}の事由</dt><dd>${esc(reasons.find(x=>x[0]===p['reason'+i])?.[1])}${p['reason'+i]==='other_municipal'?' ／ '+esc(p['other'+i]):''}</dd>`).join('')}<dt>施設内メモ</dt><dd>${esc(p.note)||'なし'}</dd></dl>`;}
  function renderHistory(){
    $('#history').innerHTML=store.history.map((h,i)=>`<div class="history-row"><div><strong>${esc(h.name)}</strong> <span class="badge ${h.active?'':'neutral'}">${h.active?'有効な登録':'過去の記録'}</span><p>${categoryName(h.cert.category)} ／ ${period(h.cert)}</p><small>${esc(h.text)}</small>${h.cert.note?'<small>施設内メモ：'+esc(h.cert.note)+'</small>':''}</div>${h.active&&h.name==='家族共通'?'<button type="button" data-deactivate="'+i+'" class="danger">理由を付けて無効化</button>':''}</div>`).join('')||'<p class="muted">家族共通の登録履歴はまだありません。</p>';
    const individuals=children.filter(c=>store.children[c.id].mode==='individual'&&store.children[c.id].cert);
    $('#history').innerHTML+=individuals.map(c=>`<div class="history-row"><div><strong>${esc(c.name)}</strong> <span class="badge individual">個別設定</span><p>${categoryName(store.children[c.id].cert.category)} ／ ${period(store.children[c.id].cert)}</p><small>園児個別の認定履歴として保持</small></div></div>`).join('');
  }
  $('#cert-form').addEventListener('input',event=>{
    const el=event.target;if(el.dataset.scope){const p=el.dataset.scope==='common'?draft.common:draft.children[el.dataset.scope].cert;p[el.dataset.field]=el.value;refresh();}
    if(el.id==='correction-reason'){editReason=el.value;refresh();}
  });
  $('#children').addEventListener('change',event=>{
    const id=event.target.dataset.childMode;if(!id)return;
    const item=draft.children[id];item.mode=event.target.value;
    if(item.mode==='individual'&&!item.cert.category)item.cert=copy(draft.common);
    renderChildren();refresh();
  });
  $('#operation').addEventListener('change',()=>{
    operation=$('#operation').value;draft.common=operation==='correct'?copy(store.common):{...copy(store.common||blank()),from:'',to:''};editReason='';render();
  });
  $('#cert-form').addEventListener('submit',async event=>{
    event.preventDefault();showErrors=true;if(renderErrors().length){$('#errors').focus();return;}
    pendingSave=copy({draft,operation,editReason,revision:state.revision});
    const submit=$('#cert-form button[type=submit]');submit.disabled=true;
    try{await send('preview',pendingSave);}catch(error){$('#errors').textContent=error.message;$('#errors').hidden=false;$('#errors').focus();return;}finally{submit.disabled=false;}
    $('#confirm-summary').innerHTML='<h3>'+ (operation==='correct'?'登録済み期間の訂正':'新しい期間への切替')+'</h3>'+summary(draft.common)+(editReason?'<p>訂正理由：'+esc(editReason)+'</p>':'')+'<p class="muted">下の園児に反映します。料金の再計算は別操作です。</p>';
    $('#confirm-summary').innerHTML+=children.filter(c=>!c.excluded&&draft.children[c.id].mode==='individual').map(c=>'<details><summary>'+esc(c.name)+'の個別設定を確認</summary>'+summary(draft.children[c.id].cert)+'</details>').join('');
    $('#confirm-impact').innerHTML=impactMarkup();$('#save-error').hidden=true;$('#confirm').showModal();
  });
  $('#save').addEventListener('click',async()=>{
    $('#save').disabled=true;
    try{const result=await send('save',pendingSave);$('#confirm').close();loadState(result);
      $('#saved-message').textContent='保存しました。家族共通と園児個別の認定を反映しました。過去料金は再計算していません。';$('#saved-message').hidden=false;$('#saved-message').scrollIntoView({block:'center'});
    }catch(error){$('#save-error').textContent=error.message;$('#save-error').hidden=false;}
    finally{$('#save').disabled=false;}
  });
  $('#reset-draft').addEventListener('click',()=>{pendingDiscard=()=>{draft=copy(baseline.draft);operation=baseline.operation;editReason=baseline.editReason;showErrors=false;render();};$('#discard').showModal();});
  $('#discard-yes').addEventListener('click',()=>{pendingDiscard?.();$('#discard').close();});
  document.addEventListener('click',event=>{const close=event.target.closest('[data-close]');if(close)$('#'+close.dataset.close).close();});
  $('#history').addEventListener('click',event=>{
    if(!event.target.closest('[data-deactivate]'))return;
    const names=children.filter(c=>!c.excluded&&store.children[c.id].mode==='inherit').map(c=>c.name);
    $('#deactivate-impact').textContent='対象：'+names.join('、')+' ／ '+period(store.common);
    $('#deactivate-reason').value='';$('#deactivate-error').hidden=true;$('#deactivate').showModal();
  });
  $('#deactivate-yes').addEventListener('click',async()=>{
    const reason=$('#deactivate-reason').value.trim();if(!reason){$('#deactivate-error').hidden=false;return;}
    $('#deactivate-yes').disabled=true;
    try{const result=await send('deactivate',{reason,revision:state.revision});$('#deactivate').close();loadState(result);
      $('#saved-message').textContent='家族共通の認定を無効化しました。個別設定は保持されています。';$('#saved-message').hidden=false;
    }catch(error){$('#deactivate-error').textContent=error.message;$('#deactivate-error').hidden=false;}
    finally{$('#deactivate-yes').disabled=false;}
  });
  window.addEventListener('beforeunload',event=>{if(dirty()){event.preventDefault();event.returnValue='';}});
  loadState(state);
})();
