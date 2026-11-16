(() => {
 const parentWindow=window.parent,review=parentWindow.ReflectionReview,key='daily:fictional-1',form=document.querySelector('.daily-reflection-panel form'),input=form.querySelector('[name=reflection_body]'),status=document.querySelector('#daily-reflection-status'),message=document.querySelector('#day-message');
 let saved='',mode=parentWindow.AnnualMock.mode(),timer=null;
 const sample='集いでは歌や手遊びに笑顔で応じる姿が見られた。眠気のある子は静かな場所で休めるようにした。次回も一人ひとりの生活リズムに合わせて参加する。';
 const jump=document.createElement('a');jump.className='day-jump no-print';jump.href='#daily-reflection-heading';jump.textContent='その日の振り返りへ';message.after(jump);
 const detail=document.createElement('button');detail.type='button';detail.className='daily-status-button no-print';detail.textContent='反省の承認状況';status.after(detail);detail.addEventListener('click',()=>review.openRequest(key));
 function reflect(){
  const state=review.status(key),locked=review.isLocked(key);
  input.readOnly=locked;
  form.querySelector('[value=draft]').disabled=locked;
  form.querySelector('[value=submit]').textContent=locked?'承認状況を確認':'承認確認へ進む';
  status.textContent=state==='draft'?(saved.trim()?'反省の下書き保存済み':'反省未入力'):'反省：'+review.label(key);
  detail.hidden=state==='draft';
  document.querySelector('[data-daily-print-reflection]').textContent=input.value.trim()||'未入力';
 }
 function reset(){
  clearTimeout(timer);mode=parentWindow.AnnualMock.mode();
  saved=['partial','filled','approved','request-error'].includes(mode)?sample:'';input.value=saved;reflect();message.textContent='日案の反省と承認の見本です。入力・保存・承認依頼はこの画面内だけの動作です。';
 }
 function saveDraft(){
  if(mode==='error')throw new Error('下書きを保存できませんでした。入力は残っています。（確認用のエラー）');
  saved=input.value;reflect();
 }
 input.addEventListener('input',()=>{
  document.querySelector('[data-daily-print-reflection]').textContent=input.value||'未入力';
  clearTimeout(timer);status.textContent='反省の下書きを保存中';
  timer=setTimeout(()=>{try{saveDraft();message.textContent='下書きを保存しました。管理者への通知はまだありません。';}catch(error){message.textContent=error.message;status.textContent='反省の下書き保存エラー';}},1200);
 });
 form.addEventListener('submit',event=>{
  event.preventDefault();clearTimeout(timer);
  if(event.submitter?.value==='submit'&&review.isLocked(key)){review.openRequest(key);return;}
  if(event.submitter?.value==='submit'&&!input.value.trim()){message.textContent='反省を入力してください。';return;}
  try{
   saveDraft();
   if(event.submitter?.value==='draft'){message.textContent='下書きを保存しました。管理者への通知はまだありません。';return;}
   review.openConfirmation({key,kind:'daily',origin:'daily',title:'2026-10-01 日案の振り返り（ことり組）',meta:'見本保育園 / ことり組（0歳児） / 担任：見本の保育士',columns:['その日の振り返り'],values:[saved]});
  }catch(error){message.textContent=error.message;}
 });
 document.addEventListener('submit',event=>{event.preventDefault();if(event.target!==form)message.textContent='この見本では既存の年案・日案の本文や実施変更は保存しません。反省の承認フローをお試しください。';});
 document.addEventListener('click',event=>{
  if(event.target.closest('[data-day-print]')){window.print();return;}
  const anchor=event.target.closest('a');if(anchor&&anchor!==jump){event.preventDefault();message.textContent='画面遷移は確認用の見本です。本番への接続はありません。';}
 });
 window.addEventListener('message',event=>{if(event.origin!==location.origin||event.source!==parentWindow)return;if(event.data.kind==='daily-preview-reset')reset();if(event.data.kind==='reflection-review-updated')reflect();});
 const resize=()=>parentWindow.postMessage({kind:'daily-preview-height',height:Math.ceil(document.querySelector('main').getBoundingClientRect().height)+16},location.origin);
 new ResizeObserver(resize).observe(document.querySelector('main'));document.fonts.ready.then(resize);reset();
 window.DailyReflectionMock={state:()=>({body:input.value,saved,planStatus:'承認済み',reviewStatus:review.status(key)})};
})();
