  // This form and all its requests exist only in the fictional preview app.
  const phraseDialog = document.querySelector('#phrase-dialog');
  const pq = selector => phraseDialog.querySelector(selector);
  const phraseCatalog = JSON.parse(document.querySelector('#preview-phrase-catalog').textContent);
  let editingPhrase = null, phraseSaving = false;
  const phraseToolbar = document.createElement('div');
  phraseToolbar.className = 'phrase-toolbar';
  phraseToolbar.innerHTML = '<small>園内で共有する文例</small><button type="button" id="add-phrase">＋ 文例を追加</button>';
  q('.target').after(phraseToolbar);
  q('[data-mode="original"]').textContent = '原文・園の文例';
  pq('#phrase-age').innerHTML = Array.from({length:6},(_,i)=>`<option value="${i}">${i}歳児</option>`).join('');
  pq('#phrase-month').insertAdjacentHTML('beforeend',Array.from({length:12},(_,i)=>`<option value="${i+1}">${i+1}月</option>`).join(''));

  const baseOriginHtml = originHtml;
  originHtml = function(row) {
    if (!row.is_facility) return baseOriginHtml(row);
    return `<p>園で追加した文例 · ${esc(row.created_by)}<br>${esc(row.age)}歳児 / ${row.registered_month?'毎年'+esc(row.registered_month)+'月':'すべての月'} / ${esc(row.field_label)}<br>${esc(row.source_note || '出所メモなし')}<br>登録番号 ${row.facility_id} / 第${row.version}版<br>${esc(row.text)}</p>`;
  };
  const baseDisplayCandidates = displayCandidates;
  displayCandidates = function() {
    baseDisplayCandidates();
    all('[data-candidate]').forEach(button => {
      const index = Number(button.dataset.candidate), row = candidateRows[index];
      if (!row.is_facility) return;
      button.insertAdjacentHTML('afterbegin','<span class="facility-tag">園で追加した文例</span>');
      button.insertAdjacentHTML('afterend',`<div class="facility-action"><button type="button" data-phrase-edit="${index}">文例を修正・削除</button></div>`);
    });
  };
  const basePanel = panel;
  panel = function(load=true) {
    basePanel(load);
    q('#add-phrase').disabled = !editable() || !ctx().definitions[current.field]?.section;
  };
  function phraseOptions(selected) {
    const defs = phraseCatalog[pq('#phrase-age').value];
    pq('#phrase-field').innerHTML = Object.entries(defs).map(([key,d]) =>
      `<option value="${esc(key)}">${esc(d.section+' / '+d.label)}</option>`).join('');
    if (defs[selected]) pq('#phrase-field').value = selected;
  }
  function phraseError(message) {
    pq('#phrase-error').textContent = message;
    pq('#phrase-error').hidden = !message;
  }
  function openPhrase(row=null) {
    commitEdit(); editingPhrase = row;
    pq('#phrase-age').value = row?.age ?? ctx().age;
    pq('#phrase-month').value = row?.registered_month ?? Number(ctx().target_month.slice(5));
    const field = current.field.startsWith('child:') ? 'personal:'+current.field.split(':')[2] : current.field;
    phraseOptions(row?.field_code || field);
    pq('#phrase-text').value = row?.text || '';
    pq('#phrase-note').value = row?.source_note || '';
    pq('#phrase-title').textContent = row ? '園の文例を修正' : '文例を追加';
    pq('#phrase-submit').textContent = row ? '変更を保存' : '園の文例として登録';
    pq('#phrase-delete').hidden = !row;
    pq('#phrase-delete-confirm').hidden = true;
    phraseError(''); phraseDialog.showModal(); pq('#phrase-text').focus();
  }
  root.addEventListener('click', event => {
    const button = event.target.closest('button');
    if (button?.id === 'add-phrase') openPhrase();
    if (button?.dataset.phraseEdit !== undefined) openPhrase(candidateRows[Number(button.dataset.phraseEdit)]);
  });
  pq('#phrase-age').addEventListener('change', () => phraseOptions(pq('#phrase-field').value));
  pq('#phrase-cancel').addEventListener('click', () => {if (!phraseSaving) phraseDialog.close();});
  phraseDialog.addEventListener('cancel', event => {if (phraseSaving) event.preventDefault();});
  pq('#phrase-delete').addEventListener('click', () => {pq('#phrase-delete-confirm').hidden=false;});
  pq('#phrase-delete-cancel').addEventListener('click', () => {pq('#phrase-delete-confirm').hidden=true;});
  async function phraseRequest(path, method, payload) {
    const errorToggle = document.querySelector('#preview-phrase-error');
    if (errorToggle.checked) {
      errorToggle.checked = false;
      throw new Error('【見本のエラー】登録できませんでした。入力は残っています。もう一度登録してください。');
    }
    const token = document.querySelector('meta[name="csrf-token"]')?.content || '';
    return api(path,{method,headers:{'Content-Type':'application/json','X-CSRF-Token':token},
      ...(payload ? {body:JSON.stringify(payload)} : {})});
  }
  function phraseBusy(value) {
    phraseSaving=value;
    phraseDialog.querySelectorAll('input,textarea,select,button').forEach(el => el.disabled=value);
  }
  pq('#phrase-form').addEventListener('submit', async event => {
    event.preventDefault(); if (phraseSaving) return;
    const text = pq('#phrase-text').value.trim();
    if (!text) {phraseError('文例の本文を入力してください。');pq('#phrase-text').focus();return;}
    const payload = {text,source_note:pq('#phrase-note').value,
      age:Number(pq('#phrase-age').value),month:Number(pq('#phrase-month').value),
      field_code:pq('#phrase-field').value,version:editingPhrase?.version || 0};
    phraseError('');phraseBusy(true);
    try {
      await phraseRequest('preview-phrases'+(editingPhrase?'/'+editingPhrase.facility_id:''),editingPhrase?'PUT':'POST',payload);
      phraseDialog.close(); mode='original'; keyword='';q('#keyword').value='';
      await search();
      const definition=ctx().definitions[current.field], selected=phraseCatalog[payload.age][payload.field_code];
      const inScope=payload.age===ctx().age && (!payload.month || payload.month===Number(ctx().target_month.slice(5)))
        && ['section','item','ryoiki'].every(key=>definition?.[key]===selected[key]);
      announce((editingPhrase?'園の文例を更新しました。':'園の文例を登録しました。')
        +(inScope?'候補から選ぶと帳票に入ります。':'登録先の年齢・月・項目を選ぶと候補に表示します。')
        +'（見本内のみ・検索語をクリアしました）');
    } catch(error) {phraseError(error.message);}
    finally {phraseBusy(false);}
  });
  pq('#phrase-delete-execute').addEventListener('click', async () => {
    if (phraseSaving || !editingPhrase) return;
    phraseError('');phraseBusy(true);
    try {
      await phraseRequest(`preview-phrases/${editingPhrase.facility_id}?version=${editingPhrase.version}`,'DELETE');
      phraseDialog.close();await search();announce('園の文例を候補から削除しました。帳票の文章と出典はそのままです。（見本内のみ）');
    } catch(error) {phraseError(error.message);}
    finally {phraseBusy(false);}
  });
