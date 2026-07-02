"""ai_brain/server/panel.py — the control panel served at /.

A self-contained local web UI: manage watched folders, drag-drop files in,
pick the model, flip connections, ask a question, and see your history.
Vanilla JS, no build step. The token is injected when the panel is opened
from the Mac mini itself (localhost); a remote browser gets a blank field.
"""
from __future__ import annotations


def render_panel(token: str = "") -> str:
    return _PAGE.replace("__TOKEN__", token or "")


_PAGE = r"""<!doctype html><html lang="en"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>DreamLayer Brain</title>
<style>
  :root{--bg:#070A0B;--surf:#0E1518;--line:#1C2E33;--memory:#2CC79A;
        --text:#ECF0F1;--muted:#93A6AD;--ghost:#55666C;--bloom:#7A6BE0}
  *{box-sizing:border-box}
  body{margin:0;background:var(--bg);color:var(--text);
       font:15px/1.55 ui-sans-serif,system-ui,-apple-system,Segoe UI,Roboto,sans-serif}
  .wrap{max-width:840px;margin:0 auto;padding:28px 20px 80px}
  h1{font-weight:300;letter-spacing:-.02em;font-size:1.9rem;margin:0 0 4px}
  .eyebrow{font:12px ui-monospace,SFMono-Regular,Menlo,monospace;letter-spacing:.22em;
           text-transform:uppercase;color:var(--memory)}
  .card{background:var(--surf);border:1px solid var(--line);border-radius:14px;
        padding:18px 18px 20px;margin-top:16px}
  h2{font-weight:400;font-size:1.05rem;margin:0 0 12px;letter-spacing:-.01em}
  .row{display:flex;gap:8px;align-items:center;flex-wrap:wrap}
  input,select{background:#0A1113;border:1px solid var(--line);color:var(--text);
        border-radius:9px;padding:9px 11px;font:inherit}
  input[type=text]{flex:1;min-width:180px}
  button{background:var(--memory);color:#04120d;border:0;border-radius:9px;
         padding:9px 15px;font:inherit;font-weight:600;cursor:pointer}
  button.ghost{background:transparent;color:var(--muted);border:1px solid var(--line);font-weight:400}
  ul{list-style:none;margin:8px 0 0;padding:0}
  li{display:flex;justify-content:space-between;align-items:center;gap:10px;
     padding:8px 0;border-top:1px solid var(--line);font-size:.94rem}
  li .path{font:13px ui-monospace,Menlo,monospace;color:var(--muted);word-break:break-all}
  .drop{margin-top:12px;border:1.5px dashed var(--line);border-radius:12px;
        padding:22px;text-align:center;color:var(--ghost);transition:.15s}
  .drop.hot{border-color:var(--memory);color:var(--memory);background:rgba(44,199,154,.05)}
  .stat{display:flex;gap:22px;color:var(--muted);font-size:.9rem;margin-top:6px}
  .stat b{color:var(--text);font-weight:500}
  .ans{margin-top:12px;padding:12px 14px;border-left:2px solid var(--memory);
       background:#0A1113;border-radius:0 9px 9px 0}
  .ans .src{font:12px ui-monospace,Menlo,monospace;color:var(--ghost);margin-top:6px}
  .hist{font-size:.9rem}
  .hist .q{color:var(--text)}.hist .a{color:var(--muted)}
  .hist .t{font:11px ui-monospace,Menlo,monospace;color:var(--bloom);text-transform:uppercase}
  label.tog{display:flex;gap:9px;align-items:center;color:var(--muted);cursor:pointer}
  .mono{font:13px ui-monospace,Menlo,monospace}
  a{color:var(--memory)}
</style></head><body><div class="wrap">
  <span class="eyebrow">DreamLayer</span>
  <h1>Brain</h1>
  <div class="stat" id="stat"></div>

  <div class="card">
    <h2>Folders it reads</h2>
    <ul id="folders"></ul>
    <div class="row" style="margin-top:12px">
      <input type="text" id="folderPath" placeholder="/Users/you/Documents/DreamLayer">
      <button onclick="addFolder()">Add folder</button>
    </div>
    <div class="drop" id="drop">drag &amp; drop files here to add them to
      <select id="dropTarget" style="margin:0 4px"></select></div>
  </div>

  <div class="card">
    <h2>Ask your stuff</h2>
    <div class="row">
      <input type="text" id="q" placeholder="where's the lease? what does Marcus owe me?"
             onkeydown="if(event.key==='Enter')ask()">
      <button onclick="ask()">Ask</button>
    </div>
    <div id="answer"></div>
  </div>

  <div class="card">
    <h2>Model</h2>
    <div class="row">
      <label class="tog"><input type="radio" name="model" value="keyword" id="mk"> Keyword (no model, works now)</label>
      <label class="tog"><input type="radio" name="model" value="ollama" id="mo"> Ollama (local model)</label>
    </div>
    <div class="row" style="margin-top:10px">
      <input type="text" id="ourl" placeholder="http://127.0.0.1:11434" style="max-width:220px">
      <input type="text" id="ochat" placeholder="chat model, e.g. llama3.2" style="max-width:190px">
      <input type="text" id="ovis" placeholder="vision model" style="max-width:170px">
    </div>
    <div class="row" style="margin-top:10px">
      <label class="tog"><input type="checkbox" id="email"> Read email &amp; iMessage</label>
      <label class="tog"><input type="checkbox" id="cloud"> Allow cloud for hard cases</label>
      <button onclick="saveModel()">Save</button>
    </div>
  </div>

  <div class="card">
    <h2>History</h2>
    <ul id="history" class="hist"></ul>
  </div>
</div>
<script>
const TOKEN="__TOKEN__";
const H={"Content-Type":"application/json"}; if(TOKEN)H["X-DreamLayer-Token"]=TOKEN;
const api=(p,o={})=>fetch(p,Object.assign({headers:H},o)).then(r=>r.json());
const esc=s=>(s||"").replace(/[&<>]/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;"}[c]));

async function load(){
  const c=await api("/dreamlayer/config");
  document.getElementById("stat").innerHTML=
    `<span><b>${c.stats.files}</b> files</span><span><b>${c.stats.passages}</b> passages</span>`+
    `<span>model <b>${c.config.model}</b></span>`;
  const fl=document.getElementById("folders");fl.innerHTML="";
  const dt=document.getElementById("dropTarget");dt.innerHTML="";
  (c.config.folders||[]).forEach(f=>{
    fl.innerHTML+=`<li><span class="path">${esc(f)}</span>`+
      `<button class="ghost" onclick="rmFolder('${esc(f)}')">remove</button></li>`;
    dt.innerHTML+=`<option>${esc(f)}</option>`;
  });
  document.getElementById("mk").checked=c.config.model==="keyword";
  document.getElementById("mo").checked=c.config.model==="ollama";
  document.getElementById("ourl").value=c.config.ollama_url||"";
  document.getElementById("ochat").value=c.config.ollama_chat_model||"";
  document.getElementById("ovis").value=c.config.ollama_vision_model||"";
  document.getElementById("email").checked=!!c.config.email_enabled;
  document.getElementById("cloud").checked=!!c.config.cloud_enabled;
  loadHistory();
}
async function addFolder(){
  const p=document.getElementById("folderPath").value.trim();if(!p)return;
  await api("/dreamlayer/folders",{method:"POST",body:JSON.stringify({action:"add",path:p})});
  document.getElementById("folderPath").value="";load();
}
async function rmFolder(p){
  await api("/dreamlayer/folders",{method:"POST",body:JSON.stringify({action:"remove",path:p})});load();
}
async function saveModel(){
  await api("/dreamlayer/config",{method:"POST",body:JSON.stringify({
    model:document.getElementById("mo").checked?"ollama":"keyword",
    ollama_url:document.getElementById("ourl").value,
    ollama_chat_model:document.getElementById("ochat").value,
    ollama_vision_model:document.getElementById("ovis").value,
    email_enabled:document.getElementById("email").checked,
    cloud_enabled:document.getElementById("cloud").checked})});load();
}
async function ask(){
  const q=document.getElementById("q").value.trim();if(!q)return;
  const a=document.getElementById("answer");a.innerHTML="<div class='ans'>thinking…</div>";
  const r=await api("/dreamlayer/brain/ask",{method:"POST",body:JSON.stringify({query:q})});
  a.innerHTML=r&&r.text?`<div class="ans">${esc(r.text)}`+
    `<div class="src">${esc(r.tier)} · ${esc((r.sources||[]).join(", "))}</div></div>`
    :`<div class="ans">nothing in your files matches that yet.</div>`;
  loadHistory();
}
async function loadHistory(){
  const h=await api("/dreamlayer/history");const ul=document.getElementById("history");
  ul.innerHTML=(h.items||[]).map(x=>
    `<li><div><div class="q">${esc(x.query)}</div>`+
    `<div class="a">${esc(x.answer)}</div></div><span class="t">${esc(x.tier)}</span></li>`).join("")
    ||"<li style='color:var(--ghost)'>no questions yet</li>";
}
// drag & drop upload
const drop=document.getElementById("drop");
["dragover","dragenter"].forEach(e=>drop.addEventListener(e,ev=>{ev.preventDefault();drop.classList.add("hot")}));
["dragleave","drop"].forEach(e=>drop.addEventListener(e,ev=>{ev.preventDefault();drop.classList.remove("hot")}));
drop.addEventListener("drop",async ev=>{
  const folder=document.getElementById("dropTarget").value;
  for(const f of ev.dataTransfer.files){
    const body=await f.text();
    await fetch("/dreamlayer/upload?folder="+encodeURIComponent(folder)+"&name="+encodeURIComponent(f.name),
      {method:"POST",headers:TOKEN?{"X-DreamLayer-Token":TOKEN}:{},body});
  }
  load();
});
load();
</script></body></html>"""
