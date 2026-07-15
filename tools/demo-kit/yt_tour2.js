// v2 tab tour: the app as it actually looks in use. Rich demo-state stubs
// (same Marcus/Priya/Dana narrative as the app's own Demo Mode) so every page
// has real content, and each tab scrolls its FULL height, slower. No captions.
// Usage: node yt_tour2.js /tmp/yt/tour2      (needs /tmp/panel_demo.html)
const { chromium } = require(process.env.PLAYWRIGHT_HOME || '/opt/node22/lib/node_modules/playwright');
const http = require('http'); const fs = require('fs'); const path = require('path');
const OUT = process.argv[2] || '/tmp/yt/tour2';
fs.mkdirSync(path.join(OUT,'seq'), { recursive: true });
const HTML = fs.readFileSync('/tmp/panel_demo.html');
const srv = http.createServer((q,r)=>{ r.setHeader('Content-Type','text/html'); r.end(HTML); });

const CURSOR_JS = `
(()=>{
  const c=document.createElement('div'); c.id='fauxcur';
  c.innerHTML='<svg width="26" height="26" viewBox="0 0 24 24"><path d="M4 2 L4 20 L8.6 15.4 L11.6 22 L14.4 20.8 L11.5 14.4 L18 14 Z" fill="#fff" stroke="#0b0b0b" stroke-width="1.3" stroke-linejoin="round"/></svg>';
  Object.assign(c.style,{position:'fixed',left:'0',top:'0',zIndex:99999,pointerEvents:'none',
    transform:'translate(-2px,-2px)',filter:'drop-shadow(0 2px 3px rgba(0,0,0,.55))'});
  document.body.appendChild(c);
  const r=document.createElement('div');
  Object.assign(r.style,{position:'fixed',left:'0',top:'0',width:'10px',height:'10px',borderRadius:'50%',
    zIndex:99998,pointerEvents:'none',border:'2px solid rgba(47,212,196,.9)',opacity:'0',transform:'translate(-50%,-50%) scale(1)'});
  document.body.appendChild(r);
  window.__cur=(x,y)=>{c.style.transform='translate('+(x-2)+'px,'+(y-2)+'px)';};
  window.__press=(x,y,down)=>{c.style.transform='translate('+(x-2)+'px,'+(y-2)+'px) scale('+(down?0.86:1)+')';};
  window.__ripple=(x,y)=>{r.style.left=x+'px';r.style.top=y+'px';r.style.transition='none';
    r.style.opacity='0.9';r.style.transform='translate(-50%,-50%) scale(0.4)';
    requestAnimationFrame(()=>{r.style.transition='transform .45s ease-out,opacity .45s ease-out';
      r.style.opacity='0';r.style.transform='translate(-50%,-50%) scale(3.4)';});};
})();`;

