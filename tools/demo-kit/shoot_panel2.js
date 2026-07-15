// Driven walkthrough of the real Brain-panel "Your API" feature with a visible
// mouse cursor: move → click (ripple) → scroll → focus input → type letter by
// letter → open the provider dropdown → pick a cloud provider. Captures the full
// app viewport per micro-step + a per-frame caption sidecar (caps.json).
const { chromium } = require(process.env.PLAYWRIGHT_HOME || '/opt/node22/lib/node_modules/playwright');
const http = require('http'); const fs = require('fs'); const path = require('path');
const OUT = process.argv[2] || '/tmp/panel_shots2';
fs.mkdirSync(path.join(OUT,'seq'), { recursive: true });
const HTML = fs.readFileSync('/tmp/panel_demo.html');
const srv = http.createServer((q,r)=>{ r.setHeader('Content-Type','text/html'); r.end(HTML); });

const CURSOR_JS = `
(()=>{
  const c=document.createElement('div'); c.id='fauxcur';
  c.innerHTML='<svg width="26" height="26" viewBox="0 0 24 24"><path d="M4 2 L4 20 L8.6 15.4 L11.6 22 L14.4 20.8 L11.5 14.4 L18 14 Z" fill="#fff" stroke="#0b0b0b" stroke-width="1.3" stroke-linejoin="round"/></svg>';
  Object.assign(c.style,{position:'fixed',left:'0',top:'0',zIndex:99999,pointerEvents:'none',
    transform:'translate(-2px,-2px)',filter:'drop-shadow(0 2px 3px rgba(0,0,0,.55))',transition:'transform .04s linear'});
  document.body.appendChild(c);
  const r=document.createElement('div'); r.id='fauxripple';
  Object.assign(r.style,{position:'fixed',left:'0',top:'0',width:'10px',height:'10px',borderRadius:'50%',
    zIndex:99998,pointerEvents:'none',border:'2px solid rgba(47,212,196,.9)',opacity:'0',transform:'translate(-50%,-50%) scale(1)'});
  document.body.appendChild(r);
  window.__cur=(x,y)=>{c.style.transform='translate('+(x-2)+'px,'+(y-2)+'px)';};
  window.__press=(x,y,down)=>{c.style.transform='translate('+(x-2)+'px,'+(y-2)+'px) scale('+(down?0.86:1)+')';};
  window.__ripple=(x,y,t)=>{r.style.left=x+'px';r.style.top=y+'px';r.style.transition='none';
    r.style.opacity='0.9';r.style.transform='translate(-50%,-50%) scale(0.4)';
    requestAnimationFrame(()=>{r.style.transition='transform .45s ease-out,opacity .45s ease-out';
      r.style.opacity='0';r.style.transform='translate(-50%,-50%) scale(3.4)';});};
})();`;

