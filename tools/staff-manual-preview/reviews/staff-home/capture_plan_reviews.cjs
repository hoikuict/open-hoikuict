// Capture the deployed November changes; every submitted form uses a temporary DB.
const {chromium}=require('playwright');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const readline=require('node:readline');
const {once}=require('node:events');
const {spawn,execFileSync}=require('node:child_process');
const crypto=require('node:crypto');
const root=path.resolve(__dirname,'../../../..');
const out=path.join(__dirname,'plan-forms');
const evidence=path.join(root,'.local-dev/manual-plan-review-20261116');

async function main(){
  fs.mkdirSync(evidence,{recursive:true});
  const server=spawn(path.join(root,'venv/Scripts/python.exe'),['-X','utf8',path.join(__dirname,'plan_review_fixture.py')],
    {cwd:root,windowsHide:true,stdio:['ignore','pipe','inherit']});
  let browser,page;
  const checks=[],images=[],errors=[];
  try{
    const lines=readline.createInterface({input:server.stdout});
    const origin=await Promise.race([once(lines,'line').then(([line])=>line),once(server,'exit').then(([code])=>{throw Error('Fixture exited '+code);})]);
    assert.match(origin,/^http:\/\/127\.0\.0\.1:\d+$/);
    browser=await chromium.launch({executablePath:process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE});
    page=await browser.newPage({viewport:{width:1490,height:1050},deviceScaleFactor:1.25,locale:'ja-JP'});
    page.setDefaultTimeout(9000);
    page.on('pageerror',e=>errors.push(e.message));
    await page.route('**/*',async route=>{
      const url=new URL(route.request().url());
      if(url.origin===origin)return route.continue();
      if(url.hostname==='cdn.tailwindcss.com')return route.fulfill({path:path.resolve(__dirname,'../../dist/assets/tailwind.js'),contentType:'text/javascript'});
      if(url.hostname==='unpkg.com')return route.fulfill({body:'',contentType:'text/javascript'});
      return route.abort();
    });
    const loc=s=>page.locator(s).first();
    const go=uri=>page.goto(origin+uri);
    const shown=(selector,text)=>page.locator(selector).filter({hasText:text}).first().waitFor();
    async function shot(name,selector){
      if(name.startsWith('weekly-'))await page.evaluate(()=>scrollTo(0,document.body.scrollHeight));
      await page.evaluate(()=>document.fonts.ready);
      const target=loc(selector);await target.scrollIntoViewIfNeeded();
      const file=path.join(out,name+'.jpg');
      await target.screenshot({path:file,quality:94,animations:'disabled'});
      images.push({file:path.relative(root,file),sha256:crypto.createHash('sha256').update(fs.readFileSync(file)).digest('hex')});
    }
    await go('/fixture/monthly?mode=partial');
    await loc('#request-review').waitFor();
    await shot('monthly-save','.monthly-submit-pair');
    await loc('#request-review').click();
    await shown('#monthly-review-feedback','未記入 2件');
    await shot('monthly-review-missing','#drive-monthly-plan .actions');
    const missing=await page.locator('#monthly-review-feedback [data-review-field]').evaluateAll(els=>els.map(el=>el.dataset.reviewField));
    assert.equal(missing.length,2);
    for(const key of missing){
      await page.locator('#monthly-review-feedback [data-review-field]').first().click();
      assert.equal(await page.evaluate(()=>document.activeElement.dataset.cell),key);
      assert.equal(await loc('#page').inputValue(),'1');
      await loc('[data-cell="'+key+'"]').fill(key.endsWith(':play')?'落ち葉の色や形を見つけて楽しむ。':'かごを用意し、発見を受け止める。');
    }
    await shot('monthly-review-child','#form .roster');
    await shown('#monthly-review-feedback','入力がそろいました');
    await shot('monthly-review-ready','#drive-monthly-plan .actions');
    checks.push('月案：別ページの未記入2件から該当欄へ移動し、入力後に件数が更新。自動依頼なし。');
    await loc('#request-review').click();
    await page.waitForURL('**/plans/documents/*#review-status');
    await shown('.document-header','レビュー待ち');
    await page.setViewportSize({width:780,height:1050});
    await shot('monthly-review-pending','.document-header');
    await shot('monthly-review-withdraw','#review-status');
    await page.getByRole('button',{name:'レビューを取り下げる',exact:true}).click();
    await shown('.document-header','下書き');
    checks.push('月案：入力を保存してレビュー依頼し、詳細画面でレビュー待ちを表示。取り下げ後は下書き。');

    await go('/plans/weekly-library?classroom_id=1&month=2026-11&age=1&week_start=2026-11-02');
    await page.setViewportSize({width:950,height:1050});
    await loc('[name=owner_name]').waitFor();
    assert.equal(await loc('[name=owner_name]').inputValue(),'見本 はなこ');
    await loc('[data-start="2026-11-02"][data-field=aim]').fill('秋の自然に親しむ。');
    await loc('[data-start="2026-11-02"][data-field=activity]').fill('園庭で落ち葉を集める。');
    await loc('[data-start="2026-11-09"][data-field=activity]').fill('木の実を見つけて楽しむ。');
    await shot('weekly-save','#weekly-form .form-actions');
    await loc('[name=owner_name]').fill('');
    await loc('#weekly-review').click();
    await shown('#weekly-save-feedback','作成者を入力');
    await shot('weekly-review-missing','#weekly-form .form-actions');
    await loc('#weekly-save-feedback a').click();
    assert.equal(await page.evaluate(()=>document.activeElement.name),'owner_name');
    await loc('[name=owner_name]').fill('見本 はなこ');
    await loc('#weekly-review').click();
    await shown('#weekly-save-feedback','レビューを依頼しました');
    assert.ok(page.url().includes('/plans/weekly-library'));
    assert.equal(await loc('[data-start="2026-11-09"][data-field=activity]').inputValue(),'木の実を見つけて楽しむ。');
    await shot('weekly-review-pending','#weekly-form .form-actions');
    await shot('weekly-review-detail','.plan-calendar-nav');
    checks.push('週案：新規作成者の初期値・不足理由から移動・修正後に選択中の週だけレビュー依頼。同画面に残り別週の未保存入力を保持。');
    await loc('#weekly-document-link').click();
    await shown('.document-header','レビュー待ち');
    await shot('weekly-review-withdraw','#review-status');
    await page.getByRole('button',{name:'レビューを取り下げる',exact:true}).click();
    await shown('.document-header','下書き');
    checks.push('週案：文書詳細を開いてレビューを取り下げ、下書きへ戻る。');

    await go('/plans/daily-plans/new?target_date=2026-11-11&classroom_ref='+encodeURIComponent('そら組'));
    await loc('[name=daily_aims]').fill('粘土の感触を楽しむ。');
    await loc('#daily-draft [name=age_class]').selectOption('');
    await loc('#daily-draft button[type=submit]').click();
    await shown('#daily-save-feedback','確認が必要な項目 2件');
    await page.setViewportSize({width:780,height:1050});
    await shot('daily-save-missing','#daily-save-area');
    await loc('#daily-save-feedback [data-error-field=age_class]').click();
    assert.equal(await page.evaluate(()=>document.activeElement.id),'daily-age-class');
    await loc('#daily-draft [name=age_class]').selectOption({label:'3歳児'});
    await shown('#daily-save-feedback','確認が必要な項目 1件');
    await loc('#daily-save-feedback [data-error-field=timeline]').click();
    assert.equal(await page.evaluate(()=>document.activeElement.name),'timeline_time');
    await loc('[name=timeline_time]').fill('10:00');
    await loc('[name=timeline_children]').fill('粘土を丸めたり伸ばしたりする。');
    await loc('[name=timeline_support]').fill('作りたい形に合わせて声をかける。');
    await loc('[name=timeline_considerations]').fill('道具を使う場所を確かめる。');
    await shown('#daily-save-feedback','記入漏れは解消しました');
    await shot('daily-save-ready','#daily-save-area');
    assert.equal(await loc('[name=daily_aims]').inputValue(),'粘土の感触を楽しむ。');
    await loc('#daily-draft button[type=submit]').click();
    await shown('.document-header','下書き');
    checks.push('日案新規作成：保存直前に不足2件を表示。年齢・流れへ移動し件数が更新。入力内容を保持し、再度保存して文書詳細へ移動。');
    assert.deepEqual(errors,[]);
    const revision=execFileSync('git',['-C',path.join(root,'.local-dev/document-search-rollout-20261108/source'),'rev-parse','HEAD'],{encoding:'utf8',windowsHide:true}).trim();
    fs.writeFileSync(path.join(evidence,'capture-report.json'),JSON.stringify({date:'2026-11-16',revision,checks,images,pageErrors:errors},null,2)+'\n');
    console.log(JSON.stringify({checks,images:images.length,pageErrors:errors}));
  }catch(error){
    if(page){console.error('At:',page.url());console.error((await page.locator('body').innerText()).slice(-4000));await page.screenshot({path:path.join(evidence,'capture-failure.png'),fullPage:true});}
    throw error;
  }finally{
    if(browser)await browser.close();
    if(server.exitCode===null)server.kill();
  }
}
main().catch(error=>{console.error(error);process.exitCode=1;});
