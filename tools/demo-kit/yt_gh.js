// Capture the REAL v0.1.0 release page for the install video: initial hold,
// smooth scroll to the Assets section, and the DreamLayer.dmg link's box at the
// final scroll (compositor drives the cursor + click + download shelf).
// Requests are fulfilled Node-side (route.fetch) because Chromium's own
// transport stalls behind the CONNECT relay. Run with:
//   NODE_EXTRA_CA_CERTS=/root/.ccr/ca-bundle.crt node yt_gh.js /tmp/yt/gh
const { chromium } = require(process.env.PLAYWRIGHT_HOME || '/opt/node22/lib/node_modules/playwright');
const fs = require('fs'); const path = require('path');
const OUT = process.argv[2] || '/tmp/yt/gh';
fs.mkdirSync(path.join(OUT,'seq'), { recursive: true });

(async()=>{
  const b = await chromium.launch({ executablePath: process.env.CHROME_BIN || '/opt/pw-browsers/chromium-1194/chrome-linux/chrome' });
  const ctx = await b.newContext({ viewport:{width:1520,height:880}, deviceScaleFactor:1, colorScheme:'dark',
    proxy:{ server: process.env.HTTPS_PROXY } });
  const p = await ctx.newPage();
  await p.route('**/*', async route => {
    try { const resp = await route.fetch({timeout:30000}); await route.fulfill({ response: resp }); }
    catch(e){ await route.abort(); }
  });
  await p.goto('https://github.com/LetsGetToWorkBro/dreamlayer/releases/tag/v0.1.0',{waitUntil:'domcontentloaded',timeout:90000});
  await p.waitForTimeout(2500);
  // the expanded_assets <include-fragment> doesn't self-hydrate under routed
  // networking — fetch it in-page (goes through the route) and inline it
  await p.evaluate(async()=>{
    const f=[...document.querySelectorAll('include-fragment')].find(x=>(x.getAttribute('src')||'').includes('expanded_assets'));
    if(f && !document.querySelector('a[href*="DreamLayer.dmg"]')){
      const r=await fetch(f.getAttribute('src'),{headers:{'Accept':'text/fragment+html, text/html'}});
      const html=await r.text();
      const div=document.createElement('div'); div.innerHTML=html;
      f.replaceWith(div);
    }
  });
  await p.waitForSelector('a[href*="DreamLayer.dmg"]',{timeout:20000, state:'attached'});
  await p.waitForTimeout(1000);
  // hide the cookie banner if present
  await p.evaluate(()=>{ const c=document.querySelector('#wcpConsentBannerCtrl, .cookie-consent, [data-testid="cookie-banner"]'); if(c) c.style.display='none'; });

  let fi=0;
  const snap=async(n=1)=>{ for(let i=0;i<n;i++){ await p.screenshot({path:`${OUT}/seq/f_${String(fi).padStart(4,'0')}.png`, timeout:20000}); fi++; } };
  const scrollY=(y)=>p.evaluate((yy)=>window.scrollTo(0,yy), y);

  // find the DMG link's document position to plan the scroll
  const link = await p.evaluate(()=>{
    const a=document.querySelector('a[href*="DreamLayer.dmg"]');
    if(!a) return null;
    const r=a.getBoundingClientRect();
    return { docY: r.top + window.scrollY, x: r.left + Math.min(90, r.width/2), h: r.height };
  });
  const targetY = link ? Math.max(0, link.docY - 500) : 2400;

  const meta = { holds:{}, link:null };
  meta.holds.start = fi;
  await snap(36);                                   // read the top of the release

  // smooth scroll down to the assets area (smoothstep, 84 frames)
  const STEPS=84;
  for(let k=1;k<=STEPS;k++){
    const t=k/STEPS, e=t*t*(3-2*t);
    await scrollY(Math.round(targetY*e));
    await snap(1);
  }
  meta.holds.assets = fi;
  await snap(20);                                   // settle on the assets list

  // record the link's viewport box at this final scroll for the compositor
  if(link){
    const box = await p.evaluate(()=>{
      const a=document.querySelector('a[href*="DreamLayer.dmg"]');
      const r=a.getBoundingClientRect();
      return { x:r.left+Math.min(90,r.width/2), y:r.top+r.height/2 };
    });
    meta.link = box;
  }
  await snap(56);                                   // hold while cursor moves + clicks (compositor)
  meta.holds.end = fi;
  fs.writeFileSync(`${OUT}/meta.json`, JSON.stringify(meta));
  console.log('gh frames', fi, 'link', JSON.stringify(meta.link));
  await b.close();
})();
