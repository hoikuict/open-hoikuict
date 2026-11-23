const fs=require('fs'),path=require('path'),assert=require('assert');
const {chromium}=require('../../.local-dev/manual-update-20261123/node_modules/playwright');
const root=path.resolve(__dirname,'../..'),out=path.join(root,'docs/manual-guide-preview/assets'),evidence=path.join(root,'.local-dev/manual-refresh-20261123');
fs.mkdirSync(evidence,{recursive:true});
const mode=process.argv[2],report={mode,syntheticOnly:true,images:[],checks:[],errors:[]};
(async()=>{
 const browser=await chromium.launch({executablePath:'C:/Users/katet/AppData/Local/ms-playwright/chromium_headless_shell-1243/chrome-headless-shell-win64/chrome-headless-shell.exe'});
 try{
  const ctx=await browser.newContext({viewport:{width:mode==='parent'?600:1280,height:960},locale:'ja-JP'});
  await ctx.route('**/*',r=>r.request().url().startsWith('http://127.0.0.1:817')?r.continue():r.abort());
  const p=await ctx.newPage();p.setDefaultTimeout(12000);p.on('pageerror',e=>report.errors.push(e.message));
  const base='http://127.0.0.1:'+(mode==='billing'?'8172':'8171'),info=await(await ctx.request.get(base+'/__review/login')).json();
  const go=async u=>{const r=await p.goto(base+u);assert(r.ok(),u+' '+r.status());await p.evaluate(()=>document.fonts.ready);};
  const shot=async(name,selector='main')=>{await p.waitForTimeout(150);const target=typeof selector==='string'?p.locator(selector).first():selector;await target.screenshot({path:path.join(out,'r2-'+name+'.jpg'),type:'jpeg',quality:90});report.images.push('r2-'+name);};
  const fill=async(n,v)=>p.locator('[name="'+n+'"]').fill(v);
  if(mode==='parent'){
   await go('/parent-portal/');await shot('contact-entry');
   await go(info.contact);await shot('contact-empty');
   await p.locator('[name=attendance_mode][value=present]').check();await p.locator('[name=emergency_mode][value=usual]').check();
   await fill('temperature','36.6');await fill('bedtime','20:30');await fill('wakeup_time','06:30');await fill('sleep_notes','よく眠りました。');
   await p.locator('[name=dinner_appetite]').first().check();await p.locator('[name=breakfast_appetite]').first().check();await fill('dinner_contents','ごはん、焼き魚、野菜');await fill('breakfast_contents','トースト、バナナ');await fill('contact_note','いつもどおり元気です。');
   await shot('contact-emergency','[data-day-emergency]');await shot('contact-meals','[data-meal-container]');await shot('contact-care','[data-contact-group=temperature]');
   await shot('contact-filled');await p.getByRole('button',{name:'保存する',exact:true}).click();await p.waitForURL(/parent-portal\//);await p.getByText('日次連絡を保存しました。',{exact:true}).waitFor();await shot('contact-saved');
   await go(info.contact);await fill('temperature','37.5');await p.getByRole('button',{name:'保存する',exact:true}).click();await shot('contact-error');
   await go(info.pickup);await shot('pickup-empty');await p.locator('[data-pickup-hour="18"]').click();await shot('pickup-partial');
   assert(await p.locator('[data-pickup-minute="30"]').isDisabled());await p.getByText('その他の分を選ぶ',{exact:true}).click();await p.locator('[data-pickup-minute-exact]').selectOption('29');await p.locator('select[name=pickup_person]').selectOption('母');await p.locator('[name=snack_required][value="0"]').check();await shot('pickup-filled');
   await p.getByRole('button',{name:'予定を保存',exact:true}).click();await p.waitForURL(/parent-portal\//);await go(info.pickup);assert.equal(await p.locator('[name=planned_pickup_time]').inputValue(),'18:29');await shot('pickup-reopen');
   assert((await ctx.request.post(base+'/__manual/closing?value=18:00')).ok());await go(info.pickup);assert((await p.locator('main').innerText()).includes('18:00'));await shot('pickup-outside');assert((await ctx.request.post(base+'/__manual/closing?value=18:30')).ok());
   report.checks.push('食事・通常の連絡順を保存、体温エラーは保存不可、閉園18:30で18:29を保存し再表示、設定変更後の範囲外表示');
  }else if(mode==='medical'){
   await go('/health');await shot('health-overview');
   await p.locator('[name=attention]').selectOption('needs_attention');await fill('q','あおい');await p.getByRole('button',{name:'絞り込む',exact:true}).click();await shot('health-filter');
   await go('/children/1/health/profile');await shot('profile-entry');await shot('profile-basic',p.locator('form section').first());
   await go(info.medical);await p.locator('[name=parent_id]').selectOption(String(info.parent));await shot('medical-request');await p.getByRole('button',{name:'記入をお願いする',exact:true}).click();await p.waitForLoadState('networkidle');
   await go(info.parent_medical);await p.locator('[name=blood_type]').selectOption('A型');await fill('primary_doctor_name','見本こども医院');await p.locator('[name=xray_answer][value=agree]').check();await p.getByRole('button',{name:'回答を確認する',exact:true}).click();await p.getByRole('button',{name:'この内容で回答する',exact:true}).click();await p.getByRole('heading',{name:'園に回答を送りました',exact:true}).waitFor();
   await go(info.medical);await shot('medical-review');await fill('note','かかりつけ医の電話番号をご確認ください。');await shot('medical-return');await p.getByRole('button',{name:'書き直しをお願いする',exact:true}).click();await p.waitForLoadState('networkidle');
   await go(info.parent_medical);await fill('primary_doctor_phone','000-0000-0201');await p.getByRole('button',{name:'回答を確認する',exact:true}).click();await p.getByRole('button',{name:'この内容で回答する',exact:true}).click();await p.getByRole('heading',{name:'園に回答を送りました',exact:true}).waitFor();
   await go(info.medical);await p.getByRole('button',{name:'確認して反映する',exact:true}).click();await p.waitForLoadState('networkidle');await shot('medical-approved');await go('/children/1/health/profile');assert.equal(await p.locator('[name=primary_doctor_phone]').inputValue(),'000-0000-0201');await shot('profile-basic',p.locator('form section').first());await shot('profile-consent',p.locator('section').first());
   await go('/daily-contacts/');await shot('daily-list');
   const link=p.locator('a[href*="/daily-contacts/1?"]').first();await link.waitFor();await link.click();await p.locator('#daily-reply-form').waitFor();await shot('daily-received','.parent-contact');
   await fill('reply_message','元気に遊び、お昼もよく食べました。');await shot('daily-reply','#daily-reply-form');await p.getByRole('button',{name:'下書き保存',exact:true}).click();await p.waitForTimeout(300);await p.getByRole('button',{name:'保護者に公開',exact:true}).click();await p.locator('#reply-publish-dialog[open]').waitFor();await shot('daily-confirm','#reply-publish-dialog');await p.locator('[data-publish=confirm]').click();await p.waitForTimeout(400);assert((await p.locator('#reply-state').innerText()).includes('公開済み'));
   await go(info.contact);await shot('parent-reply','#daily-contact-reply');
   report.checks.push('健康一覧の絞り込み、医療の依頼・送信・書き直し・再回答・反映、日次連絡の受取・返信下書き・公開確認・保護者表示');
  }else{
   await go('/billing/');await shot('billing-home');await p.locator('[data-reopen-export]').first().click();await shot('billing-cancel','#billing-reopen-dialog');await p.getByRole('button',{name:'戻る',exact:true}).click();assert.equal(await p.locator('[data-reopen-export]').count(),2);
   await p.locator('[data-reopen-export]').first().click();await fill('reason','写真代を訂正');await p.locator('[name=confirmed_unsubmitted]').check();await shot('billing-confirm','#billing-reopen-dialog');await p.getByRole('button',{name:'取消して修正へ進む',exact:true}).click();await p.waitForURL(/child-charges/);
   const photo=p.locator('[name^=amount_temp_photo_]');assert.equal(await photo.inputValue(),'300');await photo.fill('500');await shot('billing-edit');await p.getByRole('button',{name:'保存',exact:true}).first().click();await p.waitForURL(/message=/);
   await p.getByRole('link',{name:'請求詳細',exact:true}).click();await p.locator('form[action$="/profile"]').waitFor();await shot('billing-account','#account-profile');assert.equal(await p.locator('form[action$="/profile"] input:not([type=hidden]),form[action$="/profile"] select').count(),12);await fill('note','口座情報を確認した見本');await p.getByRole('button',{name:'口座情報を保存',exact:true}).click();await p.waitForURL(/message=/);assert.equal(await p.locator('[name=note]').inputValue(),'口座情報を確認した見本');
   await p.getByRole('link',{name:'園児選択へ戻る',exact:true}).click();await p.getByRole('link',{name:'請求一覧へ戻る',exact:true}).click();await shot('billing-recreate');await p.getByRole('button',{name:'Zengin作成',exact:true}).click();await p.waitForURL(/message=/);await shot('billing-recreated');
   assert((await p.locator('main').innerText()).includes('取消済み'));report.checks.push('取消で戻る、理由と未提出確認、同月金額300→500保存、口座12項目の保存・再表示、再出力と取消履歴');
  }
  assert.deepStrictEqual(report.errors,[]);report.passed=true;
 }finally{fs.writeFileSync(path.join(evidence,'capture-'+mode+'.json'),JSON.stringify(report,null,2));await browser.close();}
 console.log(JSON.stringify(report));
})().catch(e=>{console.error(e);process.exit(1)});
