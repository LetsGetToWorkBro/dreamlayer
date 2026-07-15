// Capture the real DreamLayer web surfaces with the pre-installed Chromium.
// Dismisses the builder intro tour and hides environment-only banners (offline
// store fetch, headless-has-no-Bluetooth) so the shots show the product itself.
const { chromium } = require(process.env.PLAYWRIGHT_HOME || '/opt/node22/lib/node_modules/playwright');
const http = require('http');
const fs = require('fs');
const path = require('path');

const ROOT = require('path').join(__dirname, '..', '..', 'landing');
const OUT = process.argv[2] || '/tmp/web_out';
fs.mkdirSync(path.join(OUT, 'raw'), { recursive: true });
fs.mkdirSync(path.join(OUT, 'bgseq'), { recursive: true });

const MIME = { '.html':'text/html','.css':'text/css','.js':'text/javascript','.json':'application/json',
  '.png':'image/png','.webp':'image/webp','.svg':'image/svg+xml','.jpg':'image/jpeg','.woff2':'font/woff2','.ico':'image/x-icon' };

function serve(dir, port) {
  return new Promise((resolve) => {
    const srv = http.createServer((req, res) => {
      let u = decodeURIComponent(req.url.split('?')[0]);
      if (u === '/') u = '/index.html';
      fs.readFile(path.join(dir, u), (err, data) => {
        if (err) { res.statusCode = 404; res.end('nf'); return; }
        res.setHeader('Content-Type', MIME[path.extname(u)] || 'application/octet-stream');
        res.end(data);
      });
    });
    srv.listen(port, () => resolve(srv));
  });
}

(async () => {
  const srv = await serve(ROOT, 8799);
  const browser = await chromium.launch({ executablePath: process.env.CHROME_BIN || '/opt/pw-browsers/chromium-1194/chrome-linux/chrome' });
  const save = OUT + '/raw/';
  const shot = async (t, n, o={}) => { await t.screenshot({ path: save + n + '.png', ...o }); console.log('shot', n); };

  // ---------- Plugin Store ----------
  {
    const ctx = await browser.newContext({ viewport:{width:1440,height:900}, deviceScaleFactor:2, colorScheme:'dark' });
    const page = await ctx.newPage();
    await page.goto('http://localhost:8799/plugins.html', { waitUntil:'networkidle' });
    await page.waitForTimeout(900);
    await page.evaluate(() => { const s=document.querySelector('#status'); if(s) s.style.display='none'; });
    await shot(page, 'store_top');
    await shot(page, 'store_full', { fullPage:true });
    const card = await page.$('.card, .plugin, #grid > *');
    if (card) await card.screenshot({ path: save + 'store_card.png' });
    await ctx.close();
  }

  // ---------- Lens Builder ----------
  {
    const ctx = await browser.newContext({ viewport:{width:1440,height:960}, deviceScaleFactor:2, colorScheme:'dark' });
    const page = await ctx.newPage();
    // skip the intro tour before it can show
    await page.addInitScript(() => { try { localStorage.setItem('dl_tour','done'); } catch(e){} });
    await page.goto('http://localhost:8799/lens-builder.html', { waitUntil:'networkidle' });
    await page.waitForTimeout(600);
    // belt-and-suspenders: if the tour is up, close it
    await page.evaluate(() => {
      const x=document.querySelector('#tourX'); if(x) x.click();
      const t=document.querySelector('#tour'); if(t) t.style.display='none';
      const sc=document.querySelector('.tour-scrim'); if(sc) sc.style.display='none';
    });
    await page.waitForTimeout(1600);   // let the canvas preview render/animate
    await shot(page, 'builder_top');
    await shot(page, 'builder_full', { fullPage:true });
    const prev = await page.$('.ringwrap');
    if (prev) await prev.screenshot({ path: save + 'builder_preview.png' });
    // capture the editor column (left) tightly if present
    const ed = await page.$('.editor, .compose, textarea, .col-left');
    if (ed) await ed.screenshot({ path: save + 'builder_editor.png' }).catch(()=>{});
    // background-cycle mini demo: click each bg button, snap the preview
    const bgs = await page.$$('#bgpick button');
    for (let i=0;i<bgs.length;i++){
      await bgs[i].click();
      await page.waitForTimeout(700);
      const rw = await page.$('.ringwrap');
      if (rw) await rw.screenshot({ path: OUT + '/bgseq/bg_' + String(i).padStart(2,'0') + '.png' });
    }
    console.log('bgseq', bgs.length);
    await ctx.close();
  }

  // ---------- Playground (WebBLE dev surface) ----------
  {
    const ctx = await browser.newContext({ viewport:{width:1440,height:1000}, deviceScaleFactor:2, colorScheme:'dark' });
    const page = await ctx.newPage();
    await page.goto('http://localhost:8799/playground.html', { waitUntil:'networkidle', timeout:9000 }).catch(()=>{});
    await page.waitForTimeout(900);
    // hide the "this browser can't do Web Bluetooth" env banner (headless has no radio)
    await page.evaluate(() => { const u=document.querySelector('#unsupported'); if(u) u.style.display='none';
      const log=document.querySelector('#log,.log'); if(log && /unavailable/i.test(log.textContent)) log.textContent=''; });
    await shot(page, 'playground_top');
    await shot(page, 'playground_full', { fullPage:true });
    await ctx.close();
  }

  await browser.close();
  srv.close();
  console.log('DONE');
})();
