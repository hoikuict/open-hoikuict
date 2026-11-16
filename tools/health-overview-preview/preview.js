'use strict';
const screen = document.querySelector('#business-screen');
const scenario = document.querySelector('#scenario');
const dialog = document.querySelector('#preview-detail');
const fields = ['status','attention','classroom_id','q'];
let layout = 'proposed';
let filters = {status:'enrolled',attention:'all',classroom_id:'',q:''};

function applyFilters(){
  const rows = [...screen.querySelectorAll('tbody tr[data-status]')];
  const q = filters.q.trim().toLocaleLowerCase();
  rows.forEach(row=>{
    const identity = row.cells[0].textContent+' '+row.cells[1].textContent;
    row.hidden = !((filters.status==='all'||row.dataset.status===filters.status)
      &&(filters.attention==='all'||row.dataset.attention==='true')
      &&(!filters.classroom_id||row.dataset.classroom===filters.classroom_id)
      &&(!q||identity.toLocaleLowerCase().includes(q)));
  });
  const shown = rows.filter(row=>!row.hidden);
  [shown.length,shown.filter(r=>r.dataset.attention==='true').length,shown.filter(r=>r.dataset.priority==='true').length,shown.filter(r=>r.dataset.expired==='true').length].forEach((value,i)=>screen.querySelector(`[data-count="${i}"]`).textContent=value);
  screen.querySelector('[data-empty-result]')?.remove();
  if(!shown.length){
    const row = document.createElement('tr');row.dataset.emptyResult='';
    const cell = document.createElement('td');cell.colSpan=7;cell.className='px-4 py-12 text-center text-sm text-slate-400';cell.textContent='該当する園児がありません。';row.append(cell);screen.querySelector('tbody').append(row);
  }
}

function loadScenario(){
  const isError = scenario.value==='error';
  screen.hidden=isError;document.querySelector('#load-error').hidden=!isError;
  if(isError)return;
  screen.replaceChildren(document.querySelector('#scenario-'+scenario.value).content.cloneNode(true));
  screen.className=layout;
  screen.querySelector('.health-scroll').id='list-anchor';
  fields.forEach(name=>screen.querySelector(`[name="${name}"]`).value=filters[name]);
  applyFilters();
}

document.querySelectorAll('[data-layout]').forEach(button=>button.addEventListener('click',()=>{
  layout=button.dataset.layout;screen.className=layout;
  document.querySelectorAll('[data-layout]').forEach(b=>b.setAttribute('aria-pressed',String(b===button)));
  document.querySelector('#layout-note').textContent=layout==='proposed'?'操作欄まで画面幅に収め、狭い画面では園児ごとに全項目と操作をまとめて表示します。':'配備記録のテンプレートから再現した配置です。架空の同じデータで比較できます。';
}));
scenario.addEventListener('change',loadScenario);
document.querySelector('#retry').addEventListener('click',()=>{scenario.value='filled';loadScenario();});
document.querySelector('#jump-list').addEventListener('click',event=>{event.preventDefault();screen.querySelector('.health-scroll')?.focus();screen.querySelector('.health-scroll')?.scrollIntoView({block:'start'});});
screen.addEventListener('submit',event=>{
  event.preventDefault();
  const data=new FormData(event.target);fields.forEach(name=>filters[name]=data.get(name)||'');applyFilters();
});
screen.addEventListener('click',event=>{
  const link=event.target.closest('[data-original-route]');if(!link)return;event.preventDefault();
  if(link.dataset.originalRoute==='/health'){
    filters={status:'enrolled',attention:'all',classroom_id:'',q:''};fields.forEach(name=>screen.querySelector(`[name="${name}"]`).value=filters[name]);applyFilters();return;
  }
  document.querySelector('#detail-title').textContent=link.textContent;
  const content=document.querySelector('#detail-content');content.replaceChildren();
  const row=link.closest('tr');
  if(row){
    const labels=['園児','クラス','健康フラグ','アレルギー','最新測定','健診状態'];
    const dl=document.createElement('dl');
    labels.forEach((label,index)=>{const group=document.createElement('div');group.className='detail-row';const dt=document.createElement('dt');dt.textContent=label;const dd=document.createElement('dd');dd.textContent=row.cells[index].textContent.replace(/\s+/g,' ').trim();group.append(dt,dd);dl.append(group);});content.append(dl);
  }else{content.textContent='園児一覧へ移動する入口です。今回の変更対象は健康管理一覧の配置です。';}
  document.querySelector('#detail-route').textContent='実装時の遷移先：'+link.dataset.originalRoute;
  dialog.showModal();
});
document.querySelector('#close-detail').addEventListener('click',()=>dialog.close());
loadScenario();
