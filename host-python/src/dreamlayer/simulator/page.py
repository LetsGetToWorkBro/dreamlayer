"""simulator/page.py — the simulator's one-page cockpit.

Served by simulator/server.py at "/". Pure inline HTML/CSS/JS, no deps,
Meridian-dark like the rest of DreamLayer's surfaces. The glass is an <img>
polling /sim/frame.png — every pixel comes from the Python side (the same
renderers the golden images use), so this page never fakes the display.
"""

PAGE = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>DreamLayer · Halo Simulator</title>
<style>
  :root{
    --bg:#000; --surface:#0a0f10; --border:#1b2a2c; --text:#e7f3f1;
    --text-2:#88a09c; --text-3:#5b6f6b; --teal:#2CC79A; --coral:#E06B52;
    --mono:ui-monospace,"SF Mono",Menlo,monospace;
  }
  *{box-sizing:border-box}
  body{margin:0;background:var(--bg);color:var(--text);
    font:15px/1.55 system-ui,-apple-system,Segoe UI,Roboto,sans-serif;
    min-height:100vh;display:flex;flex-direction:column;align-items:center}
  header{width:100%;max-width:980px;display:flex;align-items:center;
    justify-content:space-between;padding:18px 22px 6px}
  .wordmark{display:flex;align-items:center;gap:10px;font-weight:800;
    letter-spacing:.14em;color:#fff;font-size:14px}
  .ring{width:14px;height:14px;border:2px solid var(--teal);border-radius:50%;position:relative}
  .ring::after{content:"";position:absolute;inset:3px;background:var(--teal);border-radius:50%}
  .sub{font-family:var(--mono);font-size:11px;letter-spacing:.22em;
    text-transform:uppercase;color:var(--teal)}
  main{width:100%;max-width:980px;display:grid;grid-template-columns:1fr 340px;
    gap:26px;padding:16px 22px 40px;align-items:start}
  @media(max-width:820px){main{grid-template-columns:1fr}}
  /* the glass */
  .stage{display:flex;flex-direction:column;align-items:center;gap:18px}
  .glass-wrap{position:relative;width:min(74vw,420px);aspect-ratio:1}
  .glass{width:100%;height:100%;border-radius:50%;display:block;
    image-rendering:auto;
    box-shadow:0 0 60px rgba(44,199,154,.14),0 0 160px rgba(44,199,154,.05),
      inset 0 0 40px rgba(0,0,0,.7);
    border:1px solid #14211f;background:#000}
  .glass-wrap::after{content:"";position:absolute;inset:0;border-radius:50%;
    background:radial-gradient(circle at 32% 26%,rgba(255,255,255,.06),transparent 45%);
    pointer-events:none}
  .veiled .glass{box-shadow:0 0 40px rgba(143,168,178,.10),inset 0 0 40px rgba(0,0,0,.8)}
  .statusline{font-family:var(--mono);font-size:11.5px;letter-spacing:.14em;
    text-transform:uppercase;color:var(--text-3)}
  .statusline b{color:var(--teal);font-weight:600}
  /* controls */
  .say{width:100%;display:flex;gap:10px}
  .say input{flex:1;background:var(--surface);border:1px solid var(--border);
    border-radius:999px;color:var(--text);padding:13px 18px;font-size:15px}
  .say input:focus{outline:none;border-color:var(--teal);
    box-shadow:0 0 0 3px rgba(44,199,154,.12)}
  .say button{background:var(--teal);color:#00201c;border:0;border-radius:999px;
    width:48px;font-size:17px;font-weight:800;cursor:pointer}
  .row{display:flex;gap:8px;flex-wrap:wrap;justify-content:center}
  .chip{font:inherit;font-size:13px;color:var(--text-2);background:transparent;
    border:1px solid var(--border);border-radius:999px;padding:8px 15px;cursor:pointer;
    transition:.15s}
  .chip:hover{color:#fff;border-color:var(--teal)}
  .chip.on{color:#00201c;background:var(--teal);border-color:var(--teal)}
  .chip.danger.on{color:#fff;background:var(--coral);border-color:var(--coral)}
  .grouplbl{font-family:var(--mono);font-size:10.5px;letter-spacing:.18em;
    text-transform:uppercase;color:var(--text-3);margin:8px 0 -2px;text-align:center}
  /* right rail */
  .rail{display:flex;flex-direction:column;gap:16px}
  .panel{background:var(--surface);border:1px solid var(--border);border-radius:14px;padding:16px}
  .panel h3{margin:0 0 10px;font-family:var(--mono);font-size:11px;
    letter-spacing:.2em;text-transform:uppercase;color:var(--teal);font-weight:600}
  .log{display:flex;flex-direction:column;gap:7px;max-height:300px;overflow:auto}
  .log .you{color:var(--text);font-size:13.5px}
  .log .you::before{content:"you  ";font-family:var(--mono);font-size:10px;color:var(--text-3)}
  .log .juno{color:var(--teal);font-size:13.5px}
  .log .juno::before{content:"juno  ";font-family:var(--mono);font-size:10px;color:var(--text-3)}
  .try{display:flex;flex-direction:column;gap:6px}
  .try button{font:inherit;text-align:left;font-size:13px;color:var(--text-2);
    background:transparent;border:0;padding:4px 2px;cursor:pointer}
  .try button:hover{color:var(--teal)}
  .try button::before{content:"› ";color:var(--teal)}
  .people{color:var(--text-2);font-size:13px}
  footer{color:var(--text-3);font-size:12px;padding:0 22px 26px;max-width:980px;text-align:center}
  footer b{color:var(--text-2)}
</style>
</head>
<body>
<header>
  <span class="wordmark"><span class="ring"></span>DREAMLAYER</span>
  <span class="sub">Halo Simulator</span>
</header>

<main>
  <section class="stage" id="stage">
    <div class="glass-wrap"><img id="glass" class="glass" src="/sim/frame.png" alt="the Halo display"></div>
    <div class="statusline" id="status">state <b>boot</b></div>

    <form class="say" id="sayform">
      <input id="sayinput" placeholder="Say something… “set a timer for 2 minutes”" autocomplete="off" autofocus>
      <button type="submit">↳</button>
    </form>

    <div class="grouplbl">Looking at</div>
    <div class="row" id="looks">
      <button type="button" class="chip on" data-look="">Nobody</button>
      <button type="button" class="chip" data-look="face-a">Face A</button>
      <button type="button" class="chip" data-look="face-b">Face B</button>
      <button type="button" class="chip" data-look="face-c">Face C</button>
      <button type="button" class="chip" id="glancebtn">👁 Glance</button>
    </div>

    <div class="grouplbl">Temple &amp; veil</div>
    <div class="row">
      <button type="button" class="chip" data-g="single">Tap</button>
      <button type="button" class="chip" data-g="double">Double-tap</button>
      <button type="button" class="chip" data-g="long">Hold</button>
      <button type="button" class="chip danger" id="veilbtn">◐ Privacy Veil</button>
    </div>
  </section>

  <aside class="rail">
    <div class="panel">
      <h3>Conversation</h3>
      <div class="log" id="log"></div>
    </div>
    <div class="panel">
      <h3>Try saying</h3>
      <div class="try" id="try">
        <button>set a timer for 30 seconds</button>
        <button>interval timer, 20 on, 10 off, 3 rounds</button>
        <button>what time is it?</button>
        <button data-look="face-a">this is my colleague Sarah, she runs marketing</button>
        <button>Sarah owes me $20</button>
        <button>I left my bike at the north rack</button>
        <button>where's my bike?</button>
        <button>remember I prefer aisle seats</button>
        <button>go incognito</button>
      </div>
    </div>
    <div class="panel">
      <h3>People it knows</h3>
      <div class="people" id="people">no one yet — introduce someone</div>
    </div>
  </aside>
</main>

<footer>
  Every pixel is rendered by the <b>real DreamLayer stack</b> — the voice grammar, Social Lens,
  Waypath, and the Reality Compiler's Figment stage (the Python twin of the device Lua,
  pinned by the parity suite). Only the hardware is simulated.
</footer>

<script>
const $=id=>document.getElementById(id);
let look="", veiled=false;

async function post(path, body){
  try{
    const r=await fetch(path,{method:"POST",headers:{"Content-Type":"application/json"},
      body:JSON.stringify(body||{})});
    return await r.json();
  }catch(e){return null;}
}

// the glass: poll real frames (~7 fps is plenty for a countdown + breathe)
setInterval(()=>{ $("glass").src="/sim/frame.png?t="+Date.now(); }, 140);

// state + transcript
async function pull(){
  try{
    const s=await (await fetch("/sim/state")).json();
    let line=`state <b>${s.state}</b>`;
    if(s.figment) line+=` · figment <b>${s.figment.scene}</b> · ${s.figment.remaining}s`;
    if(s.veiled) line+=` · <b style="color:var(--coral)">veiled</b>`;
    $("status").innerHTML=line;
    veiled=s.veiled;
    $("veilbtn").classList.toggle("on",veiled);
    $("stage").classList.toggle("veiled",veiled);
    $("log").innerHTML=(s.transcript||[]).map(t=>
      `<div class="${t.who}">${esc(t.line)}</div>`).join("");
    $("log").scrollTop=$("log").scrollHeight;
    $("people").textContent=(s.people>0)?(s.people+" kept"):
      "no one yet — introduce someone";
  }catch(e){}
}
const esc=s=>(s||"").replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
setInterval(pull, 600); pull();

// voice
$("sayform").addEventListener("submit", async ev=>{
  ev.preventDefault();
  const text=$("sayinput").value.trim();
  if(!text) return;
  $("sayinput").value="";
  await post("/sim/voice",{text, look});
  pull();
});

// looks
$("looks").addEventListener("click", ev=>{
  const b=ev.target.closest("[data-look]");
  if(!b) return;
  look=b.dataset.look;
  document.querySelectorAll("#looks [data-look]").forEach(x=>x.classList.toggle("on",x===b));
});
$("glancebtn").addEventListener("click", async ()=>{
  await post("/sim/glance",{look}); pull();
});

// gestures + veil
document.querySelectorAll("[data-g]").forEach(b=>b.addEventListener("click", async ()=>{
  await post("/sim/gesture",{name:b.dataset.g}); pull();
}));
$("veilbtn").addEventListener("click", async ()=>{
  await post("/sim/veil",{on:!veiled}); pull();
});

// try-saying shortcuts
$("try").addEventListener("click", async ev=>{
  const b=ev.target.closest("button"); if(!b) return;
  if(b.dataset.look!==undefined && b.dataset.look!==""){
    look=b.dataset.look;
    document.querySelectorAll("#looks [data-look]").forEach(x=>
      x.classList.toggle("on",x.dataset.look===look));
  }
  await post("/sim/voice",{text:b.textContent, look}); pull();
});
</script>
</body>
</html>
"""