// rich demo-state stub, matching the shapes each panel loader reads
const STUB_JS = `
(()=>{
  const now = Math.floor(Date.now()/1000);
  const STATUS = {model:'keyword',cloud:false,cloud_ready:false,incognito:false,quiet:false,
    phone_ago:44,stats:{files:12,passages:148},missing:[],cloud_calls:0,index_ago:420,email_docs:38};
  const DATA = {
    '/dreamlayer/status': STATUS,
    '/dreamlayer/calendar': {items:[
      {title:'Standup',ts:now+3600,place:'Zoom',source:'calendar',calendar:'Work'},
      {title:'Send Marcus the signed lease',ts:now+7200,place:''},
      {title:'Priya\\u2019s ceramics class',ts:now+28800,place:'Clay & Co.',source:'calendar',calendar:'Personal'}]},
    '/dreamlayer/people': {items:[
      {name:'Marcus Reyes',note:'Landlord \\u00b7 Alder Property Co.',tags:['landlord'],source:'contacts'},
      {name:'Priya Anand',note:'Met at the Overpass show',tags:['ceramics'],source:''}]},
    '/dreamlayer/social/people': {people:[
      {name:'Dana Osei',relation:'coworker',notes:['Northlight \\u00b7 last seen at standup'],debts:['owes you: the Q3 mockups'],last_seen:'standup'},
      {name:'Marcus Reyes',relation:'landlord',notes:[],debts:['you owe: the signed lease']}]},
    '/dreamlayer/reminders': {sync:true,lists:['Reminders','Work'],selected:[],last_sync:now-1200,items:[
      {title:'Send Marcus the signed lease',ts:now+7200,list:'Reminders'},
      {title:'Pick up the bike \\u00b7 4th & Alder, north rack',ts:0,list:'Reminders'},
      {title:'Review Dana\\u2019s Q3 mockups',ts:now+86400,list:'Work'}]},
    '/dreamlayer/history': {items:[
      {kind:'ask',query:'where\\u2019s the lease?',text:'Lease_2026_signed.pdf \\u00b7 Documents/Notes',tier:'local'},
      {kind:'ask',query:'what does Marcus owe me?',text:'Nothing \\u2014 you owe him the signed lease, due Friday',tier:'local'},
      {kind:'index',text:'Indexed 12 files \\u00b7 148 passages'},
      {kind:'pair',text:'Phone paired \\u00b7 one code'}]},
    '/dreamlayer/health': {version:'0.1.0',disk_kb:412,ollama_ms:null,uptime_s:7420,
      seams:{asr:{successes:214},hud:{successes:1892},ble:{successes:12}}},
    '/dreamlayer/capabilities': {frozen:false,
      summary:{active:4,off:1,missing:3},
      items:[
        {tier:'Memory',key:'total_recall',title:'Semantic memory \\u2014 search by meaning',state:'missing',impact:5,gain:'answers from meaning, not keywords'},
        {tier:'Memory',key:'keyword_index',title:'Keyword index over your folders',state:'active',impact:3,gain:''},
        {tier:'Perception',key:'sharp_ears',title:'Local speech \\u2014 on-device transcription',state:'active',impact:4,gain:''},
        {tier:'Perception',key:'clear_eyes',title:'Vision \\u2014 name what you look at',state:'missing',impact:4,gain:'needs the vision model pulled'},
        {tier:'Privacy',key:'guardian',title:'PII scrubbing + provenance',state:'active',impact:4,gain:''},
        {tier:'Voice',key:'juno_voice',title:'Juno\\u2019s voice \\u2014 spoken replies',state:'active',impact:3,gain:''},
        {tier:'Voice',key:'wake_word',title:'Hey Juno \\u2014 wake word on the glasses',state:'off',impact:3,gain:'enable when the hardware ships'},
        {tier:'Reach',key:'imessage_bridge',title:'Mail & iMessage bridge',state:'missing',impact:3,gain:'read your replies hands-free'}],
      packs:[
        {key:'total_recall',name:'Total Recall',tagline:'Semantic memory that actually understands \\u2014 indexed, deduped, searchable by meaning, fully offline.',impact:5,size:'1.2 GB',caps:['total_recall','embeddings','rerank'],state:'none',recommended:true},
        {key:'sharp_senses',name:'Sharp Senses',tagline:'On-device speech + vision \\u2014 captions, wake word, name what you see.',impact:4,size:'840 MB',caps:['sharp_ears','clear_eyes'],state:'partial'}]},
    '/dreamlayer/plugins': {capabilities:['cards','object_lens','shop'],installed:[
      {name:'open-food-facts',version:'0.1.0',requires:['shop','network'],official:true,description:'Rank a shelf by Open Food Facts \\u2014 Nutri-Score becomes a rating, allergens are flagged.'},
      {name:'currency-converter',version:'0.1.0',requires:['object_lens','network'],official:true,description:'Look at a foreign price tag and see it in your own money.'},
      {name:'face-synth',version:'0.1.0',requires:['cards'],official:true,description:'Your head is a MIDI controller.'}]},
    '/dreamlayer/folders': {folders:['/Users/you/Documents/Notes','/Users/you/Documents/Projects']},
    '/dreamlayer/cloud': {enabled:false,cannot_see:['your files or folders','raw audio or video','who you met or where you were','your questions (cloud is off)']},
    '/dreamlayer/token': {token:'\\u2022\\u2022\\u2022\\u2022-\\u2022\\u2022\\u2022\\u2022'},
    '/dreamlayer/memory/file': {path:'~/.dreamlayer/memory.md', text:'# memory\\n- Marcus: lease due Friday\\n- bike: 4th & Alder, north rack'},
    '/dreamlayer/calendars': {sync:true,items:[{name:'Work',on:true},{name:'Personal',on:true}]},
    '/dreamlayer/contacts': {sync:true,synced:2},
    '/dreamlayer/messages/recent': {items:[]},
  };
  const base = {config:{model:'keyword',email_enabled:true},status:STATUS,folders:['/Users/you/Documents/Notes','/Users/you/Documents/Projects'],
    plan:{},people:[],items:[],packs:[],plugins:[],agents:[],cals:[],lists:[]};
  window.fetch=(u)=>{
    const url=String(u).split('?')[0];
    for(const k in DATA){ if(url.endsWith(k)) return Promise.resolve({ok:true,json:()=>Promise.resolve(DATA[k]),text:()=>Promise.resolve('')}); }
    return Promise.resolve({ok:true,json:()=>Promise.resolve(base),text:()=>Promise.resolve('')});
  };
})();`;

