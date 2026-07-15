// First-run tab tour of the real Brain panel for the install video. Viewport is
// the app window's content area (1520x848); the compositor adds the Mac window
// chrome. Fresh-install stub state: nothing paired, nothing indexed, cloud off.
// In-page cursor clicks each sidebar tab and scrolls the .content pane.
// Usage: node yt_tour.js /tmp/yt/tour     (needs /tmp/panel_demo.html rendered)
const { chromium } = require(process.env.PLAYWRIGHT_HOME || '/opt/node22/lib/node_modules/playwright');
const http = require('http'); const fs = require('fs'); const path = require('path');
const OUT = process.argv[2] || '/tmp/yt/tour';
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

const TABS = [
  ['home',    'home. what’s connected, what isn’t. everything says off because it just met you', 620],
  ['day',     'your day. brief, agenda, reminders. builds itself overnight once there’s data', 560],
  ['mind',    'intelligence. keyword search needs zero models. or plug in whatever you already run', 900],
  ['reach',   'connections. phone and glasses pair with one code', 560],
  ['privacy', 'privacy. every byte that leaves gets counted here. incognito kills everything', 620],
  ['plugins', 'plugins. integrity check, capability scan, smoke test. every one, including mine', 620],
  ['caps',    'capabilities. optional powers, one-click. the good ones ship as packs', 620],
  ['learn',   'learn. the docs live in the app, with the actual card each feature draws', 560],
  ['advanced','advanced. activity, health, maintenance. the boring tab that saves you later', 620],
];

(async()=>{
  await new Promise(r=>srv.listen(8816,r));
  const b = await chromium.launch({ executablePath: process.env.CHROME_BIN || '/opt/pw-browsers/chromium-1194/chrome-linux/chrome' });
  const ctx = await b.newContext({ viewport:{width:1520,height:848}, deviceScaleFactor:1, colorScheme:'dark' });
  const p = await ctx.newPage();
  await p.addInitScript(()=>{
    const STATUS={model:'keyword',cloud:false,cloud_ready:false,incognito:false,quiet:false,phone_ago:null,
      stats:{files:0,passages:0},missing:[],cloud_calls:0,index_ago:null,email_docs:0};
    window.fetch=(u)=>Promise.resolve({ok:true,json:()=>Promise.resolve(
      String(u).includes('/dreamlayer/status')?STATUS:
      {config:{},status:STATUS,folders:[],plan:{},people:[],items:[],packs:[],plugins:[],agents:[],cals:[],lists:[]}),
      text:()=>Promise.resolve('')});
  });
  await p.goto('http://localhost:8816/', { waitUntil:'domcontentloaded' });
  await p.waitForTimeout(800);
  await p.addStyleTag({content:'#modelStatus,#apiStatus,.shimmer{display:none!important}.mstat:empty{display:none!important}'});
  await p.evaluate(CURSOR_JS);

  let fi=0; const caps=[]; let CAP='first open. nothing is set up, nothing has phoned home. let’s look around';
  let cx=1400, cy=790;
  const setCur=(x,y)=>p.evaluate(([x,y])=>window.__cur(x,y),[x,y]);
  const snap=async(n=1)=>{ for(let i=0;i<n;i++){ await p.screenshot({path:`${OUT}/seq/f_${String(fi).padStart(4,'0')}.png`}); caps.push(CAP); fi++; } };
  const ease=t=>t*t*(3-2*t);
  async function moveTo(x,y,steps=12){ const sx=cx,sy=cy; for(let k=1;k<=steps;k++){ const e=ease(k/steps); cx=sx+(x-sx)*e; cy=sy+(y-sy)*e; await setCur(cx,cy); await snap(1);} cx=x;cy=y; }
  async function clickTab(id){
    const box=await p.evaluate((tid)=>{const el=document.querySelector(`#side button[data-p="${tid}"]`);const r=el.getBoundingClientRect();return {x:r.left+r.width/2,y:r.top+r.height/2};},id);
    await moveTo(box.x,box.y,12);
    await p.evaluate(([x,y])=>window.__press(x,y,true),[cx,cy]); await snap(2);
    await p.evaluate(([x,y,tid])=>{window.__ripple(x,y);showPage(tid);},[cx,cy,id]);
    await snap(2);
    await p.evaluate(([x,y])=>window.__press(x,y,false),[cx,cy]); await snap(2);
  }
  const scrollContent=async(px,n)=>{ for(let i=0;i<n;i++){ await p.evaluate((pp)=>{document.querySelector('.content').scrollTop+=pp;},px); await snap(1);} };

  await setCur(cx,cy); await snap(26);              // boot hold on Home
  for(const [id,line,scrollPx] of TABS){
    CAP=line;
    await clickTab(id);
    await snap(12);
    await scrollContent(28, Math.round(scrollPx/28));
    await snap(14);
  }
  CAP='that’s the whole app. local until you say otherwise';
  await moveTo(1400,790,10); await snap(24);
  fs.writeFileSync(`${OUT}/caps.json`, JSON.stringify(caps));
  console.log('tour frames', fi);
  await b.close(); srv.close();
})();
