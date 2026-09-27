  const outputActions = document.createElement('span');
  outputActions.style.display='contents';
  outputActions.innerHTML='<button type="button" id="print-monthly">印刷用PDF</button><button type="button" id="excel-monthly">Excel出力</button>';
  q('.actions').prepend(outputActions);
  q('.actions').insertAdjacentHTML('beforeend','<small class="export-note">対象の月・年齢の全園児を出力。保存前の入力も含みます。</small>');
  let exporting = false;
  async function exportMonthly(kind) {
    if (exporting) return;
    commitEdit();
    const snapshot=clone(ctx());
    const popup=kind==='pdf'?window.open('about:blank','_blank'):null;
    exporting=true;q('#print-monthly').disabled=q('#excel-monthly').disabled=true;
    announce(kind==='pdf'?'印刷用PDFを作成しています…':'Excelファイルを作成しています…');
    try {
      const token=document.querySelector('meta[name="csrf-token"]')?.content || '';
      const data=await api('preview-export',{method:'POST',headers:{'Content-Type':'application/json','X-CSRF-Token':token},
        body:JSON.stringify({kind,context:snapshot})});
      if (popup) popup.location.href=data.url;
      else {
        const link=document.createElement('a');link.href=data.url;
        if(kind==='pdf') {link.target='_blank';link.rel='noopener';}
        else link.download='';
        document.body.append(link);link.click();link.remove();
      }
      announce(`${kind==='pdf'?'印刷用PDF':'Excel'}を出力しました（${data.pages}ページ）。現在の入力を使い、帳票の保存はしていません。`);
    } catch(error) {if(popup)popup.close();announce(error.message,true);}
    finally {exporting=false;q('#print-monthly').disabled=q('#excel-monthly').disabled=false;}
  }
  q('#print-monthly').addEventListener('click',()=>exportMonthly('pdf'));
  q('#excel-monthly').addEventListener('click',()=>exportMonthly('xlsx'));
  // The saved-document page's existing Print button uses the same complete output.
  const documentPrintButton=document.querySelector('button[onclick="window.print()"]');
  if(documentPrintButton) documentPrintButton.onclick=()=>exportMonthly('pdf');

  // Direct browser printing also uses plain text, all roster pages and no application chrome.
  window.addEventListener('beforeprint',()=>{
    commitEdit();document.querySelector('#monthly-print-root')?.remove();
    const printRoot=document.createElement('div');printRoot.id='monthly-print-root';
    const oldPage=current.page;
    const paperPages=[];
    if(individual()) {
      for(let i=0;i<pages().length;i++) {
        current.page=i;
        paperPages.push(head()+common(['common:goal','common:home','common:review'])+roster());
      }
    } else paperPages.push(group());
    current.page=oldPage;
    printRoot.innerHTML=paperPages.map((html,i)=>`<section class="print-sheet">${html}<p class="print-footer">操作見本（架空データ） ${i+1} / ${paperPages.length}</p></section>`).join('');
    printRoot.querySelectorAll('textarea').forEach(el=>{
      const text=document.createElement('div');text.className='print-text';text.textContent=body(el.dataset.cell);el.replaceWith(text);
    });
    printRoot.querySelectorAll('input').forEach(el=>{
      const text=document.createElement('div');text.className='print-text';text.textContent=el.value;el.replaceWith(text);
    });
    document.body.append(printRoot);
  });
  window.addEventListener('afterprint',()=>document.querySelector('#monthly-print-root')?.remove());
