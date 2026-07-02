"""ai_brain/server/panel.py — the control panel served at /.

A self-contained local web UI, polished to match the phone app's design
language (docs: phone-app/DESIGN.md): the same dark palette, 8-pt rhythm,
soft "arrive" motion, tactile controls, and toast feedback instead of jarring
reloads. Vanilla JS/CSS, no build step, no external requests. The token is
injected only when the panel is opened from the Mac mini itself (localhost);
a remote browser gets a blank field and must be told the token.
"""
from __future__ import annotations


def render_panel(token: str = "") -> str:
    return _PAGE.replace("__TOKEN__", token or "")


_PAGE = r"""<!doctype html><html lang="en"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>DreamLayer Brain</title>
<style>
  :root{
    --bg:#000000; --surf:#0E1416; --surf2:#141F23; --line:#1F2A2E;
    --memory:#2FD4C4; --attention:#FF6B5E; --success:#56D364; --error:#FF5C5C;
    --text:#FFFFFF; --muted:#8A9BA3; --ghost:#55666C;
    --r-sm:10px; --r-lg:18px; --r-pill:999px;
    --ease:cubic-bezier(.16,1,.3,1);
  }
  *{box-sizing:border-box}
  html,body{margin:0}
  body{
    background:
      radial-gradient(1100px 620px at 50% -8%, rgba(47,212,196,.10), transparent 60%),
      var(--bg);
    color:var(--text); -webkit-font-smoothing:antialiased;
    font:15px/1.55 ui-sans-serif,system-ui,-apple-system,"SF Pro Text",Segoe UI,Roboto,sans-serif;
    min-height:100vh;
  }
  .wrap{max-width:760px;margin:0 auto;padding:0 20px 96px}

  /* --- top bar ------------------------------------------------------- */
  .bar{position:sticky;top:0;z-index:20;display:flex;align-items:center;gap:12px;
       padding:20px 0 16px;margin-bottom:6px;
       background:linear-gradient(var(--bg) 72%,transparent);backdrop-filter:blur(6px)}
  .brand{font-weight:600;letter-spacing:-.01em;font-size:1.05rem}
  .brand b{color:var(--memory);font-weight:600}
  .live{display:flex;align-items:center;gap:7px;margin-left:auto;color:var(--muted);
        font:12px ui-monospace,SFMono-Regular,Menlo,monospace}
  .live .dot{width:8px;height:8px;border-radius:50%;background:var(--success);
        box-shadow:0 0 0 0 rgba(86,211,100,.6);animation:pulse 2.4s var(--ease) infinite}
  @keyframes pulse{0%{box-shadow:0 0 0 0 rgba(86,211,100,.5)}70%{box-shadow:0 0 0 7px rgba(86,211,100,0)}100%{box-shadow:0 0 0 0 rgba(86,211,100,0)}}

  h1{font-weight:700;letter-spacing:-.025em;font-size:2.4rem;margin:6px 0 2px}
  .sub{color:var(--muted);margin:0 0 22px}
  .stat{display:flex;flex-wrap:wrap;gap:8px;margin:0 0 20px}
  .chip{display:inline-flex;align-items:center;gap:6px;background:var(--surf);
        border:1px solid var(--line);border-radius:var(--r-pill);
        padding:6px 12px;font-size:.82rem;color:var(--muted)}
  .chip b{color:var(--text);font-weight:600}
  .chip.on{border-color:rgba(47,212,196,.5);color:var(--memory)}

  /* --- cards --------------------------------------------------------- */
  main>section{background:var(--surf);border:1px solid var(--line);
        border-radius:var(--r-lg);padding:20px;margin-bottom:14px;
        opacity:0;transform:translateY(14px);animation:rise .5s var(--ease) forwards}
  main>section:nth-child(1){animation-delay:.02s}
  main>section:nth-child(2){animation-delay:.07s}
  main>section:nth-child(3){animation-delay:.12s}
  main>section:nth-child(4){animation-delay:.17s}
  main>section:nth-child(5){animation-delay:.22s}
  @keyframes rise{to{opacity:1;transform:none}}
  h2{font-weight:600;font-size:1.12rem;margin:0 0 4px;letter-spacing:-.01em}
  .eyebrow{font:11px ui-monospace,SFMono-Regular,Menlo,monospace;letter-spacing:.2em;
           text-transform:uppercase;color:var(--memory);margin-bottom:8px}
  .lead{color:var(--muted);font-size:.92rem;margin:0 0 16px}

  .row{display:flex;gap:10px;align-items:center;flex-wrap:wrap}
  input[type=text]{flex:1;min-width:180px}
  input,select{background:#0A1113;border:1px solid var(--line);color:var(--text);
        border-radius:var(--r-sm);padding:11px 13px;font:inherit;transition:border-color .15s}
  input:focus,select:focus{outline:none;border-color:var(--memory)}
  input::placeholder{color:var(--ghost)}

  button{background:var(--memory);color:#04120d;border:0;border-radius:var(--r-sm);
         padding:11px 16px;font:inherit;font-weight:600;cursor:pointer;
         transition:transform .12s var(--ease),filter .15s}
  button:hover{filter:brightness(1.06)}
  button:active{transform:scale(.96)}
  button.ghost{background:transparent;color:var(--muted);border:1px solid var(--line);font-weight:500}
  button.ghost:hover{color:var(--text);border-color:var(--muted);filter:none}
  button.sm{padding:8px 12px;font-size:.85rem}

  /* connections rows + switches */
  .conn{display:flex;gap:18px;align-items:center;justify-content:space-between;
        padding:16px 0;border-top:1px solid var(--line)}
  .conn:first-of-type{border-top:0;padding-top:4px}
  .conn-t{font-size:1rem}
  .conn-s{font-size:.85rem;color:var(--muted);margin-top:3px;max-width:46ch}
  .sw{position:relative;display:inline-block;width:48px;height:28px;flex:none;cursor:pointer}
  .sw input{opacity:0;width:0;height:0;position:absolute}
  .sw .track{position:absolute;inset:0;background:#0A1113;border:1px solid var(--line);
        border-radius:var(--r-pill);transition:background .2s var(--ease),border-color .2s}
  .sw .track:before{content:"";position:absolute;left:3px;top:2px;width:21px;height:21px;
        border-radius:50%;background:var(--ghost);transition:transform .2s var(--ease),background .2s}
  .sw input:checked + .track{background:rgba(47,212,196,.22);border-color:var(--memory)}
  .sw input:checked + .track:before{transform:translateX(20px);background:var(--memory)}
  .sw input:checked + .track.red{background:rgba(255,107,94,.22);border-color:var(--attention)}
  .sw input:checked + .track.red:before{background:var(--attention)}
  .sw input:disabled + .track{opacity:.4;cursor:not-allowed}

  /* folders list */
  ul{list-style:none;margin:6px 0 0;padding:0}
  li.folder{display:flex;justify-content:space-between;align-items:center;gap:12px;
     padding:12px 0;border-top:1px solid var(--line)}
  li.folder:first-child{border-top:0}
  .path{font:13px ui-monospace,Menlo,monospace;color:var(--muted);word-break:break-all}
  .path:before{content:"";display:inline-block;width:7px;height:7px;border-radius:2px;
        background:var(--memory);margin-right:9px;vertical-align:middle;opacity:.8}
  .drop{margin-top:14px;border:1.5px dashed var(--line);border-radius:14px;
        padding:26px;text-align:center;color:var(--ghost);
        transition:border-color .15s,color .15s,background .15s}
  .drop.hot{border-color:var(--memory);color:var(--memory);background:rgba(47,212,196,.06)}
  .empty{color:var(--ghost);font-size:.9rem;padding:14px 0;text-align:center}

  /* segmented control */
  .seg{display:inline-flex;background:#0A1113;border:1px solid var(--line);
       border-radius:var(--r-pill);padding:3px;gap:2px}
  .seg button{background:transparent;color:var(--muted);border-radius:var(--r-pill);
       padding:8px 16px;font-weight:500}
  .seg button.on{background:var(--memory);color:#04120d;font-weight:600}
  .fold{max-height:0;overflow:hidden;opacity:0;transition:max-height .3s var(--ease),opacity .25s,margin .3s}
  .fold.open{max-height:220px;opacity:1;margin-top:12px}

  /* answer */
  .ans{margin-top:14px;padding:14px 16px;background:#0A1113;border-radius:var(--r-sm);
       border-left:2px solid var(--memory);animation:rise .35s var(--ease) both}
  .ans .src{display:inline-flex;gap:8px;align-items:center;font:11px ui-monospace,Menlo,monospace;
       color:var(--ghost);margin-top:8px}
  .tier{background:rgba(47,212,196,.14);color:var(--memory);border-radius:var(--r-pill);
       padding:2px 8px;text-transform:uppercase;letter-spacing:.08em}
  .shimmer{height:14px;border-radius:6px;margin:6px 0;
       background:linear-gradient(90deg,#0A1113,#182228,#0A1113);
       background-size:200% 100%;animation:sh 1.1s linear infinite}
  .shimmer.s2{width:70%}
  @keyframes sh{0%{background-position:200% 0}100%{background-position:-200% 0}}

  /* pairing code */
  .paircode{margin-top:14px;background:#0A1113;border:1px solid var(--line);
       border-radius:var(--r-sm);padding:14px;animation:rise .35s var(--ease) both}
  .paircode .code{font:13px/1.5 ui-monospace,Menlo,monospace;color:var(--memory);
       word-break:break-all;user-select:all}
  .paircode .foot{display:flex;justify-content:space-between;align-items:center;
       gap:12px;margin-top:12px;flex-wrap:wrap}
  .paircode .foot .url{font:12px ui-monospace,Menlo,monospace;color:var(--ghost)}

  /* history */
  .hist li{display:flex;justify-content:space-between;align-items:flex-start;gap:12px;
       padding:12px 0;border-top:1px solid var(--line)}
  .hist li:first-child{border-top:0}
  .hist .q{color:var(--text)} .hist .a{color:var(--muted);font-size:.9rem;margin-top:2px}
  .hist .t{font:10px ui-monospace,Menlo,monospace;color:var(--memory);
       text-transform:uppercase;letter-spacing:.08em;flex:none;padding-top:3px}

  label.tog{display:flex;gap:10px;align-items:center;color:var(--muted);cursor:pointer}
  label.tog input{accent-color:var(--memory)}

  /* toast */
  #toast{position:fixed;left:50%;bottom:30px;transform:translate(-50%,20px);
       background:var(--surf2);border:1px solid var(--line);border-radius:var(--r-pill);
       padding:11px 20px;color:var(--text);font-size:.9rem;opacity:0;pointer-events:none;
       transition:opacity .25s var(--ease),transform .25s var(--ease);z-index:50;
       box-shadow:0 12px 40px rgba(0,0,0,.5)}
  #toast.show{opacity:1;transform:translate(-50%,0)}
  #toast .dot{display:inline-block;width:7px;height:7px;border-radius:50%;
       background:var(--success);margin-right:9px;vertical-align:middle}
  a{color:var(--memory)}
</style></head><body>
<div class="wrap">
  <div class="bar">
    <span class="brand"><b>Dream</b>Layer</span>
    <span class="live"><span class="dot"></span><span id="livetext">Brain online</span></span>
  </div>

  <h1>Brain</h1>
  <p class="sub" id="sub">This Mac mini is the brain — your files, your memory, your reach.</p>
  <div class="stat" id="stat"></div>

  <main>
  <section>
    <div class="eyebrow">Connections</div>
    <h2>Reach &amp; devices</h2>
    <p class="lead">Pair your phone (it brings the glasses), choose how far the
      brain reaches, or shut the doors with Incognito.</p>
    <div class="conn">
      <div>
        <div class="conn-t">Cloud</div>
        <div class="conn-s">Reach the frontier for the hardest, non-personal asks —
          obscure facts, the richest object explanations, widest translation. Your
          own files, memory and people never need it. Nothing private ever leaves.</div>
      </div>
      <label class="sw"><input type="checkbox" id="cloud" onchange="saveConn()"><span class="track"></span></label>
    </div>
    <div class="conn">
      <div>
        <div class="conn-t">Incognito</div>
        <div class="conn-s">A private stretch: stays on your LAN, forces cloud off,
          and logs nothing. Flip it on when you want the doors shut.</div>
      </div>
      <label class="sw"><input type="checkbox" id="incognito" onchange="saveConn()"><span class="track red"></span></label>
    </div>
    <div class="conn">
      <div>
        <div class="conn-t">Phone &amp; glasses</div>
        <div class="conn-s">One code wires the phone, this Brain, and your glasses
          together. Open the DreamLayer app → Brain → Pair a device, then scan or
          paste this.</div>
      </div>
      <button id="pairbtn" onclick="pair()">Pair a phone</button>
    </div>
    <div id="pairout"></div>
  </section>

  <section>
    <div class="eyebrow">Knowledge</div>
    <h2>Folders it reads</h2>
    <p class="lead">Everything in these folders is searchable — notes, PDFs, mail
      exports. Files never leave your Mac mini.</p>
    <ul id="folders"></ul>
    <div class="row" style="margin-top:14px">
      <input type="text" id="folderPath" placeholder="/Users/you/Documents/DreamLayer"
             onkeydown="if(event.key==='Enter')addFolder()">
      <button onclick="addFolder()">Add folder</button>
    </div>
    <div class="drop" id="drop">Drag &amp; drop files here → add them to
      <select id="dropTarget" style="margin:0 4px"></select></div>
  </section>

  <section>
    <div class="eyebrow">Recall</div>
    <h2>Ask your stuff</h2>
    <div class="row">
      <input type="text" id="q" placeholder="where's the lease? what does Marcus owe me?"
             onkeydown="if(event.key==='Enter')ask()">
      <button onclick="ask()">Ask</button>
    </div>
    <div id="answer"></div>
  </section>

  <section>
    <div class="eyebrow">Intelligence</div>
    <h2>Model</h2>
    <p class="lead">Keyword search works with no model at all. Add Ollama on this
      Mac mini for written answers and vision.</p>
    <div class="seg" id="modelSeg">
      <button data-m="keyword" onclick="pickModel('keyword')">Keyword</button>
      <button data-m="ollama" onclick="pickModel('ollama')">Ollama</button>
    </div>
    <div class="fold" id="ollamaFields">
      <div class="row">
        <input type="text" id="ourl" placeholder="http://127.0.0.1:11434" style="max-width:230px">
        <input type="text" id="ochat" placeholder="chat model · llama3.2" style="max-width:200px">
        <input type="text" id="ovis" placeholder="vision model" style="max-width:180px">
      </div>
    </div>
    <div class="row" style="margin-top:16px;justify-content:space-between">
      <label class="tog"><input type="checkbox" id="email"> Read email &amp; iMessage</label>
      <button class="sm" onclick="saveModel()">Save</button>
    </div>
  </section>

  <section>
    <div class="eyebrow">Log</div>
    <h2>History</h2>
    <ul id="history" class="hist"></ul>
  </section>
  </main>
</div>
<div id="toast"></div>
<script>
const TOKEN="__TOKEN__";
const H={"Content-Type":"application/json"}; if(TOKEN)H["X-DreamLayer-Token"]=TOKEN;
const api=(p,o={})=>fetch(p,Object.assign({headers:H},o)).then(r=>r.json());
const esc=s=>(s||"").replace(/[&<>]/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;"}[c]));
const $=id=>document.getElementById(id);
let modelSel="keyword";

let toastT;
function toast(msg){
  const t=$("toast"); t.innerHTML='<span class="dot"></span>'+esc(msg);
  t.classList.add("show"); clearTimeout(toastT);
  toastT=setTimeout(()=>t.classList.remove("show"),1900);
}

async function load(){
  let c;
  try{ c=await api("/dreamlayer/config"); }
  catch(e){ $("livetext").textContent="offline"; return; }
  if(c.error){ $("sub").textContent="Enter this Brain's token to manage it."; return; }
  const incog=c.config.network_mode==="lan_only";
  const cloudOn=!incog && !!c.config.cloud_enabled;
  $("stat").innerHTML=
    chip(`<b>${c.stats.files}</b> files`)+
    chip(`<b>${c.stats.passages}</b> passages`)+
    chip(`model <b>${esc(c.config.model)}</b>`)+
    chip(`cloud <b>${cloudOn?"on":"off"}</b>`, cloudOn)+
    (incog?chip("incognito", true):"");

  // folders
  const fl=$("folders"), dt=$("dropTarget"); fl.innerHTML=""; dt.innerHTML="";
  const folders=c.config.folders||[];
  if(!folders.length){ fl.innerHTML='<li class="empty">No folders yet — add one below to give your Brain something to read.</li>'; }
  folders.forEach(f=>{
    fl.innerHTML+=`<li class="folder"><span class="path">${esc(f)}</span>`+
      `<button class="ghost sm" onclick="rmFolder('${esc(f)}')">Remove</button></li>`;
    dt.innerHTML+=`<option>${esc(f)}</option>`;
  });

  // model
  pickModel(c.config.model==="ollama"?"ollama":"keyword", true);
  $("ourl").value=c.config.ollama_url||"";
  $("ochat").value=c.config.ollama_chat_model||"";
  $("ovis").value=c.config.ollama_vision_model||"";
  $("email").checked=!!c.config.email_enabled;

  // connections
  const cloud=$("cloud"); cloud.checked=cloudOn; cloud.disabled=incog;
  $("incognito").checked=incog;
  loadHistory();
}
function chip(html,on){ return `<span class="chip${on?" on":""}">${html}</span>`; }

function pickModel(m, silent){
  modelSel=m;
  document.querySelectorAll("#modelSeg button").forEach(b=>
    b.classList.toggle("on", b.dataset.m===m));
  $("ollamaFields").classList.toggle("open", m==="ollama");
  if(!silent && m==="keyword") saveModel(true);
}

async function saveConn(){
  const incog=$("incognito").checked;
  const cloud=$("cloud").checked;
  $("cloud").disabled=incog;
  await api("/dreamlayer/config",{method:"POST",body:JSON.stringify({
    network_mode: incog?"lan_only":"connected",
    cloud_enabled: incog?false:cloud})});
  toast(incog?"Incognito on — cloud off, LAN only":(cloud?"Cloud on":"Cloud off"));
  load();
}
async function addFolder(){
  const el=$("folderPath"), p=el.value.trim(); if(!p) return;
  await api("/dreamlayer/folders",{method:"POST",body:JSON.stringify({action:"add",path:p})});
  el.value=""; toast("Folder added — indexing"); load();
}
async function rmFolder(p){
  await api("/dreamlayer/folders",{method:"POST",body:JSON.stringify({action:"remove",path:p})});
  toast("Folder removed"); load();
}
async function saveModel(silent){
  await api("/dreamlayer/config",{method:"POST",body:JSON.stringify({
    model:modelSel,
    ollama_url:$("ourl").value, ollama_chat_model:$("ochat").value,
    ollama_vision_model:$("ovis").value, email_enabled:$("email").checked})});
  if(!silent) toast("Saved");
  load();
}
async function ask(){
  const q=$("q").value.trim(); if(!q) return;
  $("answer").innerHTML='<div class="ans"><div class="shimmer"></div><div class="shimmer s2"></div></div>';
  const r=await api("/dreamlayer/brain/ask",{method:"POST",body:JSON.stringify({query:q})});
  $("answer").innerHTML = r&&r.text
    ? `<div class="ans">${esc(r.text)}<div class="src">`+
      `<span class="tier">${esc(r.tier||"local")}</span>${esc((r.sources||[]).join(", "))}</div></div>`
    : `<div class="ans" style="border-left-color:var(--ghost);color:var(--muted)">Nothing in your files matches that yet.</div>`;
  loadHistory();
}
async function pair(){
  const out=$("pairout");
  out.innerHTML='<div class="paircode"><div class="shimmer"></div></div>';
  let r; try{ r=await api("/dreamlayer/pair"); }catch(e){ r=null; }
  if(!r||!r.code){
    out.innerHTML='<div class="paircode" style="border-color:var(--line)"><div class="conn-s">'+
      'Pairing is only offered from the Brain itself — open this panel on the Mac mini.</div></div>';
    return;
  }
  window._pairCode=r.code;
  out.innerHTML=`<div class="paircode"><div class="code" id="thecode">${esc(r.code)}</div>`+
    `<div class="foot"><span class="url">${esc(r.url)}</span>`+
    `<button class="sm" onclick="copyPair()">Copy code</button></div></div>`;
  toast("Pairing code ready");
}
function copyPair(){
  const code=window._pairCode||"";
  if(navigator.clipboard){ navigator.clipboard.writeText(code).then(()=>toast("Copied to clipboard")); }
  else{ const r=document.createRange(); r.selectNode($("thecode"));
        getSelection().removeAllRanges(); getSelection().addRange(r); toast("Selected — ⌘C to copy"); }
}
async function loadHistory(){
  const h=await api("/dreamlayer/history");
  $("history").innerHTML=(h.items||[]).map(x=>
    `<li><div><div class="q">${esc(x.query)}</div>`+
    `<div class="a">${esc(x.answer)}</div></div><span class="t">${esc(x.tier)}</span></li>`).join("")
    || '<li class="empty">No questions yet — ask your Brain something above.</li>';
}

// drag & drop upload
const drop=$("drop");
["dragover","dragenter"].forEach(e=>drop.addEventListener(e,ev=>{ev.preventDefault();drop.classList.add("hot")}));
["dragleave","drop"].forEach(e=>drop.addEventListener(e,ev=>{ev.preventDefault();drop.classList.remove("hot")}));
drop.addEventListener("drop",async ev=>{
  const folder=$("dropTarget").value; let n=0;
  for(const f of ev.dataTransfer.files){
    const body=await f.text();
    await fetch("/dreamlayer/upload?folder="+encodeURIComponent(folder)+"&name="+encodeURIComponent(f.name),
      {method:"POST",headers:TOKEN?{"X-DreamLayer-Token":TOKEN}:{},body}); n++;
  }
  toast(n===1?"1 file added":n+" files added"); load();
});
load();
</script></body></html>"""
