/* Offline data adapter for the deployed monthly sheet. Never performs network I/O. */
(() => {
  'use strict';
  const contract=window.monthlySheetContract, clone=structuredClone;
  const classes=[{name:'ことり組（架空）',age:0},{name:'こりす組（架空）',age:2},{name:'ひかり組（架空）',age:5}];
  const records=new Map(),scope=(id,month,age)=>`${id}/${month}/${age}`;
  let nextId=100;
  const cell=body=>({body,origins:[]});
  function definitions(sheet,month){
    const result={},add=(key,label,section=null,item=label,ryoiki=null)=>{result[key]={label,section,item,ryoiki};};
    add('common:goal',sheet.age<3?'ねらい':'今月のねらい','クラス全体','ねらい');
    add('common:home','家庭との連携','クラス全体');add('common:review','評価・反省','クラス全体');
    if(sheet.age<3){add('common:events','行事');for(const child of sheet.children)for(const [key,label]of contract.PERSONAL)add(`${child.ref}:${key}`,label,'個人別');}
    else{
      for(const [domain,label]of contract.DOMAINS)for(const [column,title]of contract.COLUMNS)add(`group:${domain}:${column}`,`${label} / ${title}`,domain==='care'?'養護':'教育',title,label);
      add('group:food','食育','食育');const [y,m]=month.split('-').map(Number);for(let day=1;day<=new Date(y,m,0).getDate();day++)add(`event:${day}`,`${day}日 行事・活動`);
    }
    return result;
  }
  function context(id,month,age){
    id=Number(id);age=Number(age);const c=classes[id-1];
    if(!c||!/^\d{4}-(0[1-9]|1[0-2])$/.test(month)||Number(month.slice(0,4))<1900||Number(month.slice(0,4))>2199||!Number.isInteger(age)||age<0||age>5)throw Error('クラス・対象月・年齢を確認してください。');
    const saved=records.get(scope(id,month,age));if(saved)return clone(saved);
    const year=Number(month.slice(0,4)), template=contract.TEMPLATES[Math.min(age,3)];
    const sheet={schema_version:1,template_version:contract.TEMPLATE_VERSION,template_id:template[0],age,classroom_id:id,
      children:age<3?Array.from({length:8},(_,i)=>({ref:`child:${id*100+i+1}`,name:`園児${String.fromCharCode(65+i)}（見本）`,birth_date:`${year-age-1}-12-10`})) : [],fields:{}};
    return {classroom_id:id,classroom_name:c.name,target_month:month,age,sheet,owner_name:'見本の保育士',
      editable:true,edit_reason:'確認用モックです。保存はこの画面内だけに行います。',status:'未保存',document_id:null,lock_version:0,base_token:'mock',
      definitions:definitions(sheet,month),personal:contract.PERSONAL,columns:contract.COLUMNS,domains:contract.DOMAINS,template,ai:{enabled:false}};
  }
  function exampleTexts(c,field){
    if(contract.samples.COMMON[field])return contract.samples.COMMON[field];
    if(field.startsWith('child:'))return contract.samples.PERSONAL[c.age][field.split(':')[2]]||[];
    if(field==='group:food')return ['食材に興味をもち、楽しく食事をする。','食材の色や形を見比べて楽しむ。'];
    if(field.startsWith('group:')){const [,d,col]=field.split(':');return contract.samples.GROUP[d]?.[contract.COLUMNS.findIndex(([k])=>k===col)]||[];}
    return [];
  }
  function sampleFields(c,state){
    if(state==='empty'||state==='error')return {};
    const keys=Object.keys(c.definitions),result={};keys.forEach((key,i)=>{
      if(state==='partial'&&i%3!==0)return;
      const value=exampleTexts(c,key)[0];
      if(value)result[key]=cell(`【架空例】${value}`);
      else if(key==='common:events'||key==='event:10')result[key]=cell('園庭で秋探し（見本）');
    });return result;
  }
  function reset(){
    records.clear();nextId=100;
    classes.forEach((c,i)=>{for(let m=4;m<=10;m++){
      const month=`2026-${String(m).padStart(2,'0')}`,ctx=context(i+1,month,c.age);ctx.sheet.fields=sampleFields(ctx,m===10?'partial':'filled');
      ctx.status=m===10?'下書き':'承認済み';ctx.editable=m===10;ctx.document_id=nextId++;
      ctx.edit_reason=ctx.editable?'モック内で編集・保存できます。':'承認済みの見本です。閲覧のみです。';records.set(scope(i+1,month,c.age),clone(ctx));
    }});
  }
  const api=window.monthlyPreview={context,sampleFields,reset,
    summary(id,month,age){return records.has(scope(id,month,age))?context(id,month,age):null;},
    savedForClass(id){return [...records.values()].filter(c=>c.classroom_id===id).map(value=>clone(value));},
    async request(path,options={}){
      const [name,query='']=path.split('?'),params=new URLSearchParams(query),payload=JSON.parse(options.body||'{}');
      const c=context(payload.classroom_id||params.get('classroom_id'),payload.target_month||params.get('target_month'),payload.age??params.get('age'));
      if(name==='context')return c;
      if(name==='presence')return {peers:[],editable:c.editable,edit_reason:c.edit_reason};
      if(name==='save'){
        if(!c.editable)throw Error('承認済みの見本は保存できません。');
        if(!String(payload.owner_name||'').trim())throw Error('担任名を入力してください。');
        if(document.querySelector('#save-error').checked)throw Error('保存に失敗しました（見本）。「保存失敗を試す」を外して再試行してください。');
        c.sheet.fields=clone(payload.fields);c.owner_name=payload.owner_name;c.document_id ||= nextId++;c.status='下書き';c.lock_version++;
        records.set(scope(c.classroom_id,c.target_month,c.age),clone(c));api.onSave?.(c);return c;
      }
      if(name==='candidates'){
        const mode=document.querySelector('#mock-source').value;
        if(mode==='error')throw Error('参考例を読み込めません（見本）。入力は保持しています。');
        const field=params.get('field'),words=(params.get('keyword')||'').normalize('NFKC').toLowerCase().split(/\s+/).filter(Boolean);
        return {items:mode==='none'?[]:exampleTexts(c,field).map((text,i)=>({text:'【架空例】'+text,kind:'original',year:2025,age:c.age,month:Number(c.target_month.slice(5)),phrase_id:i+1,cell_id:i+1,source_key:'mock',section:c.definitions[field]?.section,item:c.definitions[field]?.label,relative_path:'確認用の架空文例',sheet:'操作見本'})).filter(row=>words.every(w=>row.text.normalize('NFKC').toLowerCase().includes(w))),has_more:false};
      }
      if(name==='history'){
        const [y,m]=c.target_month.split('-').map(Number),child=params.get('child_ref');
        return {months:[3,2,1].map(n=>{const d=new Date(y,m-1-n,1),month=`${d.getFullYear()}-${String(d.getMonth()+1).padStart(2,'0')}`,saved=records.get(scope(c.classroom_id,month,c.age));
          return {month,legacy:[],records:saved?[{classroom:saved.classroom_name,age:saved.age,status:saved.status,document_id:saved.document_id,fields:Object.fromEntries(contract.PERSONAL.map(([k])=>[k,clone(saved.sheet.fields[`${child}:${k}`]||cell(''))]))}]:[]};})};
      }
      throw Error('この機能は確認用モックでは接続していません。');
    }
  };
  reset();
})();
