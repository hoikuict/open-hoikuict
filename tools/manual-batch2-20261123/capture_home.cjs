const fs=require('fs'), path=require('path'),assert=require('assert');
const {chromium}=require('../../.local-dev/manual-update-20261123/node_modules/playwright');
const root=path.resolve(__dirname,'../..'), fixtures=path.join(root,'.local-dev/manual-batch2-20261123/capture'), out=path.join(__dirname,'review');
const results=[];
(async()=>{
 const browser=await chromium.launch({executablePath:'C:/Users/katet/AppData/Local/ms-playwright/chromium_headless_shell-1243/chrome-headless-shell-win64/chrome-headless-shell.exe'});
 try{
  const page=await browser.newPage({viewport:{width:500,height:1000}});
  await page.route('**/*',async r=>{const u=new URL(r.request().url());if(u.origin!=='http://manual.test')return r.abort();const file=path.join(fixtures,path.basename(u.pathname));if(!fs.existsSync(file))return r.abort();return r.fulfill({path:file,contentType:file.endsWith('.js')?'text/javascript':'text/html; charset=utf-8'});});
  async function load(name,width=500){await page.setViewportSize({width,height:1000});await page.goto('http://manual.test/'+name+'.html');await page.evaluate(()=>document.fonts.ready);}
  async function snap(name,locator){
   assert.equal(await locator.count(),1,name);await locator.scrollIntoViewIfNeeded();
   const box=await locator.boundingBox(),pos=await page.evaluate(()=>({x:scrollX,y:scrollY}));
   const pad=['home-shortcuts.jpg','attention-entry.jpg'].includes(name)?34:6;
   const x=Math.max(0,Math.floor(box.x+pos.x-pad)),y=Math.max(0,Math.floor(box.y+pos.y-pad));
   const right=Math.min(page.viewportSize().width,Math.ceil(box.x+pos.x+box.width+pad));
   await page.screenshot({path:path.join(out,name),fullPage:true,clip:{x,y,width:right-x,height:Math.ceil(box.y+pos.y+box.height+pad)-y},...(name.endsWith('.jpg')?{quality:93}:{})});results.push(name);
  }
  const hero=()=>page.locator('main section').first();
  const section=title=>page.getByRole('heading',{name:title,exact:true}).locator('xpath=ancestor::section[1]');
  await load('capture-home-location');await snap('staff-home-detail.png',hero());
  await load('capture-home-location',1265);await snap('staff-home-overview.jpg',hero());
  await load('capture-home-everyday',1265);await snap('home-location.jpg',hero());
  await load('capture-home-everyday');
  await snap('home-shortcuts.jpg',hero().locator('a[href="/staff/attention"]').locator('..'));
  await snap('home-update.jpg',hero().getByText('最終更新',{exact:false}).locator('..'));
  for(const [name,title] of [['home-attendance.jpg','担当クラスの出欠確認'],['home-schedule.jpg','今日の予定'],['home-timeline.jpg','連絡タイムライン'],['home-attention-card.jpg','要確認'],['home-quick.jpg','よく使う機能']])await snap(name,section(title));
  await load('capture-home-documents');await snap('home-return.jpg',section('差し戻しがあります'));await snap('home-document.jpg',section('計画文書・児童票の通知'));
  await load('capture-home-admin');await snap('home-approvals.jpg',section('すべての承認待ち'));await snap('home-terminal.jpg',page.getByText('保護者端末の接続状況',{exact:true}));
  await load('capture-attention-home');await snap('attention-entry.jpg',hero().locator('a[href="/staff/attention"]'));
  await load('capture-attention-list');await snap('attention-summary.jpg',hero());await snap('attention-list.png',page.locator('main section').nth(1));
  await load('capture-attention-empty');await snap('attention-empty.jpg',page.locator('main'));
  await load('capture-attention-admin');await snap('attention-scope.jpg',page.locator('a[href="/staff/attention?scope=assigned"]').locator('..'));
  await load('capture-progress-list',1265);
  const menu=page.locator('aside a[href="/child-records/progress"]').locator('..').locator('..');
  await snap('progress-menu.jpg',menu);
  await load('capture-progress-list',1000);await snap('progress-rows.jpg',page.locator('main table'));
  await load('capture-progress-list',390);await snap('progress-period.jpg',page.locator('[aria-label="対象期間の選択"]'));
  await load('capture-progress-filter',390);await snap('progress-filter.jpg',page.locator('select[name="status"]').locator('xpath=ancestor::section[1]'));
  await load('capture-progress-empty',390);await snap('progress-empty.jpg',page.locator('main'));
  fs.writeFileSync(path.join(root,'.local-dev/manual-batch2-20261123/capture-home.json'),JSON.stringify({passed:true,images:results},null,2));console.log(JSON.stringify({passed:true,images:results.length}));
 }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exit(1);});
