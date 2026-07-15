// Drive the REAL shipped Brain panel (main's render_panel HTML) and capture the
// "plug in any API as your brain" feature: the Your-API segment, the provider
// dropdown, and the live local(green)/remote(amber) privacy warning.
const { chromium } = require(process.env.PLAYWRIGHT_HOME || '/opt/node22/lib/node_modules/playwright');
const http = require('http'); const fs = require('fs'); const path = require('path');
const OUT = process.argv[2] || '/tmp/panel_shots';
fs.mkdirSync(path.join(OUT,'seq'), { recursive: true });

const HTML = fs.readFileSync('/tmp/panel_demo.html');
const srv = http.createServer((req,res)=>{ res.setHeader('Content-Type','text/html'); res.end(HTML); });

(async ()=>{
  await new Promise(r=>srv.listen(8811,r));
  const browser = await chromium.launch({ executablePath: process.env.CHROME_BIN || '/opt/pw-browsers/chromium-1194/chrome-linux/chrome' });
  const ctx = await browser.newContext({ viewport:{width:900,height:1300}, deviceScaleFactor:2, colorScheme:'dark' });
  const page = await ctx.newPage();
  // stub network so load() doesn't throw; feature JS is pure client-side
  await page.addInitScript(()=>{
    const j=(o)=>Promise.resolve({ok:true,json:()=>Promise.resolve(o),text:()=>Promise.resolve('')});
    window.fetch=(u,opt)=>{ return j({config:{},status:{},folders:[],plan:{},people:[],items:[],packs:[],plugins:[]}); };
  });
  await page.goto('http://localhost:8811/', { waitUntil:'domcontentloaded' });
  await page.waitForTimeout(500);
  // hide loading skeletons/shimmers (empty network stub leaves them 'loading' → flashing)
  await page.addStyleTag({content:'#modelStatus,#apiStatus,.shimmer,.mstat .shimmer{display:none!important} .mstat:empty{display:none!important}'});
  // reveal the Intelligence page and the Model section
  await page.evaluate(()=>{ try{ showPage('mind'); }catch(e){} });
  await page.waitForTimeout(300);
  // open "Your API"
  await page.evaluate(()=>{ try{ pickModel('api'); }catch(e){} });
  await page.waitForTimeout(500);
  // locate the Model section and scroll it into view
  const box = await page.evaluate(()=>{
    const secs=[...document.querySelectorAll('section')];
    const s=secs.find(x=>(x.querySelector('h2')?.textContent||'').trim()==='Model');
    s.scrollIntoView({block:'start'}); window.scrollBy(0,-24);
    const r=s.getBoundingClientRect();
    return {x:Math.max(0,r.left-20), y:Math.max(0,r.top-14), w:Math.min(860,r.width+40), h:Math.min(1180,r.height+40)};
  });
  const clip={ x:Math.round(box.x), y:Math.round(box.y), width:Math.round(box.w), height:Math.round(box.h) };
  let fi=0;
  const snap=async(n=1)=>{ for(let i=0;i<n;i++){ await page.screenshot({path:`${OUT}/seq/f_${String(fi).padStart(4,'0')}.png`, clip}); fi++; } };

  // helper: set a field value, fire events, re-render warning
  const setBase = async (val)=>{ await page.evaluate((v)=>{ const el=document.getElementById('abase'); el.value=v; el.dispatchEvent(new Event('input')); }, val); };
  const setProv = async (p)=>{ await page.evaluate((pp)=>{ const s=document.getElementById('aprov'); s.value=pp; apiPreset(true); }, p); };
  const setModel = async (val)=>{ await page.evaluate((v)=>{ document.getElementById('amodel').value=v; }, val); };

  // 1) fold just opened, Custom, empty -> neutral hint
  await setProv('custom'); await page.waitForTimeout(200); await snap(10);
  // 2) type a local LM Studio / Hermes endpoint char-by-char -> green on-device
  const local='http://localhost:1234/v1';
  for(let k=1;k<=local.length;k++){ await setBase(local.slice(0,k)); await snap(1); }
  await setModel('hermes-3-8b'); await page.waitForTimeout(150); await snap(4);
  await snap(28);                        // hold green "On your device"
  // 3) switch provider to OpenAI -> autofills + amber egress warning
  await setProv('openai'); await page.waitForTimeout(200); await snap(30);
  // 4) switch to Anthropic -> autofills claude, amber
  await setProv('anthropic'); await page.waitForTimeout(200); await snap(22);
  // 5) back to a local vLLM endpoint -> green again
  await setProv('custom'); await setBase(''); await snap(2);
  const vllm='http://192.168.1.42:8000/v1';
  for(let k=1;k<=vllm.length;k++){ await setBase(vllm.slice(0,k)); await snap(1); }
  await setModel('Qwen2.5-7B'); await snap(4); await snap(30);
  console.log('panel frames', fi, 'clip', JSON.stringify(clip));
  await browser.close(); srv.close();
})();
