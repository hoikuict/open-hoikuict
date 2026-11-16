const assert = require('node:assert/strict');
const { chromium } = require('playwright');

(async () => {
  const origin = process.argv[2] || 'http://127.0.0.1:8087';
  assert.equal(new URL(origin).hostname, '127.0.0.1');
  const browser = await chromium.launch({executablePath: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE});
  try {
    const page = await browser.newPage({viewport:{width:1400,height:940},locale:'ja-JP'});
    const problems = [];
    page.on('pageerror', e => problems.push(e.message));
    page.on('response', r => { if (r.status() >= 400) problems.push(r.status()+' '+r.url()); });
    await page.route('**/*', route => {
      if (new URL(route.request().url()).origin === origin) return route.continue();
      problems.push(route.request().url());
      return route.abort();
    });
    const visit = async path => assert.ok((await page.goto(origin + path)).ok(), path);
    const follow = async locator => {
      await Promise.all([page.waitForNavigation({waitUntil:'load'}),locator.click()]);
    };
    await visit('/plans/');
    assert.deepEqual(await page.locator('.period-links strong').allTextContents(), ['年案','月案','週案','日案']);
    assert.ok(await page.locator('.format-label.old').count());
    assert.ok(await page.locator('.format-label:not(.old)').count());
    const destinations = [
      ['年案','#annual-save'],['月案','.month-grid'],['週案','.week-list'],['日案','a[href*="daily-plans/new"]']
    ];
    for (const [name, target] of destinations) {
      await follow(page.locator('.period-links a').filter({has:page.getByText(name,{exact:true})}));
      await page.locator(target).first().waitFor({state:'attached'});
      await visit('/plans/');
    }
    await follow(page.getByRole('link',{name:/旧式の帳票/}));
    assert.equal(await page.locator('.format-label:not(.old)').count(), 0);
    const forms = await page.locator('.old-options a,.old-options + a').evaluateAll(links => links.map(a=>a.pathname));
    assert.equal(forms.length,5);
    for (const path of forms) {
      await visit(path);
      assert.ok(await page.locator('main form').count(), path);
      assert.match(await page.locator('.plan-breadcrumb').innerText(), /旧式の帳票/);
    }
    await visit('/plans/annual-plans/new');
    assert.equal(await page.getByText('自園の年案を引き継ぐ・開く',{exact:true}).count(),1);
    for (const [path, oldOnly, both, editor] of [
      ['/plans/monthly-plans/?year=2026&age=0','2026-10','2026-11','/monthly-library'],
      ['/plans/weekly-plans/?month=2026-11&age=0','2026-11-02','2026-11-09','/weekly-library']
    ]) {
      const byKey = key => page.locator('[data-period="'+key+'"]');
      await visit(path);
      assert.match(await byKey(oldOnly).innerText(), /未作成/);
      const old = byKey(oldOnly).getByRole('link',{name:/旧式を開く/});
      const oldUrl = await old.getAttribute('href');
      await follow(old);
      await follow(page.getByRole('link',{name:'修正',exact:true}));
      assert.match(await page.locator('.plan-breadcrumb').innerText(), /旧式の帳票/);
      assert.equal(await page.locator('main form').getAttribute('action'),oldUrl);
      await visit(path);
      await follow(byKey(oldOnly).getByRole('link',{name:'自園の帳票で作成'}));
      assert.ok(new URL(page.url()).pathname.endsWith(editor));
      await visit(path);
      assert.match(await byKey(both).innerText(), /自園の帳票 · 下書き/);
      assert.equal(await byKey(both).getByRole('link',{name:/旧式を開く/}).count(),1);
      await follow(byKey(both).getByRole('link',{name:'自園の帳票を開く'}));
      assert.ok(new URL(page.url()).pathname.endsWith(editor));
    }
    await visit('/mock/scenes/empty');
    assert.match(await page.locator('main').innerText(),/まだ帳票がありません/);
    await visit('/mock/scenes/filled');
    assert.equal(await page.locator('.document-row').count(),8);
    await visit('/mock/scenes/error');
    await visit('/plans/legacy/');
    await follow(page.getByRole('link',{name:'もう一度読み込む'}));
    await page.locator('.document-row').first().waitFor();
    assert.equal(new URL(page.url()).pathname, '/plans/legacy/');
    assert.ok(await page.locator('.document-row').count());
    await visit('/plans/');
    if (process.env.PLAN_SCREENSHOT) await page.locator('main.plan-docs-content').screenshot({path:process.env.PLAN_SCREENSHOT});
    await page.setViewportSize({width:390,height:844});
    for (const url of ['/plans/','/plans/legacy/','/plans/monthly-plans/','/plans/weekly-plans/']) {
      await visit(url);
      assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=window.innerWidth),url+' overflows');
    }
    assert.deepEqual(problems,[]);
    console.log('Verified standard and legacy routes, both calendar formats and edit targets, four scenarios, mobile layout and local assets.');
  } finally { await browser.close(); }
})().catch(error => {console.error(error); process.exitCode=1;});