(async ()=>{
  await new Promise(r=>srv.listen(8813,r));
  const browser = await chromium.launch({ executablePath: process.env.CHROME_BIN || '/opt/pw-browsers/chromium-1194/chrome-linux/chrome' });
  const ctx = await browser.newContext({ viewport:{width:800,height:1040}, deviceScaleFactor:2, colorScheme:'dark' });
  const page = await ctx.newPage();
  await page.addInitScript(()=>{ window.fetch=()=>Promise.resolve({ok:true,json:()=>Promise.resolve({config:{},status:{},folders:[],plan:{},people:[],items:[],packs:[],plugins:[]}),text:()=>Promise.resolve('')}); });
  await page.goto('http://localhost:8813/', { waitUntil:'domcontentloaded' });
  await page.waitForTimeout(400);
  await page.addStyleTag({content:'#modelStatus,#apiStatus,.shimmer,.mstat .shimmer{display:none!important}.mstat:empty{display:none!important}#side{display:none!important} input:focus,select:focus{outline:2px solid var(--memory)!important;outline-offset:1px}'});
  await page.evaluate(()=>{ try{showPage('mind');}catch(e){} });
  // isolate the Model section so the feature fills the frame and the scroll is meaningful
  await page.evaluate(()=>{ document.querySelectorAll('section').forEach(s=>{ if((s.querySelector('h2')?.textContent||'').trim()!=='Model') s.style.display='none'; }); const se=document.scrollingElement||document.documentElement; se.scrollTop=0; });
  await page.evaluate(CURSOR_JS);
  await page.waitForTimeout(200);
  const scrollDown=async(px,n=1)=>{ for(let i=0;i<n;i++){ await page.evaluate((p)=>{const se=document.scrollingElement||document.documentElement; se.scrollTop+=p;},px); await snap(1);} };

  let fi=0; const caps=[]; let CAP=['',''];
  let cx=740, cy=980;                          // cursor starts bottom-right
  const setCur=(x,y)=>page.evaluate(([x,y])=>window.__cur(x,y),[x,y]);
  const snap=async(n=1)=>{ for(let i=0;i<n;i++){ await page.screenshot({path:`${OUT}/seq/f_${String(fi).padStart(4,'0')}.png`}); caps.push(CAP.slice()); fi++; } };
  const cap=(t,s)=>{CAP=[t,s];};
  const ease=(t)=>t*t*(3-2*t);
  async function moveTo(x,y,steps=16){ const sx=cx,sy=cy; for(let k=1;k<=steps;k++){ const e=ease(k/steps); cx=sx+(x-sx)*e; cy=sy+(y-sy)*e; await setCur(cx,cy); await snap(1);} cx=x;cy=y; }
  async function centerOf(sel){ return await page.evaluate((s)=>{const el=document.querySelector(s);const r=el.getBoundingClientRect();return {x:r.left+Math.min(r.width/2,120),y:r.top+r.height/2};},sel); }
  async function click(sel, doAction){ const p=await centerOf(sel); await moveTo(p.x,p.y,16);
    await page.evaluate(([x,y])=>window.__press(x,y,true),[cx,cy]); await snap(2);
    await page.evaluate(([x,y])=>window.__ripple(x,y),[cx,cy]);
    if(doAction) await doAction();
    await snap(3);
    await page.evaluate(([x,y])=>window.__press(x,y,false),[cx,cy]); await snap(3);
  }
  async function typeInto(sel, text, setter){ // letter by letter with focus caret
    await page.evaluate((s)=>document.querySelector(s).focus(), sel);
    for(let k=1;k<=text.length;k++){ await setter(text.slice(0,k)); await snap(2); }
    await snap(3);
  }
  const setBase=(v)=>page.evaluate((v)=>{const el=document.getElementById('abase');el.value=v;el.dispatchEvent(new Event('input'));},v);
  const setModelV=(v)=>page.evaluate((v)=>{document.getElementById('amodel').value=v;},v);

  // ---- walkthrough ----
  cap('Intelligence → Model','plug in any API as your brain'); await setCur(cx,cy); await snap(8);
  // click "Your API"
  cap('Click: Your API','the Brain becomes your primary answerer');
  await click('#modelSeg button[data-m="api"]', async()=>{ await page.evaluate(()=>pickModel('api')); });
  await page.waitForTimeout(150); await snap(6);
  // scroll down a touch to reveal the fields
  cap('Scroll to the fields','pick a shape, paste the endpoint');
  await scrollDown(20,8);
  await snap(4);
  // click the endpoint input and type a local LM Studio / Hermes endpoint
  cap('Type a local endpoint','LM Studio · Hermes · vLLM — on your machine');
  await click('#abase', null);
  await typeInto('#abase','http://localhost:1234/v1', setBase);
  cap('On your device','questions never leave · works in incognito'); await snap(24);
  // model name
  cap('Name the model','');
  await click('#amodel', null);
  await typeInto('#amodel','hermes-3-8b', setModelV);
  await snap(10);
  // open provider dropdown -> fake menu -> pick OpenAI
  cap('Open the provider dropdown','OpenAI · Anthropic · Gemini · OpenRouter · Ollama');
  const menu = async()=>{ await page.evaluate(()=>{
      const sel=document.getElementById('aprov'); const r=sel.getBoundingClientRect();
      const m=document.createElement('div'); m.id='fauxmenu';
      Object.assign(m.style,{position:'fixed',left:r.left+'px',top:(r.bottom+4)+'px',width:r.width+'px',
        background:'#0E1416',border:'1px solid #2A4A44',borderRadius:'10px',zIndex:99990,overflow:'hidden',
        boxShadow:'0 18px 50px -20px rgba(0,0,0,.9)',font:'15px system-ui'});
      [['custom','Custom (OpenAI-compatible)'],['openai','OpenAI'],['anthropic','Anthropic'],['gemini','Google Gemini'],['openrouter','OpenRouter'],['ollama','Ollama · local']]
        .forEach(([v,l],i)=>{const o=document.createElement('div');o.className='fmi';o.dataset.v=v;o.textContent=l;
          Object.assign(o.style,{padding:'10px 14px',color:'#dfeae8',cursor:'pointer',borderTop:i?'1px solid #172420':'none'});m.appendChild(o);});
      document.body.appendChild(m);
    }); };
  await click('#aprov', menu);
  // move to the OpenAI row and click it
  cap('Pick a cloud provider','endpoint + model fill in automatically');
  const openaiPos = await page.evaluate(()=>{const o=[...document.querySelectorAll('#fauxmenu .fmi')].find(x=>x.dataset.v==='openai');const r=o.getBoundingClientRect();o.style.background='#12211d';return{x:r.left+120,y:r.top+r.height/2};});
  await moveTo(openaiPos.x, openaiPos.y, 16);
  await page.evaluate(([x,y])=>window.__press(x,y,true),[cx,cy]); await snap(2);
  await page.evaluate(([x,y])=>window.__ripple(x,y),[cx,cy]);
  await page.evaluate(()=>{ document.getElementById('fauxmenu')?.remove(); const s=document.getElementById('aprov'); s.value='openai'; apiPreset(true); });
  await page.evaluate(([x,y])=>window.__press(x,y,false),[cx,cy]); await snap(4);
  cap('Remote → flagged','counted · logged as egress · off in incognito'); await snap(18);
  // scroll down to read the whole warning + reveal Save
  cap('Scroll to the warning','read exactly what leaves your device');
  for(let s=0;s<22;s++){
    const done=await page.evaluate(()=>{const b=document.querySelector('button[onclick="saveModel()"]');const r=b.getBoundingClientRect();return r.bottom<=window.innerHeight-24 && r.bottom>0;});
    if(done)break; await scrollDown(30,1);
  }
  await snap(8);
  // click Save (freeze re-render so the confirmed state stays on screen)
  cap('Click Save','your Brain is now pointed at your API');
  await page.evaluate(()=>{ window.load=()=>{}; });
  await click('button[onclick="saveModel()"]', async()=>{ await page.evaluate(()=>saveModel()); });
  cap('Saved','local stays private · remote is always flagged');
  for(let h=0;h<34;h++){ await page.evaluate(()=>document.getElementById('toast').classList.add('show')); await snap(1); }
  fs.writeFileSync(`${OUT}/caps.json`, JSON.stringify(caps));
  console.log('frames', fi);
  await browser.close(); srv.close();
})();
