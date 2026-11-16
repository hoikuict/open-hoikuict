// Capture fixture pages from build_entry_review_capture.py. All requests are served from disk.
const fs = require('node:fs/promises');
const path = require('node:path');
const assert = require('node:assert/strict');
const { chromium } = require('playwright');

async function main() {
  const root = path.resolve(__dirname, '../../../..');
  const snapshots = path.join(root, '.local-dev/manual-entry-review');
  const origin = 'http://manual.test';
  const browser = await chromium.launch({ executablePath: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE || undefined });
  try {
    const page = await browser.newPage({ viewport: { width: 540, height: 900 }, locale: 'ja-JP' });
    const pageNames = new Set(['list', 'new', 'saved', 'detail', 'pending', 'returned', 'no-recipient']);
    await page.route('**/*', async route => {
      const url = new URL(route.request().url());
      assert.equal(route.request().method(), 'GET');
      if (url.hostname === 'cdn.tailwindcss.com') {
        return route.fulfill({ path: path.resolve(__dirname, '../../dist/assets/tailwind.js'), contentType: 'text/javascript' });
      }
      if (url.origin !== origin) return route.abort();
      if (url.pathname === '/static/js/child-progress.js') {
        return route.fulfill({ path: path.join(root, '.local-dev/child-review-rollout-20261108/source', url.pathname.slice(1)), contentType: 'text/javascript' });
      }
      const name = url.pathname.startsWith('/plans/documents/') ? 'detail' : url.pathname.slice(1);
      if (pageNames.has(name)) return route.fulfill({ path: path.join(snapshots, name + '.html'), contentType: 'text/html; charset=utf-8' });
      return route.abort();
    });
    const load = async name => {
      await page.goto(origin + '/' + name, { waitUntil: 'networkidle' });
      await page.evaluate(() => document.fonts.ready);
    };
    async function capture(name, ...elements) {
      await elements[0].evaluate(el => window.scrollBy(0, el.getBoundingClientRect().top - 90));
      const boxes = await Promise.all(elements.map(el => el.boundingBox()));
      const x = Math.max(0, Math.floor(Math.min(...boxes.map(r => r.x))) - 3);
      const y = Math.max(0, Math.floor(Math.min(...boxes.map(r => r.y))) - 3);
      const right = Math.min(page.viewportSize().width, Math.ceil(Math.max(...boxes.map(r => r.x + r.width))) + 3);
      const bottom = Math.ceil(Math.max(...boxes.map(r => r.y + r.height))) + 3;
      assert(bottom <= page.viewportSize().height, 'Capture exceeds viewport: ' + name);
      const clip = { x, y, width: right - x, height: bottom - y };
      await page.screenshot({ clip, path: path.join(__dirname, 'entry-' + name + '.jpg'), quality: 93 });
      console.log(name, clip.width, clip.height);
    }
    await page.setViewportSize({ width: 1160, height: 900 });
    await load('list');
    await capture('start', page.locator('main table'));
    await page.setViewportSize({ width: 500, height: 900 });
    await load('new');
    await capture('period', page.locator('[data-progress-editor] > div').first(), page.locator('[aria-label="対象期間の選択"]'));
    const overview = page.getByLabel('対象期間の子どもの姿', { exact: false });
    await overview.fill('砂場で「どうぞ」とカップを渡し、友だちと一緒に遊ぶ姿が増えた。');
    await capture('overview', overview.locator('xpath=ancestor::section[1]'));
    await page.locator('[name="source_log_ids"]').check();
    await capture('evidence', page.locator('aside section').filter({ hasText: '対象期間の子どもの記録' }));
    await capture('save', page.locator('[data-progress-save-state]').locator('..'));
    // The subsequent page comes from an actual successful TestClient POST.
    await page.on('dialog', dialog => dialog.accept());
    await load('saved');
    await capture('saved', page.locator('[role="status"]').filter({ hasText: '下書きを保存しました' }), page.getByRole('link', { name: '詳細・承認へ' }).locator('..'));
    await load('detail');
    await capture('request', page.locator('.document-header'), page.locator('.status-panel'));
    await load('pending');
    await capture('pending', page.locator('.document-header'), page.locator('.status-panel'));
    await load('returned');
    await capture('returned', page.locator('.document-header'), page.locator('.status-panel'));
    await load('no-recipient');
    await capture('no-recipient', page.locator('.status-panel'));

    // Compare normal navigation and the saved draft's link using the release JS.
    await load('saved');
    await overview.fill('保存していない追記の見本');
    await page.getByRole('link', { name: '作成状況へ' }).click();
    assert(await page.getByRole('button', { name: '保存して切り替える' }).isVisible());
    await page.getByRole('button', { name: '入力を続ける' }).click();
    await page.getByRole('link', { name: '詳細・承認へ' }).click();
    await capture('unsaved', page.locator('[data-progress-unsaved]'));
    await page.getByRole('button', { name: '入力を続ける' }).click();
    assert.equal(await overview.inputValue(), '保存していない追記の見本');
    await page.getByRole('link', { name: '詳細・承認へ' }).click();
    const detailUrl = await page.locator('[data-progress-detail]').getAttribute('href');
    const saveUrl = origin + await page.locator('[data-progress-body]').getAttribute('action');
    const saveGo = page.getByRole('button', { name: '保存して切り替える' });
    await page.route(saveUrl, route => route.abort(), {times: 1});
    await saveGo.click();
    await page.getByText('保存を確認できませんでした。', { exact: false }).waitFor();
    assert.equal(await overview.inputValue(), '保存していない追記の見本');
    assert(await page.locator('[name="source_log_ids"]').isChecked());
    await page.route(saveUrl, route => {
      assert.equal(route.request().method(), 'POST');
      assert(route.request().postData().includes('保存していない追記の見本'));
      assert(route.request().postData().includes(detailUrl));
      return route.fulfill({ json: { location: detailUrl } });
    }, {times: 1});
    await saveGo.click();
    await page.waitForURL('**/plans/documents/*');
    await load('saved');
    await overview.fill('破棄する追記');
    await page.getByRole('link', { name: '詳細・承認へ' }).click();
    await page.getByRole('button', { name: '保存せず切り替える' }).click();
    await page.waitForURL('**/plans/documents/*');
    assert(!(await page.locator('main').innerText()).includes('破棄する追記'));
    assert(await page.getByRole('button', { name: 'レビュー依頼' }).isVisible());
    for (const width of [390, 1440]) {
      await page.setViewportSize({ width, height: 900 });
      await load('saved');
      await page.getByRole('link', {name: '対象期間の子どもの記録'}).click();
      assert(await page.locator('#progress-logs').evaluate(el => el === document.activeElement && el.getBoundingClientRect().top < innerHeight));
    }
    await fs.writeFile(path.join(snapshots, 'observations.json'), JSON.stringify({
      draftDirty: true, detailOffersSaveDiscardStay: true, networkFailureKeepsInputAndEvidence: true,
      saveNavigatesToSameDocument: true, evidenceHeadingAtWidths: [390, 1440],
    }, null, 2));
  } finally {
    await browser.close();
  }
}
main().catch(error => { console.error(error); process.exitCode = 1; });
