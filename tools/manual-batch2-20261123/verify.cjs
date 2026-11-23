const fs=require('fs'),path=require('path'),assert=require('assert');
const {chromium}=require('../../.local-dev/manual-update-20261123/node_modules/playwright');
const root=path.resolve(__dirname,'../..'),evidence=path.join(root,'.local-dev/manual-batch2-20261123'),base=process.argv[2]||'http://127.0.0.1:8166/';
const published=base.includes('/staff-records-20261123/'),prefix=published?(base.startsWith('https:')?'public-':'publication-local-'):'';
const report={views:[],details:0,images:0,links:0,errors:[]};
(async()=>{
 const browser=await chromium.launch({executablePath:'C:/Users/katet/AppData/Local/ms-playwright/chromium_headless_shell-1243/chrome-headless-shell-win64/chrome-headless-shell.exe'});
 try{
  const ctx=await browser.newContext();const page=await ctx.newPage();page.on('pageerror',e=>report.errors.push(e.message));
  await ctx.route('**/*',r=>r.request().url().startsWith(new URL(base).origin+'/')?r.continue():r.abort());
  for(const width of [1366,390,320])for(const slug of ['index','home','attention','progress','entry','review-request']){
   await page.setViewportSize({width,height:1000});assert((await page.goto(base+slug+'.html')).ok());
   assert.equal((await page.locator('header').innerText()).includes('未公開'),!published);assert.equal(await page.getByText('HPへ戻る',{exact:true}).count(),0);
   const size=()=>page.locator('.intro').evaluate(e=>parseFloat(getComputedStyle(e).fontSize));const before=await size();
   await page.locator('#font-toggle').click();assert((await size())>before);assert(!(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth+1)));
   await page.locator('#font-toggle').click();assert.equal(await size(),before);
   for(const details of await page.locator('details').all()){await details.locator('summary').click();assert(await details.getAttribute('open')!==null);report.details++;}
   for(const img of await page.locator('main img').all()){await img.evaluate(e=>e.decode());assert(await img.evaluate(e=>e.naturalWidth===+e.getAttribute('width')&&e.naturalHeight===+e.getAttribute('height')));report.images++;}
   if(slug!=='index'){await page.locator('.image-link').first().click();assert(await page.locator('dialog').isVisible());await page.locator('dialog img').evaluate(e=>e.decode());await page.keyboard.press('Escape');assert(!(await page.locator('dialog').isVisible()));}
   assert(!(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth+1)),slug+' '+width);
   if(width===1366)for(const url of await page.locator('a[href]').evaluateAll(a=>[...new Set(a.map(x=>x.href.split('#')[0]))])){assert((await ctx.request.get(url)).ok());report.links++;}
   await page.evaluate(()=>scrollTo(0,0));if(width!==320)await page.screenshot({path:path.join(evidence,prefix+slug+'-'+width+'.png')});
   report.views.push({slug,width});
  }
  report.passed=report.errors.length===0;fs.writeFileSync(path.join(evidence,prefix+'verification.json'),JSON.stringify(report,null,2));console.log(JSON.stringify({...report,views:report.views.length}));assert(report.passed);
 }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exit(1);});
