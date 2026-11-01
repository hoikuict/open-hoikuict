const { chromium } = require('C:/Users/katet/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const root = process.cwd();
const output = path.join(root,'.local-dev/parent-guardian-prefill-verification');
const approved = {window:{}};
vm.runInNewContext(fs.readFileSync(path.join(root,'tools/parent-guardian-prefill-preview/fixtures.js'),'utf8'), approved);
(async()=>{
 const browser=await chromium.launch({headless:true,executablePath:'C:/Users/katet/AppData/Local/ms-playwright/chromium_headless_shell-1243/chrome-headless-shell-win64/chrome-headless-shell.exe'});
 const page=await browser.newPage({viewport:{width:1380,height:1000}});
 const errors=[],unexpected=[],writes=[],checks=[];
 page.on('pageerror',e=>errors.push(e.message));
 let accept=false;
 page.on('dialog',dialog=>accept?dialog.accept():dialog.dismiss());
 await page.route('**/*',async route=>{
   const request=route.request();const url=new URL(request.url());
   if(!['GET','HEAD'].includes(request.method())){writes.push(request.url());await route.abort();return;}
   if(url.hostname==='guardian-verification.invalid'&&/^\/(add|invite|new)-(empty|filled|error|review)$/.test(url.pathname)){
     await route.fulfill({contentType:'text/html; charset=utf-8',body:fs.readFileSync(path.join(output,url.pathname.slice(1)+'.html'),'utf8')});return;
   }
   if(url.hostname==='guardian-verification.invalid'&&url.pathname==='/static/js/parent-guardian-registration.js'){
     await route.fulfill({contentType:'text/javascript',body:fs.readFileSync(path.join(root,'static/js/parent-guardian-registration.js'),'utf8')});return;
   }
   if(url.hostname==='guardian-verification.invalid'&&url.pathname==='/approved'){
     await route.fulfill({contentType:'text/html; charset=utf-8',body:approved.window.ParentGuardianFixture.views.invite});return;
   }
   unexpected.push(request.url());await route.abort();
 });
 const shape=()=>page.locator('form input:not([type=hidden]),form textarea,form select').evaluateAll(nodes=>nodes.map(n=>({name:n.name,type:n.type,required:n.required,label:n.closest('label').textContent.trim().replace(/\s+/g,' ')})));
 try{
   await page.goto('https://guardian-verification.invalid/approved');
   const mock=await shape();
   for(const kind of ['add','invite','new']){
     await page.goto(`https://guardian-verification.invalid/${kind}-empty`);
     if(kind!=='new') assert.deepEqual(await shape(),mock);
     else assert.equal((await shape()).length,28);
     if(kind==='invite'){
       assert.equal(await page.locator('[name=g1_phone]').inputValue(),'09011112222');
       assert.equal(await page.locator('[name=g1_workplace]').inputValue(),'試験会社');
       assert.ok(await page.locator('.prefill-note').isVisible());
       await page.evaluate(()=>document.querySelector('form').addEventListener('submit',event=>{event.preventDefault();window.initialSubmission=Object.fromEntries(new FormData(event.target));}));
       await page.locator('form button[type=submit]').click();
       assert.equal(await page.evaluate(()=>window.initialSubmission.g1_phone),'09011112222');
       await page.locator('[name=g1_phone]').fill('');
     }else{
       assert.equal(await page.locator('[name=g1_phone]').inputValue(),'');
       assert.equal(await page.locator('.prefill-note').count(),0);
     }
     await page.locator('form button[type=submit]').click();
     assert.ok(await page.locator('form input:invalid').count()>0);
     await page.goto(`https://guardian-verification.invalid/${kind}-error`);
     assert.ok(await page.locator('[role=alert]').isVisible());
     assert.equal(await page.locator('[name=g1_workplace]').inputValue(),'検証会社');
     if(kind!=='new') assert.deepEqual(await shape(),mock);
     await page.goto(`https://guardian-verification.invalid/${kind}-filled`);
     await page.screenshot({path:path.join(output,`${kind}-desktop.png`),fullPage:true});
     await page.setViewportSize({width:390,height:844});
     assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));
     await page.screenshot({path:path.join(output,`${kind}-mobile.png`),fullPage:true});
     await page.setViewportSize({width:1380,height:1000});
     if(kind!=='new'){
       await page.locator('#cancel-guardian-registration').click();
       assert.equal(await page.locator('[name=g1_workplace]').inputValue(),'検証会社');
       await page.evaluate(()=>{
         document.querySelector('form').addEventListener('submit',event=>{
           event.preventDefault();window.submittedFields=[...new FormData(event.target).keys()];
         });
       });
       await page.locator('form button[type=submit]').click();
       assert.deepEqual(await page.evaluate(()=>window.submittedFields.filter(k=>k!=='csrf_token')),mock.map(f=>f.name));
       accept=true;await page.locator('#cancel-guardian-registration').click();accept=false;
       assert.equal(await page.locator('form').count(),0);
       assert.match(await page.locator('h1').innerText(),/入力を終了/);
     }
     checks.push({kind,fields:kind==='new'?28:9,required:kind==='new'?13:6,mockMatches:kind!=='new',mobile:390});
   }
   assert.deepEqual(errors,[]);assert.deepEqual(unexpected,[]);assert.deepEqual(writes,[]);
   fs.writeFileSync(path.join(output,'browser.json'),JSON.stringify({verified:true,checks,errors,unexpected,writes,allNetworkFulfilledLocally:true},null,2)+'\n');
   console.log(JSON.stringify({verified:true,checks,errors,unexpected,writes}));
 }finally{await browser.close();}
})().catch(error=>{console.error(error);process.exitCode=1;});
