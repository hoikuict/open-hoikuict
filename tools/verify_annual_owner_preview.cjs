const {chromium}=require('C:/Users/katet/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright');
const assert=require('node:assert/strict');
const fs=require('node:fs');
(async()=>{
  const browser=await chromium.launch({headless:true,executablePath:'C:/Users/katet/AppData/Local/ms-playwright/chromium_headless_shell-1243/chrome-headless-shell-win64/chrome-headless-shell.exe'});
  const page=await browser.newPage({viewport:{width:1440,height:1080}}),errors=[],writes=[],external=[],checks=[];
  page.on('pageerror',e=>errors.push(e.message));
  page.on('request',r=>{if(!r.url().startsWith('http://127.0.0.1:8893/'))external.push(r.url());if(!['GET','HEAD'].includes(r.method()))writes.push(r.url());});
  page.on('dialog',d=>d.accept());
  const owner=page.locator('#annual-owner'),check=(label)=>checks.push(label);
  const switchTo=async(id,value)=>{await page.locator('#'+id).selectOption(value);await page.waitForTimeout(50);};
  try{
    await page.goto('http://127.0.0.1:8893/');await owner.waitFor();
    assert.equal(await owner.inputValue(),'見本 花1・見本 空1');check('新規の修正案は管理者を除く');
    let count=0;
    for(let id=1;id<=6;id++){
      await switchTo('annual-classroom',String(id));
      const expected=await page.evaluate(id=>Object.keys(window.ANNUAL_PREVIEW_FIXTURES.find(c=>c.id===id).sheet.fields).length,id);
      assert.equal(await page.locator('[data-edit]').count(),expected);count+=expected;
      assert.equal(await page.locator('[data-reflection]').count(),8);
      assert.equal(await owner.inputValue(),`見本 花${id}・見本 空${id}`);
    }
    assert.equal(count,298);check('6年齢298本文欄と48反省欄を表示');
    await switchTo('annual-classroom','1');
    await switchTo('preview-rule','current');assert.match(await owner.inputValue(),/見本 管理者/);check('現在の管理者混入を再現');
    await switchTo('preview-rule','proposed');await switchTo('preview-registration','admin-only');assert.equal(await owner.inputValue(),'');
    await page.locator('#annual-save').click();assert.match(await page.locator('#annual-message').innerText(),/担任名を入力/);check('管理者だけなら空欄・空欄保存の入力エラー');
    await owner.fill('手入力 担任');await page.locator('#annual-save').click();
    await owner.fill('取消前の名前');await owner.blur();await page.locator('#annual-undo').click();assert.equal(await owner.inputValue(),'手入力 担任');
    await page.locator('#preview-reopen').click();assert.equal(await owner.inputValue(),'手入力 担任');check('手入力を保存・変更を戻す・保存内容を開き直す');
    await switchTo('preview-registration','both');await switchTo('preview-state','legacy');assert.match(await owner.inputValue(),/見本 管理者/);
    await owner.fill('見本 花1・見本 空1');await page.locator('#annual-save').click();await page.locator('#preview-reopen').click();assert.equal(await owner.inputValue(),'見本 花1・見本 空1');check('保存済みを保持し、下書きの手動修正を保存できる');
    await switchTo('preview-state','approved');assert.match(await owner.inputValue(),/見本 管理者/);assert.equal(await owner.getAttribute('readonly'),'');assert.equal(await page.locator('#annual-save').isDisabled(),true);check('承認済みの担任名を保持し編集不可');
    await switchTo('preview-state','error');await owner.fill('エラー後も保持する名前');await page.locator('#annual-save').click();assert.match(await page.locator('#annual-message').innerText(),/保存できません/);assert.equal(await owner.inputValue(),'エラー後も保持する名前');check('保存エラーでも入力保持');
    await switchTo('preview-state','empty');assert.equal(await page.locator('[data-edit]').evaluateAll(nodes=>nodes.filter(n=>n.value).length),0);check('本文未入力を表示');
    await switchTo('preview-state','partial');const n=await page.locator('[data-edit]').evaluateAll(nodes=>nodes.filter(n=>n.value).length);assert.ok(n>0&&n<await page.locator('[data-edit]').count());check('本文一部入力を表示');
    await switchTo('preview-state','filled');await page.locator('[data-reflection]').first().fill('保存する架空の反省');await page.locator('#reflection-save').click();await page.locator('#preview-reopen').click();assert.equal(await page.locator('[data-reflection]').first().inputValue(),'保存する架空の反省');check('既存反省欄の模擬保存');
    await page.locator('.annual-document-link').click();assert.match(await page.locator('#preview-note').innerText(),/外部接続は行いません/);check('文書リンクの本番接続なし');
    await switchTo('preview-state','new');await owner.scrollIntoViewIfNeeded();await page.screenshot({path:'tools/annual-owner-preview/verified-desktop.png'});
    await page.setViewportSize({width:390,height:844});await page.screenshot({path:'tools/annual-owner-preview/verified-mobile.png'});
    assert.deepEqual(errors,[]);assert.deepEqual(writes,[]);assert.deepEqual(external,[]);check('ブラウザー例外・書込み要求・外部要求すべて0');
    const result={checks,errors,writes,external,baseline:'5b142edd546a4a1761b8dc5aa3cf82d685a5241c'};
    fs.writeFileSync('tools/annual-owner-preview/verification.json',JSON.stringify(result,null,2));console.log(JSON.stringify(result,null,2));
  }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});
