const {chromium}=require('C:/Users/katet/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright');
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path');
const previewUrl=require('node:url').pathToFileURL(path.join(__dirname,'index.html')).href;
(async()=>{
 const browser=await chromium.launch({headless:true,executablePath:'C:/Users/katet/AppData/Local/ms-playwright/chromium_headless_shell-1243/chrome-headless-shell-win64/chrome-headless-shell.exe'});
 const context=await browser.newContext({viewport:{width:1366,height:900}}),page=await context.newPage();
 const errors=[],requests=[],checks=[],metrics={};
 const check=(name,ok)=>{assert.ok(ok,name);checks.push(name);};
 page.on('pageerror',e=>errors.push(e.message));
 await context.route('**/*',r=>{const u=new URL(r.request().url());if(u.href.startsWith(previewUrl.slice(0,previewUrl.lastIndexOf('/')+1))&&r.request().method()==='GET')return r.continue();requests.push(u.href);return r.abort();});
 try{
  const response=await page.goto(previewUrl);check('Preview opens successfully',response.ok());
  await page.waitForFunction(()=>getComputedStyle(document.querySelector('.health-table')).tableLayout==='fixed');
  const visibleRows=()=>page.locator('tbody tr[data-status]:visible');
  check('All four existing filters preserved',await page.locator('#health-filters input,#health-filters select').count()===4);
  check('All seven columns preserved',await page.locator('th').count()===7);
  check('Enrolled default has 16 rows',await visibleRows().count()===16);
  const measure=()=>page.locator('table').evaluate(t=>({width:t.getBoundingClientRect().width,height:t.getBoundingClientRect().height,columns:[...t.querySelectorAll('th')].map(e=>Math.round(e.getBoundingClientRect().width)),rowHeight:t.querySelector('tbody tr').getBoundingClientRect().height}));
  metrics.proposed=await measure();
  await page.screenshot({path:path.join(__dirname,'proposed-r2-desktop.png'),fullPage:true});
  await page.locator('.health-scroll').screenshot({path:path.join(__dirname,'proposed-r2-table.png')});
  const content=await page.locator('tbody').innerText();
  await page.locator('[data-layout=current]').click();metrics.current=await measure();
  check('Layout change preserves table contents',await page.locator('tbody').innerText()===content);
  await page.locator('.health-scroll').screenshot({path:path.join(__dirname,'current-r2-table.png')});
  await page.locator('[data-layout=proposed]').click();
  check('Allergy column narrowed',metrics.proposed.columns[3]<metrics.current.columns[3]);
  check('Ordinary row is shorter',metrics.proposed.rowHeight<metrics.current.rowHeight);
  await page.locator('[name=status]').selectOption('all');await page.getByRole('button',{name:'絞り込む',exact:true}).click();check('Status filter includes 18 rows',await visibleRows().count()===18);
  await page.locator('[name=classroom_id]').selectOption('2');await page.getByRole('button',{name:'絞り込む',exact:true}).click();check('Class filter shows six',await visibleRows().count()===6);
  await page.locator('[name=attention]').selectOption('needs_attention');await page.getByRole('button',{name:'絞り込む',exact:true}).click();check('Attention filter shows one',await visibleRows().count()===1);
  await page.getByRole('link',{name:'リセット',exact:true}).click();
  await page.locator('[name=q]').fill('青空');await page.getByRole('button',{name:'絞り込む',exact:true}).click();check('Search by child or family',await visibleRows().count()===1);
  await page.locator('[name=q]').fill('見つからない名前');await page.getByRole('button',{name:'絞り込む',exact:true}).click();check('No-match message',await page.getByText('該当する園児がありません。',{exact:true}).isVisible());check('Summary follows filters',await page.locator('[data-count="0"]').innerText()==='0');
  await page.getByRole('link',{name:'リセット',exact:true}).click();
  await page.getByRole('link',{name:'基本医療情報の回答を確認',exact:true}).click();check('Deployment-only medical entry retained',await page.locator('dialog').isVisible());check('Original destination retained',(await page.locator('#detail-route').innerText()).includes('/children/11/health/parent-medical'));
  await page.keyboard.press('Escape');check('Escape closes detail mock',!await page.locator('dialog').isVisible());
  await page.getByRole('link',{name:'健康サマリー',exact:true}).first().click();check('Child snapshot in detail',(await page.locator('#detail-content').innerText()).includes('青空 はる'));await page.getByRole('button',{name:'閉じる',exact:true}).click();
  await page.locator('#scenario').selectOption('empty');check('Unregistered measurement scenario',await visibleRows().first().locator('td').nth(4).innerText()==='未登録');
  await page.locator('#scenario').selectOption('partial');check('Height-only scenario',(await visibleRows().first().locator('td').nth(4).innerText()).includes('cm')&&!(await visibleRows().first().locator('td').nth(4).innerText()).includes('kg'));
  await page.locator('#scenario').selectOption('error');check('Error and retry',await page.locator('#load-error').isVisible());await page.getByRole('button',{name:'再読み込み',exact:true}).click();check('Retry returns to mock rows',await visibleRows().count()===16);
  check('Long allergy text and additional count preserved',(await page.locator('tbody').innerText()).includes('加工食品に含まれる場合も確認')&&(await page.locator('tbody').innerText()).includes('ほか 2 件'));
  for(const width of [1024,847,768,720,719,390,320]){
    await page.setViewportSize({width,height:900});
    check('No page overflow at '+width,await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));
    const region=page.locator('.health-scroll');
    check('No table scroll needed at '+width,await region.evaluate(e=>e.scrollWidth<=e.clientWidth));
    check('Every action fits horizontally at '+width,await page.locator('tbody tr[data-status]:visible td:last-child a').evaluateAll(links=>links.every(a=>{const r=a.getBoundingClientRect();return r.width>0&&r.left>=0&&r.right<=innerWidth;})));
    if(width===390)await page.screenshot({path:path.join(__dirname,'proposed-r2-mobile.png'),fullPage:true});
  }
  await page.setViewportSize({width:1366,height:900});await page.emulateMedia({media:'print'});
  check('Print hides mock controls',!await page.locator('.preview-controls').isVisible());check('Print hides action links',!await page.getByRole('link',{name:'健康サマリー',exact:true}).first().isVisible());
  check('No JavaScript exceptions',errors.length===0);check('No external or mutation requests',requests.length===0);
  fs.writeFileSync(path.join(__dirname,'verification-r2-automated.json'),JSON.stringify({checks,metrics,errors,blockedRequests:requests},null,2));
  console.log(JSON.stringify({passed:checks.length,metrics}));
 }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});
