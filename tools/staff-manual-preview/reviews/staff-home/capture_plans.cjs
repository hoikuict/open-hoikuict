// Run build_plan_capture.py first. All pages, assets and sample data stay on this PC.
const path = require('node:path');
const assert = require('node:assert/strict');
const {chromium} = require('playwright');

(async () => {
  const root = path.resolve(__dirname, '../../../..');
  const source = path.join(root, '.local-dev/document-search-rollout-20261108/source');
  const fixture = path.join(root, '.local-dev/manual-plan-capture');
  const origin = 'http://guide.test';
  const browser = await chromium.launch({executablePath: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE || undefined});
  try {
    const page = await browser.newPage({viewport:{width:1180,height:1100},locale:'ja-JP',deviceScaleFactor:1.5});
    const pages = new Map([['/plans/','home'],['/plans/documents/','search'],['/plans/legacy/','legacy'],
                           ['/plans/documents/4','day'],['/plans/documents/2','week']]);
    await page.route('**/*', async route => {
      const url = new URL(route.request().url());
      if (url.hostname === 'cdn.tailwindcss.com') return route.fulfill({path:path.resolve(__dirname,'../../dist/assets/tailwind.js'),contentType:'text/javascript'});
      if (url.hostname === 'unpkg.com') return route.fulfill({contentType:'text/javascript',body:''});
      assert.equal(url.origin, origin);
      if (pages.has(url.pathname)) return route.fulfill({path:path.join(fixture,pages.get(url.pathname)+'.html'),contentType:'text/html; charset=utf-8'});
      if (url.pathname.startsWith('/static/')) return route.fulfill({path:path.join(source,url.pathname.substring(1))});
      return route.abort();
    });
    const shot = async (id, locator) => {
      await locator.screenshot({path:path.join(__dirname,'plan-'+id+'.jpg'),quality:94});
    };
    await page.goto(origin+'/plans/');
    await page.evaluate(()=>document.fonts.ready);
    const menu = page.locator('#staff-sidebar a[href="/plans/"]');
    await menu.scrollIntoViewIfNeeded();
    const box = await menu.boundingBox();
    await page.screenshot({path:path.join(__dirname,'plan-menu.jpg'),quality:94,
      clip:{x:box.x,y:box.y-box.height,width:box.width,height:box.height*3}});
    await page.setViewportSize({width:510,height:1100});
    await page.reload();
    await page.waitForFunction(()=>document.getElementById('staff-sidebar').getBoundingClientRect().right <= 1);
    await shot('standard',page.locator('section[aria-labelledby="standard-heading"]'));
    await shot('legacy-entry',page.locator('.legacy-entry'));
    await shot('reminder',page.locator('section[aria-labelledby="reflection-reminder-heading"]'));
    await shot('notice',page.locator('section[aria-labelledby="review-notification-heading"]'));
    await shot('recent',page.locator('section[aria-labelledby="recent-heading"]'));
    await page.getByRole('link',{name:'すべて見る'}).click();
    await page.waitForURL('**/plans/documents/');
    const form = page.locator('#document-search');
    await form.locator('[name=kind]').selectOption('日案');
    await form.locator('[name=room]').selectOption('さくら組');
    await form.locator('[type=submit]').click();
    assert.equal(await page.locator('#search-count').innerText(),'全4件中 2件を表示');
    await form.locator('[name=status]').selectOption('下書き');
    await form.locator('[type=submit]').click();
    assert.equal(await page.locator('#search-count').innerText(),'全4件中 1件を表示');
    await shot('query',form);
    await shot('match',page.locator('#document-results'));
    await page.locator('#document-results .document-row:visible').click();
    await page.waitForURL('**/documents/4');
    await page.evaluate(()=>window.scrollTo(0,0));
    const back = page.locator('#back-to-list');
    const top = await back.boundingBox();
    const header = await page.locator('.document-header').boundingBox();
    await page.screenshot({path:path.join(__dirname,'plan-detail.jpg'),quality:94,
      clip:{x:header.x,y:top.y,width:header.width,height:header.y+header.height-top.y}});
    await back.click();
    await page.waitForURL(origin+'/plans/documents/');
    await page.waitForFunction(()=>document.getElementById('search-count')?.textContent.length > 0);
    assert.equal(await form.locator('[name=status]').inputValue(),'下書き');
    assert.equal(await page.locator('#document-results .document-row:visible').count(),1);
    await form.locator('[name=q]').fill('見つからない名前');
    await form.locator('[type=submit]').click();
    await shot('empty',page.locator('#no-matches'));
    await page.getByRole('button',{name:'すべての帳票を表示'}).click();
    assert.equal(await page.locator('#document-results .document-row:visible').count(),4);
    await page.goto(origin+'/plans/');
    await page.locator('.legacy-entry').click();
    await shot('legacy-list',page.locator('.plan-index > section').first());
    await shot('legacy-new',page.locator('#old-create'));
    await page.locator('.document-row').filter({hasText:'週案'}).click();
    assert.equal(await page.locator('h1').innerText(),'2026-11-02週 週案（さくら組）');
    await shot('legacy-detail',page.locator('.document-header'));
    console.log('Photographed 13 screen regions and verified search, back, reset and legacy week navigation.');
  } finally {await browser.close();}
})().catch(error=>{console.error(error);process.exitCode=1;});
