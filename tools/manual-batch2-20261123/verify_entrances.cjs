const fs=require('fs'),path=require('path'),assert=require('assert');
const {chromium}=require('../../.local-dev/manual-update-20261123/node_modules/playwright');
const base=process.argv[2];if(!base)throw new Error('Specify the guide URL');
const root=path.resolve(__dirname,'../..'),evidence=path.join(root,'.local-dev/manual-batch2-20261123');
const prefix=base.startsWith('https:')?'public-':'local-';
const names=['home','attention','progress','entry','review-request'];
const report={base,routes:[],searches:[],errors:[]};
(async()=>{
 const browser=await chromium.launch({executablePath:'C:/Users/katet/AppData/Local/ms-playwright/chromium_headless_shell-1243/chrome-headless-shell-win64/chrome-headless-shell.exe'});
 try{
  const page=await browser.newPage({viewport:{width:1366,height:900}});page.on('pageerror',e=>report.errors.push(e.message));
  for(const [route,slugs] of [['home',names],['chapter/1',['attention']],['chapter/2',names.slice(2)],['chapter/4',['home']]]){
   await page.goto(base+'#'+route);
   for(const slug of slugs)assert(await page.locator(`#main a[href="staff-records-20261123/${slug}.html"]`).count(),route+' '+slug);
   assert.equal(await page.getByText('HPへ戻る',{exact:true}).count(),0);
   if(route==='home')for(const old of ['attendance-checks','attendance-times','emergency-parent','emergency-staff'])assert(await page.locator(`#main a[href="daily-20261123/${old}.html"]`).count(),old);
   report.routes.push({route,slugs});
  }
  for(const [query,slug] of [['職員 ホーム','home'],['要確認 アンケート','attention'],['児童票 未作成','progress'],['児童票 入力','entry'],['児童票 取り下げ','review-request']]){
   await page.goto(base+'#search/'+encodeURIComponent(query));assert(await page.locator(`#main a[href="staff-records-20261123/${slug}.html"]`).count(),query);report.searches.push(query);
  }
  for(const width of [1366,390,320]){
   await page.setViewportSize({width,height:900});await page.goto(base+'#chapter/2');
   const size=()=>page.locator('#main .lead').evaluate(e=>parseFloat(getComputedStyle(e).fontSize));const before=await size();
   await page.locator('#font-toggle').click();assert((await size())>before);assert(!(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth+1)));
   await page.locator('#font-toggle').click();assert.equal(await size(),before);
   await page.screenshot({path:path.join(evidence,prefix+'chapter-2-'+width+'.png')});
  }
  report.passed=report.errors.length===0;assert(report.passed);fs.writeFileSync(path.join(evidence,prefix+'entrances.json'),JSON.stringify(report,null,2));console.log(JSON.stringify(report));
 }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exit(1);});
