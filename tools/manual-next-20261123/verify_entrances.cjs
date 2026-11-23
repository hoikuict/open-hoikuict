const fs = require('fs'),path = require('path'),assert = require('assert');
const { chromium } = require('../../.local-dev/manual-update-20261123/node_modules/playwright');
const base = process.argv[2];
if(!base) throw new Error('Specify the guide URL');
const root=path.resolve(__dirname,'../..'), publicSite=base.startsWith('https:');
const names=['attendance-checks','attendance-times','emergency-parent','emergency-staff'];
const report={base,routes:[],searches:[],errors:[]};
(async()=>{
 const browser=await chromium.launch({executablePath:'C:/Users/katet/AppData/Local/ms-playwright/chromium_headless_shell-1243/chrome-headless-shell-win64/chrome-headless-shell.exe'});
 try{
  const page=await browser.newPage({viewport:{width:1366,height:900}});
  page.on('pageerror',e=>report.errors.push(e.message));
  for(const [hash,slugs] of [['home',names],['chapter/1',names.slice(0,2)],['chapter/2',names.slice(2)],['parent-app',['emergency-parent']]]){
   await page.goto(base+'#'+hash);
   for(const slug of slugs)assert(await page.locator(`#main a[href="daily-20261123/${slug}.html"]`).count(),hash+' '+slug);
   assert.equal(await page.getByText('HPへ戻る',{exact:true}).count(),0);
   report.routes.push({hash,slugs});
  }
  for(const [q,slug] of [['電話 取消','attendance-checks'],['時刻 修正','attendance-times'],['保護者 緊急連絡先','emergency-parent'],['口頭 履歴','emergency-staff']]){
   await page.goto(base+'#search/'+encodeURIComponent(q));
   assert(await page.locator(`#main a[href="daily-20261123/${slug}.html"]`).count(),q);
   report.searches.push(q);
  }
  for(const width of [1366,390,320]){
   await page.setViewportSize({width,height:900});await page.goto(base+'#parent-app');
   const size=()=>page.locator('#main .lead').evaluate(e=>parseFloat(getComputedStyle(e).fontSize));
   const initial=await size();await page.locator('#font-toggle').click();assert((await size())>initial);
   assert(!(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth+1)));
   await page.locator('#font-toggle').click();assert.equal(await size(),initial);
   await page.screenshot({path:path.join(root,`.local-dev/manual-next-20261123/${publicSite?'public':'local'}-parent-entry-${width}.png`)});
  }
  report.passed=report.errors.length===0;assert(report.passed);
  fs.writeFileSync(path.join(root,`.local-dev/manual-next-20261123/${publicSite?'public':'local'}-entrances.json`),JSON.stringify(report,null,2));
  console.log(JSON.stringify(report));
 }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exit(1);});
