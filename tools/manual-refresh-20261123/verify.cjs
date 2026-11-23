const fs=require('fs'),path=require('path'),assert=require('assert');
const {chromium}=require('../../.local-dev/manual-update-20261123/node_modules/playwright');
const root=path.resolve(__dirname,'../..'),dir=path.join(root,'.local-dev/manual-refresh-20261123');
const base=process.argv[2]||'http://127.0.0.1:8164/manual-guide-preview/',publicRun=base.startsWith('https:'),report={base,pages:[],errors:[],states:[],search:[]};
const routes=['index.html#article/parent-app-contact','index.html#article/parent-app-pickup','index.html#article/parent-app-history','health/index.html','health/profile/index.html','refresh-20261123/index.html','refresh-20261123/daily-contact.html','refresh-20261123/medical.html','refresh-20261123/billing.html'];
(async()=>{
 const browser=await chromium.launch({executablePath:'C:/Users/katet/AppData/Local/ms-playwright/chromium_headless_shell-1243/chrome-headless-shell-win64/chrome-headless-shell.exe'});
 try{
  const p=await browser.newPage();p.setDefaultTimeout(15000);p.on('pageerror',e=>report.errors.push(e.message));
  for(const width of [1366,390,320]){
   await p.setViewportSize({width,height:900});
   for(const route of routes){
    const response=await p.goto(base+route);if(response)assert(response.ok());await p.locator('h1').waitFor();
    const all=p.getByRole('button',{name:'まとめて読む',exact:true});if(await all.count())await all.click();
    await p.evaluate(()=>{for(const im of document.images)im.loading='eager';});await p.waitForFunction(()=>[...document.images].filter(x=>x.getAttribute('src')).every(x=>x.complete&&x.naturalWidth>0));
    const overflow=await p.evaluate(()=>document.documentElement.scrollWidth>innerWidth+1);assert(!overflow,route+' width '+width);
    assert.equal(await p.getByRole('link',{name:'HPへ戻る',exact:true}).count(),0);
    if(route.includes('#article/')){
     const button=p.getByRole('button',{name:'文字を大きく',exact:true});const before=await p.locator('html').evaluate(x=>parseFloat(getComputedStyle(x).fontSize));await button.click();const after=await p.locator('html').evaluate(x=>parseFloat(getComputedStyle(x).fontSize));assert(after>before);await p.getByRole('button',{name:'文字を標準に',exact:true}).click();
     for(const select of await p.locator('[data-state-step]').all())for(const value of await select.locator('option').evaluateAll(xs=>xs.map(x=>x.value))){await select.selectOption(value);await p.waitForFunction(()=>[...document.images].filter(x=>x.getAttribute('src')).every(x=>x.complete&&x.naturalWidth>0));report.states.push([width,route,value]);}
     await p.locator('[data-zoom]').first().click();await p.locator('#image-dialog[open]').waitFor();await p.waitForFunction(()=>document.querySelector('#zoom-image').naturalWidth>0);await p.locator('#close-image').click();
    }
    if(width===390)await p.screenshot({path:path.join(dir,(publicRun?'public-':'local-')+route.replace(/[^a-z0-9]+/gi,'_')+'.png'),fullPage:false});
    report.pages.push({route,width,title:await p.locator('h1').innerText(),images:await p.locator('img').count(),overflow});
   }
  }
  for(const [term,href] of [['医療','refresh-20261123/medical.html'],['返信','refresh-20261123/daily-contact.html'],['取消','refresh-20261123/billing.html']]){await p.goto(base+'index.html#search/'+encodeURIComponent(term));await p.locator('main a[href="'+href+'"]').waitFor();report.search.push(term);}
  assert.deepStrictEqual(report.errors,[]);report.passed=true;
 }finally{fs.writeFileSync(path.join(dir,(publicRun?'public':'local')+'-verification.json'),JSON.stringify(report,null,2));await browser.close();}
 console.log(JSON.stringify({passed:report.passed,pages:report.pages.length,states:report.states.length,search:report.search,errors:report.errors}));
})().catch(e=>{console.error(e);process.exit(1)});
