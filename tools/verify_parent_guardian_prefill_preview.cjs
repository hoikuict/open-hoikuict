const {chromium}=require('C:/Users/katet/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright');
const fs=require('node:fs');
const path=require('node:path');
const vm=require('node:vm');
const assert=require('node:assert/strict');
const root=path.join(process.cwd(),'tools/parent-guardian-prefill-preview');
const scope={window:{}};
vm.runInNewContext(fs.readFileSync(path.join(root,'fixtures.js'),'utf8'),scope);
const fixture=scope.window.ParentGuardianFixture;
(async()=>{
  const browser=await chromium.launch({headless:true,executablePath:'C:/Users/katet/AppData/Local/ms-playwright/chromium_headless_shell-1243/chrome-headless-shell-win64/chrome-headless-shell.exe'});
  const page=await browser.newPage({viewport:{width:1380,height:1000}});
  const errors=[],external=[],writes=[],checks=[];
  let accept=false;
  page.on('pageerror',error=>errors.push(error.message));
  page.on('dialog',dialog=>accept?dialog.accept():dialog.dismiss());
  await page.route('**/*',async route=>{
    const request=route.request();const url=new URL(request.url());
    if(!['GET','HEAD'].includes(request.method())){writes.push(request.url());await route.abort();return;}
    if(url.origin!=='http://127.0.0.1:8897'){external.push(request.url());await route.abort();return;}
    await route.continue();
  });
  const choose=async(kind,state)=>{await page.locator('#preview-kind').selectOption(kind);await page.locator('#preview-state').selectOption(state);};
  const values=()=>page.locator('#mock-view form input[name],#mock-view form textarea[name]').evaluateAll(fields=>Object.fromEntries(fields.map(f=>[f.name,f.value])));
  try{
    await page.goto('http://127.0.0.1:8897/');
    for(const kind of ['invite','add','current','new']){
      for(const state of ['initial','empty','partial','filled','error','expired']){
        await choose(kind,state);
        if(state==='expired'){assert.equal(await page.locator('#mock-view input').count(),0);continue;}
        const fields=page.locator('#mock-view form input[name],#mock-view form textarea[name]');
        assert.equal(await fields.count(),kind==='new'?28:9);
        assert.equal(await page.locator('#mock-view [required]').count(),kind==='new'?13:6);
        if(state==='initial'){
          if(kind==='invite') assert.deepEqual(await values(),{...fixture.registered});
          else if(kind!=='new') assert.ok(Object.values(await values()).every(value=>value===''));
        }
        if(state==='partial'){assert.equal(await page.locator('[name=g1_phone]').inputValue(),'');assert.equal(await page.locator('[name=g1_first_name]').inputValue(),'あおい');}
        if(state==='error'){assert.equal(await page.locator('[name=g1_phone]').inputValue(),'');assert.equal(await page.locator('[name=g1_workplace]').inputValue(),'見本事業所');}
      }
      checks.push({kind,fields:kind==='new'?28:9,states:6});
    }
    // Registered values can be submitted unchanged, without retyping.
    await choose('invite','initial');
    await page.locator('#mock-view button[type=submit]').click();
    assert.match(await page.locator('#mock-view h1').innerText(),/受け付け/);
    await page.locator('#try-review').click();
    assert.equal(await page.locator('.mock-review>div').count(),9);
    assert.match(await page.locator('.mock-review').innerText(),/090-0000-0000/);
    await page.locator('button[value=approve]').click();
    assert.match(await page.locator('[role=alert]').innerText(),/確認理由/);
    await page.locator('[name=reason]').fill('架空データでの確認');
    await page.locator('button[value=approve]').click();
    assert.match(await page.locator('[role=alert]').innerText(),/チェック/);
    await page.locator('[name=enrollment_confirmed]').check();
    await page.locator('button[value=approve]').click();
    assert.match(await page.locator('#mock-view h1').innerText(),/承認しました/);
    // Validation keeps the user's correction, rather than restoring the ledger value.
    await choose('invite','initial');
    await page.locator('[name=g1_first_name]').fill('あおい修正');
    await page.locator('[name=g1_phone]').fill('');
    await page.locator('#mock-view button[type=submit]').click();
    assert.equal(await page.locator('[name=g1_first_name]').inputValue(),'あおい修正');
    await page.locator('#cancel-guardian-registration').click();
    assert.equal(await page.locator('[name=g1_first_name]').inputValue(),'あおい修正');
    accept=true;await page.locator('#cancel-guardian-registration').click();accept=false;
    assert.equal(await page.locator('#mock-view input').count(),0);
    await page.locator('#start-over').click();
    assert.deepEqual(await values(),{...fixture.registered});
    await page.evaluate(()=>window.scrollTo(0,0));
    await page.screenshot({path:path.join(root,'verified-invite-desktop.png'),fullPage:true});
    await page.setViewportSize({width:390,height:844});
    for(const kind of ['invite','add','current','new']){
      await choose(kind,'initial');
      assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=window.innerWidth));
    }
    await choose('invite','initial');
    await page.screenshot({path:path.join(root,'verified-invite-mobile.png'),fullPage:true});
    assert.deepEqual(errors,[]);assert.deepEqual(external,[]);assert.deepEqual(writes,[]);
    const result={verified:true,checks,unchangedSubmission:true,validationRetainsEdits:true,cancelAndReopen:true,mobileWidth:390,errors,external,writes};
    fs.writeFileSync(path.join(root,'verification.json'),JSON.stringify(result,null,2)+'\n');
    console.log(JSON.stringify(result));
  }finally{await browser.close();}
})().catch(error=>{console.error(error);process.exitCode=1;});
