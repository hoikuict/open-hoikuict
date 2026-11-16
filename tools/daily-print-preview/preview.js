(() => {
 const frame=document.getElementById('preview'),state=document.getElementById('state'),stage=document.querySelector('.stage');
 let view='compact';const drafts=new Map();
 function remember(){const area=frame.contentDocument?.querySelector('[name=reflection_body]');if(area)drafts.set(frame.dataset.state||'empty',area.value);}
 function load(){frame.style.height='1px';frame.dataset.state=state.value;frame.src=state.value+'.html?view='+view;stage.className='stage '+view;
  document.querySelectorAll('[data-view]').forEach(b=>b.setAttribute('aria-pressed',String(b.dataset.view===view)));
  document.getElementById('view-description').textContent=view==='screen'?'現在の入力項目を残した業務画面です。振り返りの入力や模擬提出も試せます。':view==='original'?'現行の余白・改行を再現した印刷です。比較用の架空データを使用しています。':'本文・4列・振り返り・実施変更を残し、余白だけを整理しています。';
 }
 document.querySelectorAll('[data-view]').forEach(b=>b.addEventListener('click',()=>{remember();view=b.dataset.view;load();}));
 state.addEventListener('change',()=>{remember();load();});document.getElementById('reset').addEventListener('click',()=>{drafts.delete(state.value);load();});
 frame.addEventListener('load',()=>{const area=frame.contentDocument.querySelector('[name=reflection_body]');if(drafts.has(state.value)){area.value=drafts.get(state.value);area.dispatchEvent(new Event('input'));}});
 window.addEventListener('message',event=>{
  if(event.origin!==location.origin||event.source!==frame.contentWindow||event.data.kind!=='daily-print-size')return;
  frame.style.height=event.data.height+'px';
  const pages=Math.max(1,Math.ceil((event.data.height-1)/(277*96/25.4)));
  document.getElementById('page-status').textContent=view==='screen'?'業務画面の入力を確認':view==='compact'?'A4 '+pages+'ページ相当 · 本文10pt':'現行レイアウト · 約'+pages+'ページ分の高さ';
 });
 document.getElementById('print').addEventListener('click',()=>frame.contentWindow.print());
})();
