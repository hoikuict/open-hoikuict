(() => {
 const view=new URLSearchParams(location.search).get('view')||'compact';
 document.documentElement.dataset.view=view;
 const reflection=document.querySelector('[name=reflection_body]');
 const printReflection=document.createElement('p');printReflection.className='print-reflection';
 reflection.closest('label').after(printReflection);
 function updateReflection(){printReflection.textContent=reflection.value.trim()||'未入力';}
 updateReflection();reflection.addEventListener('input',updateReflection);
 document.querySelectorAll('.daily-reflection-panel .field-note').forEach(note=>{if(note.textContent.trim().startsWith('最終提出:'))note.classList.add('reflection-submitted-at');});
 if(view!=='original'){
  // Whitespace used to indent the Jinja template must not become printed blank lines.
  document.querySelectorAll('.schedule-table td').forEach(cell=>{
   const notes=[...cell.children];
   const text=[...cell.childNodes].filter(n=>n.nodeType===Node.TEXT_NODE).map(n=>n.textContent).join('').trim();
   const span=document.createElement('span');span.className='cell-body';span.textContent=text;
   cell.replaceChildren(span,...notes);
  });
  document.querySelectorAll('.report-section__footer').forEach(el=>{if(!el.textContent.trim())el.remove();});
 }
 // The proposed sheet uses exactly the same rules on screen and in browser printing.
 if(view!=='original'){
  const link=document.createElement('link');link.rel='stylesheet';link.href='compact.css';link.media=view==='screen'?'print':'all';document.head.append(link);
 }
 const pageStyle=document.createElement('style');pageStyle.textContent='@page{size:A4 portrait;margin:8mm}@media print{body{margin:0}.plan-docs-content{background:white}html[data-view=original] .plan-docs-content{padding:24px 32px}.no-print,.mock-message{display:none!important}}';document.head.append(pageStyle);
 const stamp=document.createElement('div');stamp.className='preview-stamp';stamp.textContent='印刷レイアウトの見本・架空データ';document.querySelector('main').prepend(stamp);
 const message=document.createElement('p');message.className='mock-message no-print';message.hidden=true;message.setAttribute('role','status');document.querySelector('main').prepend(message);
 if(location.pathname.endsWith('/error.html')){message.hidden=false;message.textContent='振り返りを入力してください。（入力エラーの表示例）';}
 document.addEventListener('submit',event=>{
  event.preventDefault();message.hidden=false;
  if(event.target.querySelector('[name=reflection_body]')&&!reflection.value.trim())message.textContent='振り返りを入力してください。（この見本では保存されません）';
  else message.textContent='入力内容を確認しました。見本のため、保存・提出は行いません。';
 });
 document.addEventListener('click',event=>{
  if(event.target.closest('[data-preview-print]')){window.print();return;}
  if(event.target.closest('a')){event.preventDefault();message.hidden=false;message.textContent='印刷確認用の見本です。画面の移動・本番データの変更はありません。';}
 });
 const report=()=>parent.postMessage({kind:'daily-print-size',height:Math.ceil(document.querySelector('main').getBoundingClientRect().height),view},location.origin);
 document.fonts.ready.then(report);window.addEventListener('load',report);new ResizeObserver(report).observe(document.querySelector('main'));
})();
