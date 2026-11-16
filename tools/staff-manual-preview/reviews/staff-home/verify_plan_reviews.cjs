// Check the illustrated guides, enlarged images and search in the local preview.
const {chromium}=require('playwright');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const origin=process.env.MANUAL_PREVIEW_ORIGIN || 'http://127.0.0.1:8122';
const evidence=process.env.MANUAL_VERIFICATION_DIR || path.resolve(__dirname,'../../../../.local-dev/manual-plan-review-20261116');

async function main(){
  fs.mkdirSync(evidence,{recursive:true});
  const browser=await chromium.launch({executablePath:process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE});
  const page=await browser.newPage({locale:'ja-JP'});
  const layouts=[],links=new Set(),errors=[];
  page.on('pageerror',error=>errors.push(error.message));
  try{
    for(const width of [1366,390,320]){
      await page.setViewportSize({width,height:900});
      for(const [slug,section] of [['monthly','review-missing'],['weekly','review'],['daily','save-help']]){
        const response=await page.goto(`${origin}/plans/${slug}/`);assert.equal(response.status(),200);
        await page.evaluate(()=>document.fonts.ready);
        const info=await page.evaluate(()=>({
          overflow:document.documentElement.scrollWidth>innerWidth+1,
          images:[...document.images].map(img=>({src:img.getAttribute('src'),ok:img.complete&&img.naturalWidth>0,width:img.naturalWidth,height:img.naturalHeight,declared:[img.width,img.height]})),
          anchors:[...document.querySelectorAll('.contents a[href^="#"]')].map(a=>({href:a.hash,exists:!!document.querySelector(a.hash)})),
          links:[...document.querySelectorAll('a[href]')].map(a=>a.href)
        }));
        assert.equal(info.overflow,false,`${slug} at ${width}px overflows`);
        assert.ok(info.images.every(img=>img.ok),`${slug}: image missing`);
        assert.ok(info.anchors.every(anchor=>anchor.exists),`${slug}: broken contents link`);
        info.links.forEach(url=>links.add(url.split('#')[0]));
        await page.locator('#'+section).scrollIntoViewIfNeeded();
        await page.screenshot({path:path.join(evidence,`${slug}-${width}.png`)});
        layouts.push({slug,width,images:info.images.length,contents:info.anchors.length,overflow:false});
      }
    }
    const enlarged=[];
    for(const [slug,image] of [['monthly','monthly-review-missing'],['weekly','weekly-review-pending'],['daily','daily-save-missing']]){
      await page.goto(`${origin}/plans/${slug}/`);
      await page.locator(`a[href="${image}.jpg"]`).click();
      assert.ok(page.url().endsWith(image+'.jpg'));
      await page.locator('img').waitFor();
      assert.ok(await page.locator('img').evaluate(img=>img.naturalWidth>0));
      enlarged.push(image);
    }
    const search=[];
    for(const [query,slugs] of [['レビュー依頼',['monthly','weekly']],['保存できない',['monthly','weekly','daily']],['記入漏れ',['daily']]]){
      await page.goto(origin+'/#home');
      await page.locator('#search-input').fill(query);
      await page.locator('#search-form button[type=submit]').click();
      for(const slug of slugs)await page.locator(`main a[href="plans/${slug}/"]`).waitFor();
      search.push({query,slugs});
    }
    for(const url of links){
      if(!url.startsWith(origin))continue;
      const response=await page.request.get(url);
      assert.ok(response.ok(),`${response.status()} ${url}`);
    }
    assert.deepEqual(errors,[]);
    const report={date:'2026-11-16',origin,layouts,enlarged,search,localLinks:links.size,pageErrors:errors};
    fs.writeFileSync(path.join(evidence,'manual-verification.json'),JSON.stringify(report,null,2)+'\n');
    console.log(JSON.stringify(report));
  }finally{await browser.close();}
}
main().catch(error=>{console.error(error);process.exitCode=1;});
