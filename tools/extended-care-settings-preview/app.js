(() => {
  'use strict';
  const $ = selector => document.querySelector(selector);
  const esc = value => String(value ?? '').replace(/[&<>"']/g, ch => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[ch]));
  const copy = value => JSON.parse(JSON.stringify(value));
  const money = value => new Intl.NumberFormat('ja-JP').format(value) + '円';
  const calc = window.FeePreviewCalculator;
  const categories = ['standard', 'short'];
  const labels = {standard:'保育標準時間', short:'保育短時間'};
  const shortLabel = {standard:'標準時間', short:'短時間'};
  const sideLabel = {morning:'前延長', evening:'あと延長'};
  let sequence = 0, scene = 'filled', draft = {}, saved = {}, baseline = {}, undo = {}, errorsVisible = {}, pendingSave = null, pendingDiscard = null, toastTimer;
  let modeSaved, billingSaved, legacySaved;
  function band(start = '', end = '', unit = '10', price = '') {return {id:'band'+(++sequence),start,end,mode:'unit',unit,price};}
  function emptyPlan(category) {return {name:shortLabel[category]+'の延長保育料',from:'',to:'',active:true,normalStart:'',normalEnd:'',morningEnabled:null,eveningEnabled:null,morningGrace:'0',eveningGrace:'0',morningBands:[],eveningBands:[],cap:''};}
  function examplePlan(category) {
    const plan = emptyPlan(category);
    Object.assign(plan,{from:'2026-04-01',normalStart:category==='standard'?'07:30':'09:00',normalEnd:category==='standard'?'18:00':'17:00',morningEnabled:category==='short',eveningEnabled:true});
    plan.morningBands = category==='short'?[band('07:30','09:00','15','100')]:[];
    plan.eveningBands = [...(category==='short'?[band('17:00','18:00','15','100')]:[]),band('18:00','19:00','10','100'),band('19:00','20:00','10','200')];
    return plan;
  }
  function loadScene(next) {
    scene = next; sequence = 0; draft = {}; saved = {}; baseline = {}; undo = {}; errorsVisible = {};
    categories.forEach(category=>{
      const plan = scene==='empty'?emptyPlan(category):examplePlan(category);
      draft[category] = copy(plan);
      saved[category] = scene==='empty'?null:copy(plan);
      baseline[category] = copy(plan);
      undo[category] = {};
    });
    if(scene==='partial') {
      saved.short = null; baseline.short = emptyPlan('short');
      draft.short.eveningBands.at(-1).price = '';
      draft.short.from = '';
    }
    if(scene==='error') {
      draft.standard.eveningBands[1].start = '18:45';
      draft.short.eveningBands[1].price = '';
      errorsVisible.standard = errorsVisible.short = true;
    }
    $('#scene').value = scene; $('#fail-next').checked = false; $('#global-notice').hidden = true;
    $('#mode-enabled').checked = scene!=='empty'; $('#mode-from').value = scene==='empty'?'':'2026-04-01';
    modeSaved = getMode();
    $('#billing-form').reset(); $('#legacy-form').reset();
    billingSaved = getBilling(); legacySaved = getLegacy();
    $('#billing-error').hidden = $('#legacy-error').hidden = true;
    $('#billing-status').textContent = billingSaved.enabled?'有効':'無効';
    $('#sim-category').value = 'standard'; $('#sim-date').value = '2026-10-15'; $('#sim-arrival').value = '08:30'; $('#sim-departure').value = '19:20';
    $('#plan-cards').innerHTML = categories.map(renderPlan).join('');
    refresh();
  }
  const dirty = category => JSON.stringify(draft[category]) !== JSON.stringify(baseline[category]);
  function field(category, key, label, value, type='text', attributes='') {
    return '<label>'+label+'<input type="'+type+'" data-field="'+key+'" value="'+esc(value)+'" aria-label="'+shortLabel[category]+' '+esc(label)+'" '+attributes+'></label>';
  }
  function renderBand(category, side, row, index) {
    const name = shortLabel[category]+' '+sideLabel[side]+(index+1);
    const input = (key,label,type,extra='') => '<label'+(type==='time'?' class="time-label"':'')+'>'+label+'<input type="'+type+'" data-field="'+key+'" data-side="'+side+'" data-band="'+row.id+'" value="'+esc(row[key])+'" aria-label="'+name+' '+label+'" '+extra+'></label>';
    return '<div class="band"><div class="band-title"><strong>'+sideLabel[side]+' '+(index+1)+'</strong><button type="button" class="remove-band" data-remove="'+row.id+'" data-side="'+side+'" aria-label="'+name+'を削除">削除</button></div><div class="band-fields">'+input('start','開始','time')+input('end','終了','time')+'</div><div class="band-rate"><label>料金方式<select data-field="mode" data-side="'+side+'" data-band="'+row.id+'" aria-label="'+name+' 料金方式"><option value="unit" '+(row.mode==='unit'?'selected':'')+'>時間ごとに課金</option><option value="flat" '+(row.mode==='flat'?'selected':'')+'>時間帯ごと定額</option></select></label>'+input('unit','何分ごと','number','min="1" max="120" '+(row.mode==='flat'?'disabled':''))+input('price',row.mode==='flat'?'1回の料金（円）':'1単位の料金（円）','number','min="0" placeholder="金額"')+'</div><p class="band-note">'+(row.mode==='flat'?'この時間帯を利用したら1回分。':'端数はこの時間帯の中で切り上げます。')+'</p></div>';
  }
  function renderExtension(category, side) {
    const plan=draft[category], enabled=plan[side+'Enabled'];
    let html='<section class="extension"><div class="extension-head"><div><h3>'+sideLabel[side]+'</h3><small>通常保育'+(side==='morning'?'の前':'のあと')+'</small></div><div class="segmented" role="group" aria-label="'+shortLabel[category]+' '+sideLabel[side]+'の使用">';
    for(const [value,label] of [[true,'使用する'],[false,'使用しない']]) html+='<label><input type="radio" name="'+category+'-'+side+'" data-field="'+side+'Enabled" value="'+value+'" '+(enabled===value?'checked':'')+' aria-label="'+shortLabel[category]+' '+sideLabel[side]+' '+label+'"><span>'+label+'</span></label>';
    html+='</div></div>';
    if(enabled===true) {
      html+='<div class="bands">'+plan[side+'Bands'].map((row,i)=>renderBand(category,side,row,i)).join('')+'</div><button type="button" class="add-band" data-add="'+side+'">＋ '+sideLabel[side]+'の時間帯を追加</button>';
      if(undo[category][side]) html+='<div class="undo-row"><span>時間帯を削除しました</span><button type="button" data-undo="'+side+'">削除を戻す</button></div>';
      html+='<div class="grace"><label>通常保育との境界の猶予<input type="number" min="0" max="120" data-field="'+side+'Grace" value="'+esc(plan[side+'Grace'])+'" aria-label="'+shortLabel[category]+' '+sideLabel[side]+'の猶予">分</label><span>途中の区切りでは再適用しません。</span></div>';
    } else html+='<p class="inactive-note">'+(enabled===false?'<strong>'+sideLabel[side]+'は使用しません。</strong><br>使用するに戻すと、入力した時間帯を復元します。':'「使用する」か「使用しない」を選んでください。')+'</p>';
    return html+'</section>';
  }
  function renderPlan(category) {
    const p=draft[category];
    return '<article class="card plan-card '+category+'" id="plan-'+category+'"><header class="plan-head"><div><h2>'+labels[category]+'</h2><p>区分はこの枠に固定されています</p></div><span class="tag" data-plan-status="'+category+'"></span></header><form id="plan-form-'+category+'" data-category="'+category+'" novalidate><div class="plan-body"><div class="plan-errors" data-errors="'+category+'" tabindex="-1" role="alert" hidden></div><fieldset class="normal-box"><legend>1. 通常保育時間 <span>この時間内は延長料金がかかりません</span></legend><div class="two-times">'+field(category,'normalStart','開始',p.normalStart,'time')+'<span>〜</span>'+field(category,'normalEnd','終了',p.normalEnd,'time')+'</div></fieldset>'+renderExtension(category,'morning')+renderExtension(category,'evening')+'<section class="plan-meta"><h3>適用期間と保存する内容</h3>'+field(category,'name','ルール名',p.name,'text','maxlength="100"')+'<div class="dates">'+field(category,'from','適用開始日',p.from,'date')+field(category,'to','適用終了日（任意）',p.to,'date')+'</div><div class="cap-active">'+field(category,'cap','日別上限額（円・任意）',p.cap,'number','min="0" placeholder="上限なし"')+'<label class="check"><input type="checkbox" data-field="active" '+(p.active?'checked':'')+'>このルールを有効にする</label></div><p class="small muted">上限は前延長・あと延長の合計に適用します。</p></section></div><footer class="card-footer"><p data-save-state="'+category+'"></p><button type="button" data-discard="'+category+'">変更を戻す</button><button type="submit" class="primary">'+shortLabel[category]+'の保存内容を確認</button></footer></form></article>';
  }
  function rerender(category, focus) {
    $('#plan-'+category).outerHTML = renderPlan(category);
    refresh();
    if(focus) $('#plan-'+category+' '+focus)?.focus();
  }
  function showErrors(category) {
    const container=$('[data-errors="'+category+'"]');
    const errors=errorsVisible[category]?calc.validate(draft[category]):[];
    container.hidden=!errors.length;
    container.innerHTML='<strong>入力を確認してください</strong><ul>'+errors.map(item=>'<li>'+esc(item.message)+'</li>').join('')+'</ul>';
    $('#plan-'+category).querySelectorAll('[aria-invalid]').forEach(input=>input.removeAttribute('aria-invalid'));
    errors.forEach(item=>{
      const selector='[data-field="'+item.field+'"]'+(item.id?'[data-band="'+item.id+'"]':'');
      $('#plan-'+category).querySelectorAll(selector).forEach(input=>input.setAttribute('aria-invalid','true'));
    });
    return errors;
  }
  function refresh() {
    categories.forEach(category=>{
      const invalid=showErrors(category).length>0;
      const status=$('[data-plan-status="'+category+'"]');
      status.className='tag '+(invalid?'error':dirty(category)?'dirty':saved[category]?'saved':'neutral');
      status.textContent=invalid?'入力を要確認':dirty(category)?'未保存の変更':saved[category]?(draft[category].active?'保存済み':'保存済み・無効'):'未設定';
      $('[data-save-state="'+category+'"]').textContent=dirty(category)?'まだ保存されていません':saved[category]?'このタブ内の保存内容':'保存すると設定済みになります';
    });
    const readiness=categories.map(category=>shortLabel[category]+'：'+(saved[category]&&saved[category].active?'設定済み':'未設定または無効')).join(' ／ ');
    $('#mode-status').textContent=readiness+'。切替前は下の従来ルールで計算します。';
    runSimulation();
  }
  function runSimulation() {
    const category=$('#sim-category').value, p=draft[category];
    const result=calc.calculate(p,$('#sim-date').value,$('#sim-arrival').value,$('#sim-departure').value);
    if(result.errors.length) {$('#sim-result').innerHTML='<div class="sim-warning"><strong>設定を確認すると試算できます</strong><ul>'+result.errors.map(error=>'<li>'+esc(error)+'</li>').join('')+'</ul></div>';return;}
    let html=result.warnings.length?'<div class="sim-warning"><strong>合計は要確認です</strong><ul>'+result.warnings.map(warning=>'<li>'+esc(warning)+'</li>').join('')+'</ul></div>':'';
    html+='<div class="result-layout"><div><table class="result-table"><thead><tr><th>使用した時間帯</th><th>計算の内訳</th><th>料金</th></tr></thead><tbody>';
    html+=result.lines.length?result.lines.map(line=>'<tr><td>'+esc(line.label)+' '+esc(line.range)+'<small>利用 '+esc(line.usedRange)+'（'+line.used+'分）</small></td><td>'+esc(line.method)+'<small>'+line.units+' × '+money(line.price)+'</small></td><td>'+money(line.amount)+'</td></tr>').join(''):'<tr><td colspan="3">'+(result.warnings.length?'設定済み時間帯での課金はありません。':'通常保育時間内、または猶予時間内のため0円です。')+'</td></tr>';
    html+='</tbody></table></div><div class="result-total '+(result.total===null?'warning':'')+'"><span>'+labels[category]+'の試算</span><strong>'+(result.total===null?'合計は要確認':new Intl.NumberFormat('ja-JP').format(result.total)+'<small>円</small>')+'</strong><p>'+(result.total===null?'設定内の小計 '+money(result.subtotal):result.capped?'小計 '+money(result.subtotal)+' → 日別上限 '+money(result.cap)+' を適用':'前延長・あと延長の合計')+'</p><p>保存前の入力内容で計算</p></div></div>';
    $('#sim-result').innerHTML=html;
  }
  function toast(message) {clearTimeout(toastTimer);$('#toast').textContent=message;$('#toast').hidden=false;toastTimer=setTimeout(()=>{$('#toast').hidden=true;},5000);}
  function openConfirmation(title, html, action, button='この設定を保存') {
    pendingSave=action;$('#confirm-title').textContent=title;$('#confirm-body').innerHTML=html;$('#confirm-error').hidden=true;$('#confirm-save').textContent=button;$('#confirm-dialog').showModal();
  }
  function formatBands(plan, side) {
    if(plan[side+'Enabled']===false)return '使用しない';
    if(plan[side+'Enabled']!==true)return '未設定';
    return plan[side+'Bands'].map(row=>row.start+'〜'+row.end+' ／ '+(row.mode==='flat'?'時間帯ごと':row.unit+'分ごと')+money(Number(row.price))).join('、')+' ／ 境界の猶予'+plan[side+'Grace']+'分';
  }
  function planSummary(plan) {
    if(!plan)return '<p class="muted">この区分はまだ保存されていません。</p>';
    const values=[['通常保育',plan.normalStart+'〜'+plan.normalEnd],['前延長',formatBands(plan,'morning')],['あと延長',formatBands(plan,'evening')],['適用期間',plan.from+'〜'+(plan.to||'終了日なし')],['日別上限',plan.cap===''?'上限なし':money(Number(plan.cap))],['状態',plan.active?'有効':'無効'],['ルール名',plan.name]];
    return '<dl class="diff">'+values.map(([label,value])=>'<dt>'+label+'</dt><dd>'+esc(value)+'</dd>').join('')+'</dl>';
  }
  function savePlan(category) {
    errorsVisible[category]=true;
    if(showErrors(category).length) {refresh();$('[data-errors="'+category+'"]').focus();return;}
    if(saved[category]&&!dirty(category)){toast('保存済みの内容から変更はありません。');return;}
    const candidate=copy(draft[category]);
    openConfirmation(labels[category]+'の保存内容', '<p class="notice">'+labels[category]+'として保存します。もう一方の区分は変更しません。</p>'+planSummary(candidate)+'<details class="quiet-details"><summary>保存前の内容を見る</summary>'+planSummary(saved[category])+'</details><p>設定の保存だけでは過去の料金は変わりません。保存後に対象月を選んで確認します。</p>',()=>{
      saved[category]=copy(candidate);baseline[category]=copy(candidate);errorsVisible[category]=false;undo[category]={};refresh();toast(labels[category]+'の設定をこのタブ内に保存しました。');
    });
  }
  function requestDiscard(text, action) {pendingDiscard=action;$('#discard-text').textContent=text;$('#discard-dialog').showModal();}
  function getMode(){return {enabled:$('#mode-enabled').checked,from:$('#mode-from').value};}
  function getBilling(){return {enabled:$('#billing-enabled').checked,code:$('#billing-code').value.trim(),template:$('#billing-template').value.trim()};}
  function getLegacy(){return Object.fromEntries(['name','from','to','start','grace','unit','price','cap','active'].map(key=>{const el=$('#legacy-'+key);return [key,el.type==='checkbox'?el.checked:el.value];}));}
  document.querySelectorAll('button:not([type])').forEach(button=>{if(!button.closest('form'))button.type='button';});
  $('#plan-cards').addEventListener('submit',event=>{event.preventDefault();savePlan(event.target.dataset.category);});
  $('#plan-cards').addEventListener('input',event=>{
    const el=event.target, form=el.closest('[data-category]');
    if(!form||!el.dataset.field)return;
    const category=form.dataset.category, key=el.dataset.field, p=draft[category];
    if(el.dataset.band){const row=p[el.dataset.side+'Bands'].find(row=>row.id===el.dataset.band);row[key]=el.value;}
    else p[key]=el.type==='checkbox'?el.checked:el.type==='radio'?el.value==='true':el.value;
    if(el.type==='radio') {
      const side=key.startsWith('morning')?'morning':'evening';
      if(p[key]&&!p[side+'Bands'].length)p[side+'Bands'].push(band(side==='evening'?p.normalEnd:'',side==='morning'?p.normalStart:''));
      rerender(category,'[data-field="'+key+'"][value="'+el.value+'"]');
    } else if(key==='mode')rerender(category,'[data-band="'+el.dataset.band+'"][data-field="mode"]');
    else refresh();
  });
  $('#plan-cards').addEventListener('click',event=>{
    const button=event.target.closest('button'), form=button?.closest('[data-category]');
    if(!button||!form)return;
    const category=form.dataset.category,p=draft[category];
    if(button.dataset.add){const side=button.dataset.add,rows=p[side+'Bands'];const next=side==='morning'?band('',rows[0]?.start||p.normalStart):band(rows.at(-1)?.end||p.normalEnd,'');if(side==='morning')rows.unshift(next);else rows.push(next);rerender(category,'[data-band="'+next.id+'"][data-field="'+(side==='morning'?'start':'end')+'"]');}
    if(button.dataset.remove){const side=button.dataset.side,rows=p[side+'Bands'],index=rows.findIndex(row=>row.id===button.dataset.remove);undo[category][side]={band:rows[index],index};rows.splice(index,1);rerender(category,'[data-undo="'+side+'"]');}
    if(button.dataset.undo){const side=button.dataset.undo,item=undo[category][side];p[side+'Bands'].splice(item.index,0,item.band);delete undo[category][side];rerender(category);}
    if(button.dataset.discard){if(!dirty(category))return toast('未保存の変更はありません。');requestDiscard(labels[category]+'の未保存の入力を戻します。',()=>{draft[category]=copy(baseline[category]);errorsVisible[category]=false;undo[category]={};rerender(category);toast('未保存の変更を戻しました。');});}
  });
  ['sim-category','sim-date','sim-arrival','sim-departure'].forEach(id=>$('#'+id).addEventListener('input',runSimulation));
  document.querySelectorAll('[data-leave]').forEach(button=>button.addEventListener('click',()=>{$('#sim-departure').value=button.dataset.leave;runSimulation();}));
  document.querySelectorAll('[data-close]').forEach(button=>button.addEventListener('click',()=>$('#'+button.dataset.close).close()));
  $('#confirm-save').addEventListener('click',()=>{
    if($('#fail-next').checked){$('#fail-next').checked=false;$('#confirm-error').textContent='保存に失敗しました（試用のエラー）。入力は残っています。再度保存するか、入力に戻ってください。';$('#confirm-error').hidden=false;return;}
    pendingSave?.();$('#confirm-dialog').close();pendingSave=null;
  });
  $('#discard-yes').addEventListener('click',()=>{pendingDiscard?.();$('#discard-dialog').close();pendingDiscard=null;});
  $('#open-spec').addEventListener('click',()=>$('#spec-dialog').showModal());
  $('#scene').addEventListener('change',()=>{const next=$('#scene').value;$('#scene').value=scene;requestDiscard('試用状態を切り替えます。このタブ内の保存内容と入力を、架空の例に置き換えます。',()=>loadScene(next));});
  $('#reset').addEventListener('click',()=>requestDiscard('このタブ内の保存内容と入力を、選択中の試用状態の初期値に戻します。',()=>loadScene(scene)));
  $('#save-mode').addEventListener('click',()=>{
    const candidate=getMode(),missing=categories.filter(category=>!saved[category]||!saved[category].active||calc.validate(saved[category]).length);
    if(candidate.enabled&&(!calc.dateOK(candidate.from)||missing.length)){
      const notice=$('#global-notice');notice.className='error-box';notice.textContent=!calc.dateOK(candidate.from)?'区分別計算の切替開始日を入力してください。':'先に'+missing.map(category=>labels[category]).join('・')+'の有効な設定を保存してください。このモックは両区分を利用する例です。';notice.hidden=false;notice.scrollIntoView({behavior:'smooth',block:'center'});return;
    }
    if(JSON.stringify(candidate)===JSON.stringify(modeSaved))return toast('計算モードに変更はありません。');
    openConfirmation('計算モードの保存','<p>区分別計算：<strong>'+(candidate.enabled?'有効（'+esc(candidate.from)+'から）':'無効・従来計算')+'</strong></p><p>過去の料金を変更するには、別途対象月の再計算が必要です。</p>',()=>{modeSaved=copy(candidate);toast('計算モードをこのタブ内に保存しました。');});
  });
  $('#billing-form').addEventListener('submit',event=>{
    event.preventDefault();const candidate=getBilling();$('#billing-error').hidden=true;
    if(!candidate.code||!candidate.template){$('#billing-error').textContent='請求費目コードと明細名テンプレートを入力してください。';$('#billing-error').hidden=false;return;}
    openConfirmation('請求連携設定の保存','<p>請求連携：'+(candidate.enabled?'有効':'無効')+'</p><p>費目：'+esc(candidate.code)+'</p><p>明細名：'+esc(candidate.template)+'</p><p>月次手動・同じ月へ転送。この操作では請求を送信しません。</p>',()=>{billingSaved=copy(candidate);$('#billing-status').textContent=candidate.enabled?'有効':'無効';toast('請求連携設定をこのタブ内に保存しました。');});
  });
  $('#legacy-form').addEventListener('submit',event=>{
    event.preventDefault();const v=getLegacy(),issues=[];
    if(!v.name.trim())issues.push('ルール名を入力してください。');
    if(!calc.dateOK(v.from)||v.to&&(!calc.dateOK(v.to)||v.to<v.from))issues.push('適用期間を確認してください。');
    if(!Number.isFinite(calc.minute(v.start)))issues.push('延長開始時刻を入力してください。');
    if(!calc.integer(v.grace,0,120)||!calc.integer(v.unit,1,120)||!calc.integer(v.price,0)||v.cap!==''&&!calc.integer(v.cap,0))issues.push('猶予0〜120分・課金単位1〜120分・料金と上限は0円以上で入力してください。');
    $('#legacy-error').hidden=!issues.length;$('#legacy-error').textContent=issues.join(' ');if(issues.length)return;
    openConfirmation('従来ルールの保存','<p class="notice">区分なしの従来計算用です。保育標準時間の設定にはなりません。</p><p>'+esc(v.name)+' ／ '+esc(v.from)+'〜'+esc(v.to||'終了日なし')+'</p><p>'+esc(v.start)+'から（猶予'+esc(v.grace)+'分）、'+esc(v.unit)+'分ごとに'+money(Number(v.price))+'</p><p>日別上限：'+(v.cap===''?'上限なし':money(Number(v.cap)))+' ／ '+(v.active?'有効':'無効')+'</p>',()=>{legacySaved=copy(v);toast('従来ルールをこのタブ内に保存しました。');});
  });
  $('#preview-recalc').addEventListener('click',()=>{
    const month=$('#recalc-month').value;
    if(!month)return toast('再計算する月を選択してください。');
    const days=['05','06','07'],times=['18:50','19:20','19:10'],statuses=['未確定','未確定','確定済み'];
    let count=0;
    const rows=days.map((day,i)=>{
      const p=saved.standard;
      let result=p?calc.calculate(p,month+'-'+day,'08:30',times[i]):null;
      let action=i===2?'保護・変更しない':!modeSaved.enabled?'区分別計算は無効':month+'-'+day<modeSaved.from?'切替前・従来ルールで要確認':!result||result.total===null?'設定を確認':money(result.total);
      if(i!==2&&modeSaved.enabled&&month+'-'+day>=modeSaved.from&&result?.total!==null&&result){count++;}
      return '<tr><td>'+esc(month+'-'+day)+'</td><td>架空 園児A<br>'+times[i]+'降園</td><td>'+statuses[i]+'</td><td>'+action+'</td></tr>';
    }).join('');
    openConfirmation('再計算の確認（架空データ）','<p class="notice">保存済みの標準時間設定で、架空の3日を確認しています。未保存の入力は使用しません。</p><table><thead><tr><th>日付</th><th>利用例</th><th>料金の状態</th><th>再計算後</th></tr></thead><tbody>'+rows+'</tbody></table><p>変更できる未確定の記録：'+count+'日分。確定・調整・対象外・請求転送済みは保護します。</p>',()=>toast(count+'日分の再計算操作を試しました。架空の確認のみです。'),'再計算を試す（モック）');
  });
  loadScene('filled');
})();
