// New-experience walkthrough: whole app in frame. Start on the Home dashboard,
// click "Intelligence" in the sidebar, scroll to Model, click "Your API" —
// the auto-scan finds local agents (stubbed discovery results; the UI is real) —
// then one-tap Connect and the green on-device state + "Your API is now the
// brain" toast. Cursor moves/clicks/scrolls are all driven.
const { chromium } = require(process.env.PLAYWRIGHT_HOME || '/opt/node22/lib/node_modules/playwright');
const http = require('http'); const fs = require('fs'); const path = require('path');
const OUT = process.argv[2] || '/tmp/panel_shots3';
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
  const r=document.createElement('div'); r.id='fauxripple';
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

(async ()=>{
  await new Promise(r=>srv.listen(8814,r));
  const browser = await chromium.launch({ executablePath: process.env.CHROME_BIN || '/opt/pw-browsers/chromium-1194/chrome-linux/chrome' });
  const ctx = await browser.newContext({ viewport:{width:1280,height:860}, deviceScaleFactor:2, colorScheme:'dark' });
  const page = await ctx.newPage();
  await page.addInitScript(()=>{
    const J=(o)=>Promise.resolve({ok:true,json:()=>Promise.resolve(o),text:()=>Promise.resolve('')});
    const STATUS={model:'keyword',cloud:false,cloud_ready:false,incognito:false,quiet:false,phone_ago:44,
      stats:{files:12,passages:148},missing:[],cloud_calls:0,index_ago:420,email_docs:0};
    const AGENTS={agents:[
      {label:'Ollama',provider:'ollama',base_url:'http://localhost:11434',models:['llama3.2','qwen2.5:7b']},
      {label:'LM Studio',provider:'custom',base_url:'http://localhost:1234/v1',models:['hermes-3-8b']}]};
    window.fetch=(u,opt)=>{
      const url=String(u);
      if(url.includes('/api/discover')) return new Promise(res=>setTimeout(()=>res({ok:true,json:()=>Promise.resolve(AGENTS),text:()=>Promise.resolve('')}),700));
      if(url.includes('/dreamlayer/status')) return J(STATUS);
      return J({config:{},status:STATUS,folders:['/Users/you/Documents/Notes'],plan:{},people:[],items:[],packs:[],plugins:[],agents:[]});
    };
  });
  await page.goto('http://localhost:8814/', { waitUntil:'domcontentloaded' });
  await page.waitForTimeout(700);
  await page.addStyleTag({content:'#modelStatus,#apiStatus{display:none!important} input:focus,select:focus{outline:2px solid var(--memory)!important;outline-offset:1px}'});
  await page.evaluate(CURSOR_JS);

  let fi=0; const caps=[]; let CAP=['',''];
  let cx=1180, cy=800;
  const setCur=(x,y)=>page.evaluate(([x,y])=>window.__cur(x,y),[x,y]);
  const snap=async(n=1)=>{ for(let i=0;i<n;i++){ await page.screenshot({path:`${OUT}/seq/f_${String(fi).padStart(4,'0')}.png`}); caps.push(CAP.slice()); fi++; } };
  const cap=(t,s)=>{CAP=[t,s];};
  const ease=(t)=>t*t*(3-2*t);
  async function moveTo(x,y,steps=14){ const sx=cx,sy=cy; for(let k=1;k<=steps;k++){ const e=ease(k/steps); cx=sx+(x-sx)*e; cy=sy+(y-sy)*e; await setCur(cx,cy); await snap(1);} cx=x;cy=y; }
  async function centerOf(sel){ return await page.evaluate((s)=>{const el=document.querySelector(s);const r=el.getBoundingClientRect();return {x:r.left+Math.min(r.width/2,140),y:r.top+r.height/2};},sel); }
  async function click(sel, doAction){ const p=await centerOf(sel); await moveTo(p.x,p.y,14);
    await page.evaluate(([x,y])=>window.__press(x,y,true),[cx,cy]); await snap(2);
    await page.evaluate(([x,y])=>window.__ripple(x,y),[cx,cy]);
    if(doAction) await doAction();
    await snap(3);
    await page.evaluate(([x,y])=>window.__press(x,y,false),[cx,cy]); await snap(2);
  }
  // the panel's .content pane is the scroller (height:100vh; overflow-y:auto)
  const scrollDown=async(px,n=1)=>{ for(let i=0;i<n;i++){ await page.evaluate((p)=>{const c=document.querySelector('.content')||document.scrollingElement; c.scrollTop+=p;},px); await snap(1);} };

  // 1) the dashboard
  cap('The Brain dashboard','everything the Mac mini runs, at a glance');
  await setCur(cx,cy); await snap(22);

  // 2) sidebar -> Intelligence
  cap('Open Intelligence','choose your AI and point it at your files');
  await click('#side button[data-p="mind"]', async()=>{ await page.evaluate(()=>showPage('mind')); });
  await page.waitForTimeout(200); await snap(8);

  // 3) scroll to the Model card
  cap('The Model card','keyword · Ollama · or your own API');
  await (async()=>{ for(let s=0;s<60;s++){
    const ok=await page.evaluate(()=>{const el=[...document.querySelectorAll('h2')].find(h=>h.textContent.trim()==='Model');const r=el.getBoundingClientRect();return r.top<140&&r.top>-40;});
    if(ok)break; await scrollDown(64,1);} })();
  await snap(8);

  // 4) click "Your API" -> auto-scan kicks off
  cap('Click: Your API','it scans this Mac for agents already running');
  await click('#modelSeg button[data-m="api"]', async()=>{ await page.evaluate(()=>pickModel('api')); });
  await snap(10);                       // shimmer while scanning (real loading state)
  await page.waitForTimeout(650); await snap(6);

  // 5) results
  cap('Found, zero typing','Ollama and LM Studio, right on this Mac');
  await scrollDown(34,6); await snap(16);

  // 6) one-tap Connect on Ollama (freeze load() so the confirmed state holds)
  cap('One tap: Connect','no endpoint, no key — it is already local');
  await page.evaluate(()=>{ window.load=()=>{}; });
  await click('#apiFound .mstat:nth-of-type(1) button.sm', async()=>{ await page.evaluate(()=>connectFound(0)); });
  await page.waitForTimeout(250);
  // 7) show the green on-device state + toast
  cap('Connected — on your device','"Your API is now the brain" · local, private, incognito-proof');
  await scrollDown(40,8);
  for(let h=0;h<30;h++){ await page.evaluate(()=>document.getElementById('toast').classList.add('show')); await snap(1); }
  await moveTo(1180,800,12); await snap(8);

  fs.writeFileSync(`${OUT}/caps.json`, JSON.stringify(caps));
  console.log('frames', fi);
  await browser.close(); srv.close();
})();