const TABS = ['home','day','mind','reach','privacy','plugins','caps','learn','advanced'];

(async()=>{
  await new Promise(r=>srv.listen(8817,r));
  const b = await chromium.launch({ executablePath: process.env.CHROME_BIN || '/opt/pw-browsers/chromium-1194/chrome-linux/chrome' });
  const ctx = await b.newContext({ viewport:{width:1520,height:848}, deviceScaleFactor:1, colorScheme:'dark' });
  const p = await ctx.newPage();
  await p.addInitScript(STUB_JS);
  await p.goto('http://localhost:8817/', { waitUntil:'domcontentloaded' });
  await p.waitForTimeout(1200);
  await p.addStyleTag({content:'#modelStatus .shimmer,#apiStatus{display:none!important}'});
  await p.evaluate(CURSOR_JS);

  let fi=0; let cx=1400, cy=790;
  const setCur=(x,y)=>p.evaluate(([x,y])=>window.__cur(x,y),[x,y]);
  const snap=async(n=1)=>{ for(let i=0;i<n;i++){ await p.screenshot({path:`${OUT}/seq/f_${String(fi).padStart(4,'0')}.png`}); fi++; } };
  const ease=t=>t*t*(3-2*t);
  async function moveTo(x,y,steps=14){ const sx=cx,sy=cy; for(let k=1;k<=steps;k++){ const e=ease(k/steps); cx=sx+(x-sx)*e; cy=sy+(y-sy)*e; await setCur(cx,cy); await snap(1);} cx=x;cy=y; }
  async function clickTab(id){
    const box=await p.evaluate((tid)=>{const el=document.querySelector(`#side button[data-p="${tid}"]`);const r=el.getBoundingClientRect();return {x:r.left+r.width/2,y:r.top+r.height/2};},id);
    await moveTo(box.x,box.y,14);
    await p.evaluate(([x,y])=>window.__press(x,y,true),[cx,cy]); await snap(2);
    await p.evaluate(([x,y,tid])=>{window.__ripple(x,y);showPage(tid);},[cx,cy,id]);
    await snap(2);
    await p.evaluate(([x,y])=>window.__press(x,y,false),[cx,cy]); await snap(2);
  }

  await setCur(cx,cy); await snap(40);              // settle on Home
  for(const id of TABS){
    await clickTab(id);
    await snap(24);                                  // read the top of the page
    // scroll the FULL page height, slower (16 px/frame), bounded for safety
    const span=await p.evaluate(()=>{const c=document.querySelector('.content');return Math.min(4200,Math.max(0,c.scrollHeight-c.clientHeight));});
    const steps=Math.ceil(span/16);
    for(let s=0;s<steps;s++){
      await p.evaluate(()=>{document.querySelector('.content').scrollTop+=16;});
      await snap(1);
    }
    await snap(26);                                  // rest at the bottom
  }
  await moveTo(1400,790,10); await snap(30);
  console.log('tour2 frames', fi);
  await b.close(); srv.close();
})();
