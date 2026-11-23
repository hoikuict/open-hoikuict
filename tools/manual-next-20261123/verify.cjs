const fs = require('fs'), path = require('path'), assert = require('assert');
const { chromium } = require('../../.local-dev/manual-update-20261123/node_modules/playwright');
const root = path.resolve(__dirname, '../..'), evidence = path.join(root,'.local-dev/manual-next-20261123');
const base = process.argv[2] || 'http://127.0.0.1:8165/';
const published = base.includes('/daily-20261123/');
const prefix = published ? (base.startsWith('https:')?'public-':'publication-local-') : '';
const origin = new URL(base).origin;
const pages = ['index','attendance-checks','attendance-times','emergency-parent','emergency-staff'];
const report = { pages: [], stateSwitches: 0, readingSteps: 0, localLinks: 0, errors: [] };
(async()=>{
 const browser = await chromium.launch({executablePath:'C:/Users/katet/AppData/Local/ms-playwright/chromium_headless_shell-1243/chrome-headless-shell-win64/chrome-headless-shell.exe'});
 try {
  const ctx = await browser.newContext({viewport:{width:1366,height:1000},locale:'ja-JP'});
  await ctx.route('**/*',r=>r.request().url().startsWith(origin+'/')?r.continue():r.abort());
  const page = await ctx.newPage(); page.on('pageerror',e=>report.errors.push(e.message));
  for(const width of [1366,390,320]) for(const slug of pages){
   await page.setViewportSize({width,height:1000});
   const response = await page.goto(base+slug+'.html'); assert(response.ok());
   assert.equal((await page.locator('.review-banner').innerText()).includes('未公開'),!published);
   assert.equal(await page.getByText('HPへ戻る',{exact:true}).count(),0);
   const size = ()=>page.locator('main p').first().evaluate(e=>parseFloat(getComputedStyle(e).fontSize));
   const initial = await size(); await page.locator('#font-toggle').click(); assert((await size())>initial);
   assert(!(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth+1)));
   await page.locator('#font-toggle').click(); assert.equal(await size(),initial);
   for(const button of await page.locator('[data-state]').all()){
    await button.click(); assert.equal(await button.getAttribute('aria-pressed'),'true'); report.stateSwitches++;
   }
   for(const image of await page.locator('figure img').all()){
    await image.evaluate(async e=>{e.loading='eager';await e.decode();});
    assert(await image.evaluate(e=>e.naturalWidth>0));
   }
   if(slug!=='index'){
    await page.locator('.image-link:visible').first().click();
    assert(await page.locator('#image-dialog').isVisible());
    assert(await page.locator('#image-dialog img').evaluate(e=>e.naturalWidth>0));
    await page.keyboard.press('Escape'); assert(!(await page.locator('#image-dialog').isVisible()));
    await page.locator('#reading-toggle').click();
    const count = await page.locator('.manual-step').count();
    for(let i=0;i<count;i++){
     assert.equal(await page.locator('.manual-step:visible').count(),1); report.readingSteps++;
     assert(await page.locator('#step-'+(i+1)).isVisible());
     if(i<count-1) await page.locator('#next-step').click();
    }
    await page.locator('.contents a').first().click(); assert(await page.locator('#step-1').isVisible());
    await page.locator('#reading-toggle').click(); assert.equal(await page.locator('.manual-step:visible').count(),count);
    await page.locator('.checklist input').first().check(); assert(await page.locator('.checklist input').first().isChecked());
   }
   assert(!(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth+1)));
   if(width===1366){
    const urls=await page.locator('a[href]').evaluateAll(es=>[...new Set(es.map(e=>e.href))]);
    for(const url of urls){
     if(url.includes('#'))continue;
     assert(url.startsWith(origin+'/'));
     assert((await ctx.request.get(url)).ok(),url); report.localLinks++;
    }
   }
   await page.evaluate(()=>scrollTo(0,0));
   if(width!==320)await page.screenshot({path:path.join(evidence,prefix+slug+'-'+width+'.png'),fullPage:false});
   report.pages.push({slug,width,images:await page.locator('figure img').count()});
  }
  report.passed=report.errors.length===0;
  fs.writeFileSync(path.join(evidence,prefix+'verification.json'),JSON.stringify(report,null,2));
  console.log(JSON.stringify({passed:report.passed,views:report.pages.length,stateSwitches:report.stateSwitches,readingSteps:report.readingSteps,links:report.localLinks,errors:report.errors}));
  assert(report.passed);
 }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exit(1);});
