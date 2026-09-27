// State integration tests use the real view/controller files and no browser I/O.
const {test}=require('node:test');
const assert=require('node:assert/strict');
const vm=require('node:vm');
const fs=require('node:fs');
const path=require('node:path');
function fixture(){
  const elements=new Map();
  function element(id){if(!elements.has(id))elements.set(id,{textContent:'',innerHTML:'',value:'',disabled:false,checked:false,childNodes:[],classList:{toggle(){}},addEventListener(){},querySelector(){return null;},querySelectorAll(){return [];},showModal(){},close(){},focus(){},replaceChildren(){this.innerHTML='';},remove(){},setAttribute(){}});return elements.get(id);}
  const context=vm.createContext({document:{querySelector:element,getElementById:element},location:{hash:'#test-only'},window:{scrollTo(){}},setTimeout(){},clearTimeout(){},fetch:()=>new Promise(()=>{})});
  for(const file of ['views.js','guided.js','guide-actions.js','server-wizard.js'])vm.runInContext(fs.readFileSync(path.join(__dirname,'beta_setup/ui',file),'utf8'),context);
  vm.runInContext("render=()=>{}; fail=message=>{s.error=message;return false;}; saveDraft=async()=>{}; required=keys=>keys.every(k=>!!s.v[k]);",context);
  return {run:code=>vm.runInContext(code,context),element};
}
test('provider round trip keeps drafts but invalidates acceptance',()=>{
  const {run}=fixture();
  run("setMailProvider('gmail');change('mailFrom','first@example.invalid');change('smtpPassword','abcdefghijklmnop');s.checks.mail=true;s.v.mailReceived=true;setMailProvider('custom');s.v.smtpHost='smtp.other.invalid';setMailProvider('gmail');");
  assert.equal(run('s.v.smtpPassword'),'abcdefghijklmnop');
  assert.equal(run('s.v.smtpHost'),'smtp.gmail.com');
  assert.equal(run('s.v.smtpUser'),'first@example.invalid');
  assert.equal(run('!!s.checks.mail||s.v.mailReceived'),false);
});
test('sender changes reset Google preparation, password, acceptance and receipt',()=>{
  const {run}=fixture();
  run("setMailProvider('gmail');change('mailFrom','first@example.invalid');s.v.smtpPassword='abcdefghijklmnop';s.v.googleReady=true;s.checks.mail=true;s.v.mailReceived=true;change('mailFrom','second@example.invalid');");
  assert.equal(run('s.v.smtpUser'),'second@example.invalid');
  assert.equal(run('s.v.smtpPassword'),'');
  assert.equal(run('s.v.googleReady||s.v.mailReceived||!!s.checks.mail'),false);
});
test('unchanged blur events retain proof; recipient changes remove visible acceptance',()=>{
  const {run,element}=fixture();
  run("s.v.testRecipient='one@example.invalid';s.checks.mail=true;s.v.mailReceived=true;change('testRecipient','one@example.invalid');");
  assert.equal(run('s.checks.mail'),true);
  element('mail-result').innerHTML='accepted';
  run("change('testRecipient','two@example.invalid');");
  assert.equal(element('mail-result').innerHTML,'');
  assert.equal(element('mailReceived').disabled,true);
  assert.equal(run('!!s.checks.mail||s.v.mailReceived'),false);
});
test('network changes invalidate the related user acknowledgements and checks',()=>{
  const {run}=fixture();
  run("s.v.ipReserved=s.v.dnsReady=s.v.networkConfirmed=true;s.checks.dns=true;change('ip','192.168.1.20');");
  assert.equal(run('s.v.ipReserved||s.v.dnsReady||s.v.networkConfirmed||!!s.checks.dns'),false);
  run("s.v.domainReady=true;change('hostname','new.garden.org');");
  assert.equal(run('s.v.domainReady'),false);
});
test('reopening resumes substeps without restoring proofs',async()=>{
  const {run}=fixture();
  run("s.local=true;s.v.smtpHost='smtp.gmail.com';s.v.mailProvider='gmail';s.checks={pc:true,dns:true,mail:true};s.v.mailReceived=true;resumeGuide({flow:'lan',step:2,guide:{netStep:7,tokenStep:2,mailStep:3}});");
  await run("handleGuidedAction('start-lan')");
  assert.equal(run('s.step'),2);
  assert.equal(run('s.mailStep'),3);
  assert.equal(run('Object.keys(s.checks).length'),0);
  assert.equal(run('s.v.mailReceived'),false);
});
test('network cancellation restores inputs without removing installed state',async()=>{
  const {run}=fixture();
  run("s.local=true;s.flow='lan';s.v.ip='192.168.1.10';captureNetworkStart();s.v.ip='192.168.1.20';confirmDialog=(title,message,label,action)=>{dialogAction=action;};");
  await run("handleGuidedAction('guide-cancel')");await run('dialogAction()');
  assert.equal(run('s.v.ip'),'192.168.1.10');
  assert.equal(run('s.local'),true);
  assert.equal(run('s.flow'),'home');
});
test('navigation never sends mail; only explicit test does and retry failure clears proof',async()=>{
  const {run}=fixture();
  run("s.v.mailProvider='gmail';s.mailStep=0;let sent=0;api=async(path,payload)=>{if(payload?.kind==='mail')sent++;return {message:'accepted'};};");
  await run("handleGuidedAction('mail-next')");
  assert.equal(run('sent'),0);
  run("Object.assign(s.v,{smtpHost:'smtp.gmail.com',smtpPort:'587',smtpUser:'one@example.invalid',mailFrom:'one@example.invalid',testRecipient:'one@example.invalid',smtpPassword:'abcd efgh ijkl mnop',googleReady:true});");
  await run("handleGuidedAction('mail-test')");
  assert.equal(run('sent'),1);assert.equal(run('s.checks.mail'),true);
  assert.equal(run('s.v.smtpPassword'),'abcdefghijklmnop');
  run("api=async()=>{const e=new Error('failed');e.code='smtp_auth_failed';throw e;};s.v.mailReceived=true;");
  await assert.rejects(run("handleGuidedAction('mail-test')"),/failed/);
  assert.equal(run('s.mailError'),'auth');assert.equal(run('!!s.checks.mail||s.v.mailReceived'),false);
});
test('apply redirects to a missing check and discarded secret caches cannot restore secrets',()=>{
  const {run}=fixture();
  run("s.flow='lan';s.step=4;s.checks={pc:true,dns:true};s.v.mailProvider='gmail';s.mailDrafts={custom:{smtpPassword:'private'}};s.networkStart={dnsToken:'private'};");
  assert.equal(run('guideApplyReady()'),false);
  assert.equal(run('s.step'),2);assert.equal(run('s.mailStep'),3);
  run('clearGuideSecrets()');
  assert.equal(run('Object.keys(s.mailDrafts).length'),0);assert.equal(run('s.networkStart.dnsToken'),'');
});
