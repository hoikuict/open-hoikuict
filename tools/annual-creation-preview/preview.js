(() => {
  'use strict';
  const copy=x=>JSON.parse(JSON.stringify(x));
  const originals=copy(window.ANNUAL_PREVIEW_FIXTURES);
  let classes=copy(originals), mode='empty', records=new Map(), lastClass=1, nextId=100, changed=false;
  const key=(id,year)=>id+':'+year;
  const empty=()=>Array.from({length:4},()=>['','']);
  const samples=[
    ['少しずつ園での生活に慣れ、保育者と一緒に身の回りのことをしようとする姿が見られた。','好きな遊びを見つけ、保育者や友達と楽しさを共有する姿が増えた。'],
    ['暑い日は休息と水分補給を取り入れ、生活リズムを整えながら過ごした。','水や砂の感触を楽しみ、自分なりに試したり工夫したりしていた。'],
    ['自分の思いを言葉や身振りで伝え、相手の気持ちにも少しずつ気付くようになった。','季節の自然に触れながら、友達とイメージを共有して遊ぶ姿が見られた。'],
    ['できることが増え、次のクラスへの期待を持って落ち着いて過ごした。','一年間に楽しんだ遊びを繰り返し、友達との関わりが深まった。']
  ];
  function create(id,year) {
    const c=classes.find(c=>c.id===id), previous=originals.find(c=>c.id===id);
    const saved=['partial','filled','error','request-error','approved'].includes(mode) && year===2026;
    let reflection=empty();
    if(saved&&['partial','request-error'].includes(mode))reflection[0]=copy(samples[0]);
    if(saved&&(mode==='filled'||mode==='approved'))reflection=copy(samples);
    const sheet=copy(c.sheet);
    return {document_id:saved?++nextId:null,lock_version:saved?1:0,classroom_id:id,classroom_name:c.name,school_year:year,age:c.age,nursery_name:'見本保育園',
      owner_name:mode==='no-teacher'?'':c.teachers.join('・'),sheet,editable:!(saved&&mode==='approved'),reflection_editable:true,
      status:saved&&mode==='approved'?'承認済み':saved?'下書き':'未保存',sources:[{key:sheet.origin.key,title:sheet.source.source.title,year:2026,class_name:'原本の見本クラス'}],
      references:year===2026?copy(c.references):[],source_error:null,previous:[{document_id:900+id,revision_id:10+id,title:`${year-1}年度 ${previous.name} の見本年案`,status:'承認済み'}],
      reflection,reflection_periods:copy(c.reflection_periods),reflection_columns:copy(c.reflection_columns),reflection_saved_at:saved&&mode!=='error'?'2026-10-11 09:00':null,
      created_at:saved?'2026-10-11 09:00':null};
  }
  function context(id,year){
    const k=key(id,year);
    if(!records.has(k)){const b=create(id,year);if(b.document_id)records.set(k,copy(b));return b;}
    return copy(records.get(k));
  }
  function registrationNote(){
    const c=classes.find(c=>c.id===lastClass);
    document.getElementById('preview-note').textContent=changed?`登録情報を変更しました：${c.name}／${c.teachers.join('・')}。保存内容を開き直すと、この年案の作成時の情報が保持されることを確認できます。`:'新規作成では登録された担任を表示します。反省の入力欄は空欄です。';
    document.querySelectorAll('#annual-classroom option').forEach(option=>{option.textContent=classes.find(c=>c.id===Number(option.value)).name;});
  }
  window.AnnualMock={
    mode:()=>mode,
    reviewError:()=>mode==='request-error',
    initial(){return context(lastClass,2026);},
    reopen(boot){return context(boot.classroom_id,boot.school_year);},
    async api(route,options={},boot){
      await new Promise(resolve=>setTimeout(resolve,180));
      if(route.startsWith('context?')){
        const p=new URLSearchParams(route.split('?')[1]);lastClass=Number(p.get('classroom_id'));const year=Number(p.get('school_year'));
        if(!Number.isInteger(year)||year<1900||year>2199)throw new Error('年度は1900〜2199年で指定してください。入力内容は保持しています。');
        const b=context(lastClass,year);
        if(p.has('previous_id')&&!b.document_id){b.sheet.origin={kind:'previous',document_id:Number(p.get('previous_id')),revision_id:Number(p.get('revision_id'))};b.sheet.baseline_label=`${year-1}年度の見本年案`;}
        registrationNote();return b;
      }
      if(route==='save'){
        const p=JSON.parse(options.body);
        if(!p.owner_name.trim())throw new Error('担任名を入力してください。登録がない場合は手入力できます。');
        const b=copy(boot);delete b.reflection_draft;
        b.document_id=b.document_id||++nextId;b.lock_version++;b.created_at=b.created_at||'2026-10-11 09:15';
        b.owner_name=p.owner_name;b.sheet.fields=copy(p.fields);b.status='下書き';
        for(const [id,field] of Object.entries(b.sheet.fields))field.position_ratio=boot.sheet.fields[id].position_ratio;
        records.set(key(b.classroom_id,b.school_year),copy(b));return b;
      }
      throw new Error('モックで未対応の操作です。');
    },
    async saveReflection(boot,values){
      await new Promise(resolve=>setTimeout(resolve,220));
      if(mode==='error')throw new Error('保存できませんでした。入力内容は残っています。時間をおいて再度保存してください。（確認用のエラー）');
      if(!boot.document_id)throw new Error('先に年案の下書きを保存してください。');
      const b=records.get(key(boot.classroom_id,boot.school_year));
      b.reflection=copy(values);b.reflection_saved_at='2026-10-11 09:20';return copy(b);
    }
  };
  document.getElementById('preview-state').addEventListener('change',e=>{
    const current=window.AnnualMock.current?.();
    if(current&&(current.planDirty||current.reflectionDirty)&&!confirm('入力中の内容を取り消して、確認する状態を切り替えますか？')){e.target.value=mode;return;}
    mode=e.target.value;records.clear();classes=copy(originals);changed=false;window.ReflectionReview.reset();registrationNote();window.dispatchEvent(new Event('annual-preview-reset'));document.getElementById('daily-preview-frame').contentWindow?.postMessage({kind:'daily-preview-reset',mode},location.origin);
  });
  document.getElementById('preview-reopen').addEventListener('click',()=>window.dispatchEvent(new Event('annual-preview-reopen')));
  document.getElementById('preview-registration').addEventListener('click',()=>{
    const current=window.AnnualMock.current?.();
    if(!current?.boot.document_id){document.getElementById('preview-note').textContent='先に年案を保存してください。保存後に登録情報を変更しても、年案の情報が変わらないことを試せます。';return;}
    const c=classes.find(c=>c.id===lastClass);changed=true;c.name=originals.find(x=>x.id===lastClass).name+'（名称変更後）';c.teachers=['新しい担任A','新しい担任B'];registrationNote();
  });
  document.addEventListener('click',e=>{
    const a=e.target.closest('a');if(!a)return;
    if(a.matches('.annual-document-link')){e.preventDefault();document.getElementById('preview-note').textContent='確認用モックです。承認後の反省入力は、上部の「年案承認済み」で試せます。';}
    if(a.getAttribute('href')?.includes('-example')){e.preventDefault();document.getElementById('preview-note').textContent='架空の参考資料です。外部のDriveには接続しません。';}
  });
  document.addEventListener('submit',e=>e.preventDefault());
})();
