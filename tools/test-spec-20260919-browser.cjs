const assert = require('node:assert/strict');
const path = require('node:path');
const fs = require('node:fs');
const { spawn } = require('node:child_process');
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const root = path.resolve(__dirname, '..');
const base = `http://127.0.0.1:${process.env.TEST_PORT || 8775}`;
const screenshots = process.env.TEST_SCREENSHOT_DIR || path.join(root, 'tmp_spec_review_20260919', 'screenshots');
fs.mkdirSync(screenshots, { recursive: true });
const python = process.env.TEST_PYTHON || (process.platform === 'win32' ? 'venv/Scripts/python.exe' : 'python');
const server = spawn(python, ['-m', 'uvicorn', 'tools.spec_20260919_browser_fixture:app', '--host', '127.0.0.1', '--port', new URL(base).port], {
  cwd: root, windowsHide: true, stdio: ['ignore', 'pipe', 'pipe'],
  env: { ...process.env, PYTHONDONTWRITEBYTECODE: '1', PYTHONUTF8: '1', HOIKUICT_DATABASE_URL: 'sqlite://', HOIKUICT_ENV: 'development', HOIKUICT_COOKIE_SECURE: '0' },
});
let output = '';
server.stdout.on('data', data => { output += data; });
server.stderr.on('data', data => { output += data; });
const pause = ms => new Promise(resolve => setTimeout(resolve, ms));
(async () => {
  let browser;
  try {
    let ids;
    for (let attempt = 0; attempt < 100; attempt++) {
      try { const res = await fetch(`${base}/__fixture19`); if (res.ok) { ids = await res.json(); break; } } catch (_) {}
      if (server.exitCode !== null) throw new Error(output);
      await pause(100);
    }
    assert(ids, output);
    const state = async () => (await fetch(`${base}/__fixture19/state`)).json();
    browser = await chromium.launch({ channel: process.env.TEST_BROWSER_CHANNEL || 'msedge', headless: true });
    const context = await browser.newContext({ viewport: { width: 390, height: 844 }, ignoreHTTPSErrors: true });
    await context.request.post(`${base}/parent-portal/login`, { form: { parent_account_id: String(ids.parent_id) } });
    const page = await context.newPage(), errors=[];
    page.on('pageerror', e => errors.push(e.message));
    page.on('requestfailed', request => console.error('Request failed:', request.url(), request.failure()?.errorText));
    const button = name => page.getByRole('button', {name, exact:true});
    const contactUrl = `${base}/parent-portal/children/${ids.child_id}/contact?date=${ids.today}`;
    await page.goto(contactUrl);
    try {
      await page.waitForFunction(() => getComputedStyle(document.querySelector('nav')).backgroundColor === 'rgb(67, 56, 202)');
    } catch (error) {
      console.error(await page.evaluate(() => ({ title: document.title, nav: document.querySelector('nav')?.outerHTML, background: getComputedStyle(document.querySelector('nav')).backgroundColor })));
      await page.screenshot({path:path.join(screenshots,'initial-failure.png'),fullPage:true});
      throw error;
    }
    assert(await page.locator('[data-pickup-minute="00"]').isDisabled());
    await page.locator('[name=attendance_mode][value=absent]').check();
    await page.locator('[name=attendance_mode][value=present]').check();
    assert(await page.locator('[data-pickup-minute-exact]').isDisabled());
    await page.locator('[data-pickup-hour="22"]').click();
    assert.equal(await page.locator('[data-selected-pickup-time]').innerText(), '22:--');
    assert(await page.locator('[data-pickup-minute="45"]').isEnabled());
    await page.locator('[data-pickup-minute="45"]').click();
    await page.locator('[name=pickup_person]').selectOption('母');
    await page.locator('[name=snack_required][value="0"]').check();
    await page.locator('[name=bedtime]').fill('21:00');
    await page.locator('[name=wakeup_time]').fill('06:30');
    await page.locator('[name=breakfast_contents]').fill('ごはん、みそ汁、卵');
    await page.locator('[name=sleep_notes]').fill('よく眠れました');
    await page.locator('[name=temperature]').fill('36.5');
    await page.locator('[name=contact_note]').fill('着替えを補充しました');
    for (const width of [320, 390, 768, 1280]) {
      await page.setViewportSize({width,height:900});
      assert(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1), 'Contact overflow at '+width);
    }
    await page.setViewportSize({width:390,height:844});
    await page.screenshot({path:path.join(screenshots,'contact-mobile.png'),fullPage:true});
    await button('保存する').click(); await page.waitForURL('**/parent-portal/?**');
    let saved = await state();
    assert.equal(saved.records[ids.child_id].planned_pickup_time,'22:45');
    assert.equal(saved.records[ids.child_id].check_in_at,null);
    assert.equal(saved.contacts[ids.child_id].extra_data.breakfast_contents,'ごはん、みそ汁、卵');
    await page.goto(contactUrl);
    assert.equal(await page.locator('[name=sleep_notes]').inputValue(),'よく眠れました');
    assert.equal(await page.locator('[data-selected-pickup-time]').innerText(),'22:45');
    console.log('PASS: complete parent contact fields and pickup save together; no closing-time limit; responsive 320/390/768/1280.');

    await page.setViewportSize({width:1280,height:900});
    await page.goto(`${base}/guardian/terminal`);
    await page.locator('[name=kiosk_token]').fill('synthetic-browser-token');
    await page.locator('form button[type=submit]').click();
    await page.locator('#terminal-clock').filter({hasText:/\d{2}:\d{2}:\d{2}/}).waitFor();
    await page.goto(`${base}/guardian/?date=${ids.today}&child_id=${ids.child_id}`);
    await button('全画面').click();
    await page.waitForFunction(() => !!document.fullscreenElement);
    assert.equal(await button('降園する').count(),0);
    assert(await button('登園する').evaluate(el => parseFloat(getComputedStyle(el).fontSize) >= 30 && el.offsetHeight >= 80));
    await button('登園する').click();
    await page.getByRole('heading',{name:'この内容で登園を受け付けます'}).waitFor();
    await page.screenshot({path:path.join(screenshots,'arrival-confirm.png'),fullPage:true});
    assert.equal((await state()).records[ids.child_id].check_in_at,null);
    await button('修正').click();await page.locator('[data-pickup-hour="18"]').waitFor();
    await page.locator('[data-pickup-hour="18"]').click();await page.locator('[data-pickup-minute="30"]').click();
    await page.locator('[data-pickup-person="父"]').click();
    await page.locator('[name=snack_required][value="1"]').check();
    await button('確認へ').click();await page.getByRole('heading',{name:'この内容で登園を受け付けます'}).waitFor();
    assert(await page.getByText('18:30',{exact:true}).isVisible());
    await page.getByRole('link',{name:'取り消し',exact:true}).click();
    await page.locator(`a[href*="class_id=${ids.room_id}"]`).first().waitFor();
    saved=await state();assert.equal(saved.records[ids.child_id].planned_pickup_time,'22:45');assert.equal(saved.records[ids.child_id].check_in_at,null);
    const chooseChild = async id => {
      await page.locator(`a[href*="class_id=${ids.room_id}"]`).first().click();
      await page.locator(`a[href*="child_id=${id}"]`).click();
    };
    await chooseChild(ids.child_id);await button('登園する').click();
    await page.getByRole('heading',{name:'この内容で登園を受け付けます'}).waitFor();
    assert(await page.getByText('22:45',{exact:true}).isVisible());
    await button('決定').click();
    await page.getByRole('heading',{name:'登園を受け付けました。',exact:true}).waitFor();
    await page.locator(`a[href*="class_id=${ids.room_id}"]`).first().waitFor();
    assert((await state()).records[ids.child_id].check_in_at);
    assert(await page.evaluate(() => !!document.fullscreenElement));
    await chooseChild(ids.child_id);await button('降園する').waitFor();
    assert.equal(await page.locator('[name=actual_pickup_person]').inputValue(),'');
    await button('降園する').click();assert(await page.locator('[data-departure-error]').isVisible());
    assert.equal((await state()).records[ids.child_id].check_out_at,null);
    await page.screenshot({path:path.join(screenshots,'departure-required.png'),fullPage:true});
    await page.locator('[data-actual-pickup="祖母"]').click();await button('降園する').click();
    await page.locator(`a[href*="class_id=${ids.room_id}"]`).first().waitFor();
    saved=await state();assert.equal(saved.records[ids.child_id].actual_pickup_person,'祖母');assert.equal(saved.records[ids.child_id].pickup_person,'母');
    console.log('PASS: first arrival remains a draft, edit/cancel preserve data, final confirmation saves, fullscreen survives; actual pickup is required and separate.');

    await chooseChild(ids.visual_id);await button('降園する').waitFor();
    assert(await page.getByText(/未打刻（職員が出席確認済み）/).isVisible());
    await page.locator('[data-actual-pickup="父"]').click();await button('降園する').click();
    await page.locator(`a[href*="class_id=${ids.room_id}"]`).first().waitFor();
    saved=await state();assert.equal(saved.records[ids.visual_id].check_in_at,null);assert(saved.records[ids.visual_id].check_out_at);
    await chooseChild(ids.partial_id);await button('登園する').click();
    await page.locator('[data-selected-pickup-time]').waitFor();
    assert.equal(await page.locator('[data-selected-pickup-time]').innerText(),'17:00');
    assert.equal(await page.locator('[name=snack_required]:checked').count(),0);
    await button('確認へ').click();assert(await page.locator('[data-pickup-person-error]').isVisible());
    await page.locator('[data-pickup-person="母"]').click();await page.locator('[name=snack_required][value="0"]').check();
    await page.screenshot({path:path.join(screenshots,'pickup-input.png'),fullPage:true});
    await button('確認へ').click();await page.getByRole('heading',{name:'この内容で登園を受け付けます'}).waitFor();
    assert.deepEqual(errors,[]);
    console.log('PASS: visual presence permits departure with arrival still missing; partial plans retain time and require remaining fields; no JavaScript errors.');
  } finally {if(browser)await browser.close();server.kill();}
})().catch(error => {console.error(error);console.error(output.slice(-4000));process.exitCode=1;});
