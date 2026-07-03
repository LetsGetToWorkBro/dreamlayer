"""ai_brain/server/panel.py — the control panel served at /.

A self-contained local web UI, polished to match the phone app's design
language (docs: phone-app/DESIGN.md): the same dark palette, 8-pt rhythm, soft
"arrive" motion, tactile controls, and toast feedback. It shows the live state
of every part (Brain, model, cloud, incognito, phone, index), lets you pick a
watched folder with a real folder browser, walks you through activating a
model, and logs everything you do. Vanilla JS/CSS, no build step, no external
requests. The token is injected only when opened from the Mac mini itself.
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
    --amber:#FFB454; --text:#FFFFFF; --muted:#8A9BA3; --ghost:#55666C;
    --r-sm:10px; --r-lg:18px; --r-pill:999px; --ease:cubic-bezier(.16,1,.3,1);
  }
  *{box-sizing:border-box}
  html,body{margin:0}
  body{
    background:radial-gradient(1100px 620px at 50% -8%, rgba(47,212,196,.10), transparent 60%),var(--bg);
    color:var(--text); -webkit-font-smoothing:antialiased;
    font:15px/1.55 ui-sans-serif,system-ui,-apple-system,"SF Pro Text",Segoe UI,Roboto,sans-serif;
    min-height:100vh;
  }
  .wrap{max-width:760px;margin:0 auto;padding:0 20px 96px}
  .bar{position:sticky;top:0;z-index:20;display:flex;align-items:center;gap:12px;
       padding:20px 0 16px;margin-bottom:6px;background:linear-gradient(var(--bg) 72%,transparent);backdrop-filter:blur(6px)}
  .brand{font-weight:600;letter-spacing:-.01em;font-size:1.05rem}
  .brand b{color:var(--memory)}
  .live{display:flex;align-items:center;gap:7px;margin-left:auto;color:var(--muted);
        font:12px ui-monospace,SFMono-Regular,Menlo,monospace}
  .live .dot{width:8px;height:8px;border-radius:50%;background:var(--success);
        animation:pulse 2.4s var(--ease) infinite}
  @keyframes pulse{0%{box-shadow:0 0 0 0 rgba(86,211,100,.5)}70%{box-shadow:0 0 0 7px rgba(86,211,100,0)}100%{box-shadow:0 0 0 0 rgba(86,211,100,0)}}
  h1{font-weight:700;letter-spacing:-.025em;font-size:2.4rem;margin:6px 0 2px}
  .sub{color:var(--muted);margin:0 0 20px}
  main>section{background:var(--surf);border:1px solid var(--line);border-radius:var(--r-lg);
        padding:20px;margin-bottom:14px;opacity:0;transform:translateY(14px);
        animation:rise .5s var(--ease) forwards}
  main>section:nth-child(1){animation-delay:.02s} main>section:nth-child(2){animation-delay:.06s}
  main>section:nth-child(3){animation-delay:.10s} main>section:nth-child(4){animation-delay:.14s}
  main>section:nth-child(5){animation-delay:.18s} main>section:nth-child(6){animation-delay:.22s}
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
  button:hover{filter:brightness(1.06)} button:active{transform:scale(.96)}
  button.ghost{background:transparent;color:var(--muted);border:1px solid var(--line);font-weight:500}
  button.ghost:hover{color:var(--text);border-color:var(--muted);filter:none}
  button.sm{padding:8px 12px;font-size:.85rem}
  button.danger{color:var(--error);border-color:rgba(255,92,92,.4)}
  pre{overflow-x:auto}

  /* system status */
  .sys{display:flex;align-items:center;gap:12px;padding:12px 0;border-top:1px solid var(--line)}
  .sys:first-child{border-top:0}
  .sdot{width:9px;height:9px;border-radius:50%;flex:none;background:var(--ghost)}
  .sdot.ok{background:var(--success);box-shadow:0 0 8px rgba(86,211,100,.5)}
  .sdot.warn{background:var(--amber);box-shadow:0 0 8px rgba(255,180,84,.4)}
  .sdot.off{background:var(--ghost)}
  .sname{font-size:.98rem;min-width:96px}
  .sstate{color:var(--muted);font-size:.88rem;margin-left:auto;text-align:right}
  .sstate b{color:var(--text);font-weight:600}

  /* connections + switches */
  .conn{display:flex;gap:18px;align-items:center;justify-content:space-between;padding:16px 0;border-top:1px solid var(--line)}
  .conn:first-of-type{border-top:0;padding-top:4px}
  .conn-t{font-size:1rem} .conn-s{font-size:.85rem;color:var(--muted);margin-top:3px;max-width:46ch}
  .sw{position:relative;display:inline-block;width:48px;height:28px;flex:none;cursor:pointer}
  .sw input{opacity:0;width:0;height:0;position:absolute}
  .sw .track{position:absolute;inset:0;background:#0A1113;border:1px solid var(--line);border-radius:var(--r-pill);transition:background .2s var(--ease),border-color .2s}
  .sw .track:before{content:"";position:absolute;left:3px;top:2px;width:21px;height:21px;border-radius:50%;background:var(--ghost);transition:transform .2s var(--ease),background .2s}
  .sw input:checked + .track{background:rgba(47,212,196,.22);border-color:var(--memory)}
  .sw input:checked + .track:before{transform:translateX(20px);background:var(--memory)}
  .sw input:checked + .track.red{background:rgba(255,107,94,.22);border-color:var(--attention)}
  .sw input:checked + .track.red:before{background:var(--attention)}
  .sw input:disabled + .track{opacity:.4;cursor:not-allowed}

  /* folders */
  ul{list-style:none;margin:6px 0 0;padding:0}
  li.folder{display:flex;justify-content:space-between;align-items:center;gap:12px;padding:12px 0;border-top:1px solid var(--line)}
  li.folder:first-child{border-top:0}
  .path{font:13px ui-monospace,Menlo,monospace;color:var(--muted);word-break:break-all}
  .path:before{content:"";display:inline-block;width:7px;height:7px;border-radius:2px;background:var(--memory);margin-right:9px;vertical-align:middle;opacity:.8}
  .drop{margin-top:14px;border:1.5px dashed var(--line);border-radius:14px;padding:24px;text-align:center;color:var(--ghost);transition:.15s}
  .drop.hot{border-color:var(--memory);color:var(--memory);background:rgba(47,212,196,.06)}
  .empty{color:var(--ghost);font-size:.9rem;padding:14px 0;text-align:center}

  /* segmented + model status */
  .seg{display:inline-flex;background:#0A1113;border:1px solid var(--line);border-radius:var(--r-pill);padding:3px;gap:2px}
  .seg button{background:transparent;color:var(--muted);border-radius:var(--r-pill);padding:8px 16px;font-weight:500}
  .seg button.on{background:var(--memory);color:#04120d;font-weight:600}
  .mstat{margin-top:16px;background:#0A1113;border:1px solid var(--line);border-radius:var(--r-sm);padding:16px}
  .mstat .head{display:flex;align-items:center;gap:10px;font-size:1rem;margin-bottom:4px}
  .mrow{display:flex;align-items:center;gap:10px;padding:8px 0;border-top:1px solid var(--line);font-size:.9rem}
  .mrow:first-of-type{border-top:0}
  .mrow .lbl{min-width:64px;color:var(--muted)} .mrow .nm{font:12px ui-monospace,Menlo,monospace;color:var(--text)}
  .mrow .st{margin-left:auto;font-size:.82rem}
  .ok-t{color:var(--success)} .warn-t{color:var(--amber)} .off-t{color:var(--ghost)}
  .steps{margin:10px 0 0;padding:0;counter-reset:s}
  .steps li{list-style:none;display:flex;gap:10px;padding:6px 0;color:var(--muted);font-size:.9rem;border:0}
  .steps li:before{counter-increment:s;content:counter(s);flex:none;width:20px;height:20px;border-radius:50%;
        background:rgba(47,212,196,.14);color:var(--memory);font:11px/20px ui-monospace,Menlo,monospace;text-align:center}
  code{font:12px ui-monospace,Menlo,monospace;background:#050809;border:1px solid var(--line);border-radius:6px;padding:2px 7px;color:var(--memory);user-select:all}

  /* answer + pair */
  .ans{margin-top:14px;padding:14px 16px;background:#0A1113;border-radius:var(--r-sm);border-left:2px solid var(--memory);animation:rise .35s var(--ease) both}
  .ans .src{display:inline-flex;gap:8px;align-items:center;font:11px ui-monospace,Menlo,monospace;color:var(--ghost);margin-top:8px}
  .tier{background:rgba(47,212,196,.14);color:var(--memory);border-radius:var(--r-pill);padding:2px 8px;text-transform:uppercase;letter-spacing:.08em}
  .shimmer{height:14px;border-radius:6px;margin:6px 0;background:linear-gradient(90deg,#0A1113,#182228,#0A1113);background-size:200% 100%;animation:sh 1.1s linear infinite}
  .shimmer.s2{width:70%}
  @keyframes sh{0%{background-position:200% 0}100%{background-position:-200% 0}}
  .paircode{margin-top:14px;background:#0A1113;border:1px solid var(--line);border-radius:var(--r-sm);padding:14px;animation:rise .35s var(--ease) both}
  .paircode .code{font:13px/1.5 ui-monospace,Menlo,monospace;color:var(--memory);word-break:break-all;user-select:all}
  .paircode .foot{display:flex;justify-content:space-between;align-items:center;gap:12px;margin-top:12px;flex-wrap:wrap}
  .paircode .url{font:12px ui-monospace,Menlo,monospace;color:var(--ghost)}
  .qrbox{background:#fff;border-radius:8px;padding:12px;width:max-content;max-width:100%;margin:0 auto 4px}
  .qrbox svg{display:block;width:200px;height:200px;max-width:100%}

  /* activity feed */
  .feed li{display:flex;justify-content:space-between;align-items:flex-start;gap:12px;padding:12px 0;border-top:1px solid var(--line)}
  .feed li:first-child{border-top:0}
  .feed .q{color:var(--text)} .feed .a{color:var(--muted);font-size:.9rem;margin-top:2px}
  .tag{font:10px ui-monospace,Menlo,monospace;text-transform:uppercase;letter-spacing:.08em;flex:none;padding-top:3px;color:var(--memory)}
  .tag.folder{color:var(--amber)} .tag.upload{color:var(--success)} .tag.cloud{color:var(--memory)}
  .tag.privacy{color:var(--attention)} .tag.pair{color:#8FB8FF} .tag.ask{color:var(--memory)} .tag.model,.tag.config{color:var(--muted)}

  /* modal (folder browser) */
  .overlay{position:fixed;inset:0;background:rgba(0,0,0,.6);backdrop-filter:blur(3px);z-index:60;
        display:none;align-items:center;justify-content:center;padding:20px}
  .overlay.show{display:flex}
  .modal{width:100%;max-width:560px;background:var(--surf);border:1px solid var(--line);border-radius:var(--r-lg);
        padding:20px;max-height:80vh;display:flex;flex-direction:column;animation:rise .3s var(--ease) both}
  .modal h3{margin:0 0 4px;font-weight:600} .modal .cur{font:12px ui-monospace,Menlo,monospace;color:var(--muted);word-break:break-all;margin-bottom:12px}
  .dirlist{overflow-y:auto;border:1px solid var(--line);border-radius:var(--r-sm);margin-bottom:14px}
  .diritem{display:flex;align-items:center;gap:10px;padding:11px 14px;cursor:pointer;border-bottom:1px solid var(--line);color:var(--text)}
  .diritem:last-child{border-bottom:0} .diritem:hover{background:rgba(47,212,196,.06)}
  .diritem:before{content:"";width:8px;height:8px;border-radius:2px;background:var(--memory);opacity:.7}
  .diritem.up:before{background:var(--ghost);border-radius:50%}
  .modal .mfoot{display:flex;gap:10px;justify-content:flex-end}

  #toast{position:fixed;left:50%;bottom:30px;transform:translate(-50%,20px);background:var(--surf2);
        border:1px solid var(--line);border-radius:var(--r-pill);padding:11px 20px;color:var(--text);
        font-size:.9rem;opacity:0;pointer-events:none;transition:opacity .25s var(--ease),transform .25s var(--ease);
        z-index:80;box-shadow:0 12px 40px rgba(0,0,0,.5)}
  #toast.show{opacity:1;transform:translate(-50%,0)}
  #toast .dot{display:inline-block;width:7px;height:7px;border-radius:50%;background:var(--success);margin-right:9px;vertical-align:middle}
  a{color:var(--memory)}
</style></head><body>
<div class="wrap">
  <div class="bar"><span class="brand"><b>Dream</b>Layer</span>
    <span class="live"><span class="dot"></span><span id="livetext">Brain online</span></span></div>
  <h1>Brain</h1>
  <p class="sub">This Mac mini is the brain — your files, your memory, your reach.</p>

  <main>
  <section>
    <div class="eyebrow">System</div><h2>What's connected</h2>
    <div id="sysrows"></div>
  </section>

  <section>
    <div class="eyebrow">Your day</div><h2>Morning brief</h2>
    <p class="lead">A quick synthesis of what's new and what's on you — messages, mail, and anything you're tracking.</p>
    <button onclick="brief()">Brief me</button>
    <div id="briefout"></div>
  </section>

  <section>
    <div class="eyebrow">Your day</div><h2>Agenda</h2>
    <p class="lead">Events the glasses surface and the brief leads with. Sync your macOS Calendar, or add one-off events by hand.</p>
    <div class="conn"><div><div class="conn-t">Sync macOS Calendar</div>
      <div class="conn-s">Pull upcoming events from Calendar.app automatically. Synced events refresh on their own; your hand-added ones stay put. Reads locally — nothing leaves this Mac.</div></div>
      <label class="sw"><input type="checkbox" id="calSync" onchange="saveCalSync()"><span class="track"></span></label></div>
    <div id="calPick" style="display:none;margin:2px 0 10px">
      <div class="conn-s" style="margin:0 0 6px">Which calendars <span id="calAllHint"></span></div>
      <div id="calList" class="row" style="flex-wrap:wrap;gap:10px"></div>
    </div>
    <div class="row" style="margin:0 0 10px;justify-content:space-between">
      <span id="calStatus" class="conn-s" style="margin:0"></span>
      <button class="sm ghost" onclick="syncCalNow()">Sync now</button></div>
    <ul id="agenda"></ul>
    <div class="row" style="margin-top:14px">
      <input type="text" id="evTitle" placeholder="Event — e.g. Sign the lease" style="flex:1"
        onkeydown="if(event.key==='Enter')addEvent()">
      <input type="datetime-local" id="evWhen" style="max-width:220px">
      <input type="text" id="evPlace" placeholder="place (optional)" style="max-width:180px">
      <button class="ghost" onclick="addEvent()">Add</button>
    </div>
  </section>

  <section>
    <div class="eyebrow">People</div><h2>Who you've met</h2>
    <p class="lead">The dossier registry — names you've introduced, with a note and tags. The glasses greet them with what you know.</p>
    <div class="conn"><div><div class="conn-t">Sync macOS Contacts</div>
      <div class="conn-s">Pull your address book in so dossiers populate themselves. Your hand-added notes always win. Reads locally — nothing leaves this Mac.</div></div>
      <label class="sw"><input type="checkbox" id="conSync" onchange="saveConSync()"><span class="track"></span></label></div>
    <div class="row" style="margin:0 0 10px;justify-content:space-between">
      <span id="conStatus" class="conn-s" style="margin:0"></span>
      <button class="sm ghost" onclick="syncConNow()">Sync now</button></div>
    <ul id="people"></ul>
    <div class="row" style="margin-top:14px">
      <input type="text" id="pName" placeholder="Name" style="max-width:180px"
        onkeydown="if(event.key==='Enter')addPerson()">
      <input type="text" id="pNote" placeholder="note — e.g. landlord, signing Friday" style="flex:1">
      <input type="text" id="pTags" placeholder="tags: work,lease" style="max-width:180px">
      <button class="ghost" onclick="addPerson()">Add</button>
    </div>
  </section>

  <section>
    <div class="eyebrow">To-dos</div><h2>Reminders</h2>
    <p class="lead">Open reminders from macOS Reminders.app — due ones lead the morning brief. Read-only.</p>
    <div class="conn"><div><div class="conn-t">Sync macOS Reminders</div>
      <div class="conn-s">Pull open to-dos in. Pick specific lists once you have more than one.</div></div>
      <label class="sw"><input type="checkbox" id="remSync" onchange="saveRemSync()"><span class="track"></span></label></div>
    <div id="remPick" style="display:none;margin:2px 0 10px">
      <div class="conn-s" style="margin:0 0 6px">Which lists <span id="remAllHint"></span></div>
      <div id="remList" class="row" style="flex-wrap:wrap;gap:10px"></div>
    </div>
    <div class="row" style="margin:0 0 10px;justify-content:space-between">
      <span id="remStatus" class="conn-s" style="margin:0"></span>
      <button class="sm ghost" onclick="syncRemNow()">Sync now</button></div>
    <ul id="reminders"></ul>
  </section>

  <section>
    <div class="eyebrow">Connections</div><h2>Reach &amp; devices</h2>
    <p class="lead">Pair your phone (it brings the glasses), choose how far the brain reaches, or shut the doors with Incognito.</p>
    <div class="conn"><div><div class="conn-t">Cloud</div>
      <div class="conn-s">Reach the frontier for the hardest, non-personal asks. Your files, memory and people never need it — nothing private ever leaves.</div></div>
      <label class="sw"><input type="checkbox" id="cloud" onchange="saveConn()"><span class="track"></span></label></div>
    <div class="conn"><div><div class="conn-t">Incognito</div>
      <div class="conn-s">A private stretch: stays on your LAN, forces cloud off, logs nothing.</div></div>
      <label class="sw"><input type="checkbox" id="incognito" onchange="saveConn()"><span class="track red"></span></label></div>
    <div class="conn"><div><div class="conn-t">Phone &amp; glasses</div>
      <div class="conn-s">One code wires the phone, this Brain, and your glasses together. In the app: Brain → Pair a device → scan or paste.</div></div>
      <button id="pairbtn" onclick="pair()">Pair a phone</button></div>
    <div id="pairout"></div>
  </section>

  <section>
    <div class="eyebrow">Cloud provider</div><h2>Wire the cloud tier</h2>
    <p class="lead">The Cloud switch decides whether the cloud is <i>allowed</i>. To make it actually
      answer, point it at an OpenAI-compatible provider. The key is stored only on this Mac mini and never shown again.</p>
    <div class="row">
      <input type="text" id="cbase" placeholder="https://api.openai.com" style="max-width:230px">
      <input type="password" id="ckey" placeholder="API key" style="max-width:200px">
      <input type="text" id="cmodel" placeholder="gpt-4o-mini" style="max-width:150px"></div>
    <div class="row" style="margin-top:12px;justify-content:space-between">
      <button class="sm ghost" onclick="testCloud()">Test connection</button>
      <button class="sm" onclick="saveCloud()">Save cloud</button></div>
    <div id="cloudStatus"></div>
  </section>

  <section>
    <div class="eyebrow">Knowledge</div><h2>Folders it reads</h2>
    <p class="lead">Everything in these folders is searchable — notes, PDFs, mail exports. Files never leave your Mac mini.</p>
    <ul id="folders"></ul>
    <div class="row" style="margin-top:14px">
      <button onclick="browseOpen()">Choose a folder…</button>
      <input type="text" id="folderPath" placeholder="…or paste a path" onkeydown="if(event.key==='Enter')addFolder()">
      <button class="ghost" onclick="addFolder()">Add</button>
    </div>
    <div class="drop" id="drop">Drag &amp; drop <b>files</b> here → add them to
      <select id="dropTarget" style="margin:0 4px"></select></div>
    <div class="row" style="margin-top:14px;justify-content:space-between">
      <span id="idxinfo" class="conn-s" style="margin:0"></span>
      <button class="sm ghost" onclick="reindex()">Re-index now</button></div>
    <div style="margin-top:12px"><a id="advtog" onclick="toggleAdv()" style="cursor:pointer;font-size:.85rem">Advanced filters ▸</a></div>
    <div class="fold" id="adv" style="max-height:0;overflow:hidden;opacity:0;transition:max-height .3s var(--ease),opacity .25s">
      <label class="tog" style="display:flex;gap:10px;align-items:center;color:var(--muted);cursor:pointer;margin-top:12px">
        <input type="checkbox" id="semantic" style="accent-color:var(--memory)"> Semantic search — rank by meaning (needs the Ollama embed model)</label>
      <div class="row" style="margin-top:10px">
        <input type="text" id="exts" placeholder="types: md,txt,pdf" style="max-width:200px">
        <input type="text" id="maxkb" placeholder="max KB" style="max-width:110px">
        <input type="text" id="excl" placeholder="exclude: node_modules,.git" style="max-width:220px"></div>
      <div class="row" style="margin-top:10px;justify-content:flex-end"><button class="sm" onclick="saveFilters()">Save filters</button></div>
    </div>
  </section>

  <section>
    <div class="eyebrow">Recall</div><h2>Ask your stuff</h2>
    <div class="row"><input type="text" id="q" placeholder="where's the lease? what does Marcus owe me?"
        onkeydown="if(event.key==='Enter')ask()"><button onclick="ask()">Ask</button></div>
    <div id="answer"></div>
  </section>

  <section>
    <div class="eyebrow">Intelligence</div><h2>Model</h2>
    <p class="lead">Keyword search works with no model at all. Add Ollama on this Mac mini for written answers and vision.</p>
    <div class="seg" id="modelSeg">
      <button data-m="keyword" onclick="pickModel('keyword')">Keyword</button>
      <button data-m="ollama" onclick="pickModel('ollama')">Ollama</button></div>
    <div class="fold" id="ollamaFields" style="max-height:0;overflow:hidden;opacity:0;transition:max-height .3s var(--ease),opacity .25s,margin .3s">
      <div class="row" style="margin-top:12px">
        <input type="text" id="ourl" placeholder="http://127.0.0.1:11434" style="max-width:230px">
        <input type="text" id="ochat" placeholder="chat · llama3.2" style="max-width:190px">
        <input type="text" id="ovis" placeholder="vision model" style="max-width:170px"></div>
    </div>
    <div id="modelStatus"></div>
    <div class="row" style="margin-top:16px;justify-content:space-between">
      <label class="tog" style="display:flex;gap:10px;align-items:center;color:var(--muted);cursor:pointer">
        <input type="checkbox" id="email" style="accent-color:var(--memory)"> Read email &amp; iMessage</label>
      <button class="sm" onclick="saveModel()">Save</button></div>
  </section>

  <section>
    <div class="eyebrow">Trust &amp; data</div><h2>Privacy controls</h2>
    <div class="conn"><div><div class="conn-t">Pairing token</div>
      <div class="conn-s">The secret your phone sends. Rotate it to <b>forget every paired device</b> — they'll each re-pair with the new code.</div></div>
      <div style="display:flex;gap:8px"><button class="sm ghost" onclick="showToken()">Show</button>
        <button class="sm" onclick="rotateToken()">Rotate</button></div></div>
    <div class="conn"><div><div class="conn-t">Cloud egress</div>
      <div class="conn-s" id="egress">Every time anything leaves for the cloud, it's counted and logged below.</div></div></div>
    <div class="conn"><div><div class="conn-t">Backup</div>
      <div class="conn-s">Download everything — settings, history, agenda — to restore later. Contains your keys, so keep it safe.</div></div>
      <div style="display:flex;gap:8px">
        <button class="sm ghost" onclick="backup()">Download</button>
        <button class="sm ghost" onclick="document.getElementById('restoreFile').click()">Restore</button>
        <input type="file" id="restoreFile" accept="application/json" style="display:none" onchange="restore(event)"></div></div>
    <div class="conn" style="border-bottom:0"><div><div class="conn-t">Erase</div>
      <div class="conn-s">Clear what the Brain has kept. This can't be undone.</div></div>
      <div style="display:flex;gap:8px;flex-wrap:wrap">
        <button class="sm ghost" onclick="clearData('history')">Questions</button>
        <button class="sm ghost" onclick="clearData('activity')">Activity</button>
        <button class="sm ghost danger" onclick="clearData('folders')">Folders</button></div></div>
    <div id="tokenout"></div>
  </section>

  <section id="msgCard" style="display:none">
    <div class="eyebrow">Messages</div><h2>On your glasses</h2>
    <p class="lead">This Mac is the <b>bridge</b> to your Messages &amp; Mail — it lives here, so
      the Brain relays it out. You read hands-free on the <b>glasses</b> and reply by voice with a
      tap to approve; you never touch the Mac. Texts and emails pop up separately (set on the phone).</p>
    <div class="conn" style="border-top:0;padding-top:0"><div><div class="conn-t">Summarize long emails</div>
      <div class="conn-s">Shorten emails to a one-line glance before they reach your glasses (uses the Brain's model; long ones only).</div></div>
      <label class="sw"><input type="checkbox" id="summarize" onchange="saveSummarize()"><span class="track"></span></label></div>
    <ul id="msgfeed" class="feed"></ul>
  </section>

  <section>
    <div class="eyebrow">Log</div><h2>Activity</h2>
    <ul id="history" class="feed"></ul>
  </section>

  <section>
    <div class="eyebrow">Ops</div><h2>Health &amp; schedule</h2>
    <div id="health" class="mstat" style="margin-top:0"></div>
    <div class="conn" style="margin-top:6px"><div><div class="conn-t">Quiet hours</div>
      <div class="conn-s">Auto-incognito during this window — cloud off, capture paused. Blank to disable.</div></div>
      <input type="text" id="quiet" placeholder="22:00-07:00" style="max-width:140px"></div>
    <div class="conn"><div><div class="conn-t">Morning brief</div>
      <div class="conn-s">Auto-generate the brief at this hour (0–23) for delivery to your phone/glasses. Blank = off.</div></div>
      <div class="row"><input type="text" id="briefhour" placeholder="off" style="max-width:70px"> <span class="conn-s" style="margin:0">:00</span></div></div>
    <div class="conn" style="border-bottom:0"><div><div class="conn-t">Keep memories for</div>
      <div class="conn-s">Auto-expire questions &amp; activity older than this. 0 = keep forever.</div></div>
      <div class="row"><input type="text" id="retain" placeholder="0" style="max-width:80px"> <span class="conn-s" style="margin:0">days</span>
        <button class="sm" onclick="saveOps()">Save</button></div></div>
  </section>
  </main>
</div>

<div class="overlay" id="browser">
  <div class="modal">
    <h3>Choose a folder</h3>
    <div class="cur" id="curpath">…</div>
    <div class="dirlist" id="dirlist" style="min-height:120px"></div>
    <div class="mfoot">
      <button class="ghost" onclick="browseClose()">Cancel</button>
      <button onclick="browseAdd()">Add this folder</button></div>
  </div>
</div>
<div id="toast"></div>
<script>
const TOKEN="__TOKEN__";
const H={"Content-Type":"application/json"}; if(TOKEN)H["X-DreamLayer-Token"]=TOKEN;
const api=(p,o={})=>fetch(p,Object.assign({headers:H},o)).then(r=>r.json());
const esc=s=>(s||"").replace(/[&<>]/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;"}[c]));
const $=id=>document.getElementById(id);
let modelSel="keyword", ollamaOK=null, browsePath="";

let toastT; function toast(m){const t=$("toast");t.innerHTML='<span class="dot"></span>'+esc(m);
  t.classList.add("show");clearTimeout(toastT);toastT=setTimeout(()=>t.classList.remove("show"),1900);}

async function load(){
  let c; try{c=await api("/dreamlayer/config");}catch(e){$("livetext").textContent="offline";return;}
  if(c.error){$("livetext").textContent="token needed";return;}
  const incog=c.config.network_mode==="lan_only";
  const fl=$("folders"),dt=$("dropTarget");fl.innerHTML="";dt.innerHTML="";
  const folders=c.config.folders||[];
  if(!folders.length){fl.innerHTML='<li class="empty">No folders yet — choose one below so your Brain has something to read.</li>';
    dt.innerHTML='<option value="">add a folder first</option>';}
  folders.forEach(f=>{fl.innerHTML+=`<li class="folder"><span class="path">${esc(f)}</span>`+
    `<button class="ghost sm" onclick="rmFolder('${esc(f)}')">Remove</button></li>`;
    dt.innerHTML+=`<option>${esc(f)}</option>`;});
  pickModel(c.config.model==="ollama"?"ollama":"keyword",true);
  $("ourl").value=c.config.ollama_url||"";$("ochat").value=c.config.ollama_chat_model||"";
  $("ovis").value=c.config.ollama_vision_model||"";$("email").checked=!!c.config.email_enabled;
  const cloud=$("cloud");cloud.checked=!incog&&!!c.config.cloud_enabled;cloud.disabled=incog;
  $("incognito").checked=incog;
  // cloud provider
  $("cbase").value=c.config.cloud_base_url||"";$("cmodel").value=c.config.cloud_model||"";
  $("ckey").placeholder=c.config.cloud_api_key==="set"?"key saved — leave blank to keep":"API key";
  // knowledge filters
  $("semantic").checked=!!c.config.semantic_search;
  $("exts").value=(c.config.index_extensions||[]).join(",");
  $("maxkb").value=c.config.max_file_kb||"";
  $("excl").value=(c.config.exclude_globs||[]).join(",");
  // ops
  $("quiet").value=c.config.quiet_hours||"";$("retain").value=c.config.retention_days||0;
  $("briefhour").value=(c.config.brief_hour>=0)?c.config.brief_hour:"";
  $("msgCard").style.display=c.config.email_enabled?"":"none";
  $("summarize").checked=!!c.config.summarize_emails;
  if(c.config.email_enabled) loadMessages();
  refreshStatus(); loadHistory(); loadHealth(); loadAgenda(); loadPeople(); loadCalendars();
  loadContactsSync(); loadReminders();
}

function fmtWhen(ts){if(!ts)return "";const d=new Date(ts*1000);
  return d.toLocaleString([], {weekday:"short",hour:"numeric",minute:"2-digit"});}
async function loadAgenda(){let r;try{r=await api("/dreamlayer/calendar");}catch(e){return;}
  const items=r.items||[];
  $("agenda").innerHTML=items.length?items.map(e=>{
    const synced=e.source==="calendar";
    const badge=synced?`<span class="tag">${esc(e.calendar||"Calendar")}</span>`:"";
    const rm=synced?"":`<button class="sm ghost" onclick='rmEvent(${JSON.stringify(e.title)},${e.ts})'>Remove</button>`;
    return `<li><div><div class="q">${esc(e.title)} ${badge}</div>`+
      `<div class="a">${esc(fmtWhen(e.ts))}${e.place?" · "+esc(e.place):""}</div></div>${rm}</li>`;}).join("")
    :'<li class="empty">Nothing scheduled — sync your calendar or add what you’re tracking.</li>';}
async function addEvent(){const t=$("evTitle").value.trim();if(!t)return;
  const w=$("evWhen").value; const ts=w?Math.floor(new Date(w).getTime()/1000):0;
  await api("/dreamlayer/calendar",{method:"POST",body:JSON.stringify({title:t,ts:ts,place:$("evPlace").value.trim()})});
  $("evTitle").value="";$("evWhen").value="";$("evPlace").value="";toast("Event added");loadAgenda();loadHistory();}
async function rmEvent(title,ts){await api("/dreamlayer/calendar",{method:"POST",body:JSON.stringify({remove:true,title:title,ts:ts})});
  toast("Event removed");loadAgenda();loadHistory();}

let _calSel=[];
async function loadCalendars(){let r;try{r=await api("/dreamlayer/calendars");}catch(e){return;}
  $("calSync").checked=!!r.sync;
  _calSel=r.selected||[];
  const cals=r.items||[];
  const showPicker=r.sync && cals.length>1;
  $("calPick").style.display=showPicker?"":"none";
  $("calAllHint").textContent=_calSel.length?"":"(all)";
  $("calList").innerHTML=cals.map(c=>{
    const on=_calSel.length===0||_calSel.includes(c);
    return `<label class="tog" style="display:flex;gap:6px;align-items:center;color:var(--muted);cursor:pointer">`+
      `<input type="checkbox" ${on?"checked":""} onchange="toggleCal(${JSON.stringify(c)},this.checked)" style="accent-color:var(--memory)"> ${esc(c)}</label>`;}).join("");
  const ls=r.last_sync?("Last synced "+fmtWhen(r.last_sync)):(r.sync?"Syncing…":"Sync is off");
  $("calStatus").textContent=ls;}
async function toggleCal(name,on){
  // build the explicit selected-list from the current checkboxes
  const boxes=[...$("calList").querySelectorAll("input")];
  const cals=boxes.map(b=>b.parentElement.textContent.trim());
  let sel=[];boxes.forEach((b,i)=>{if(b.checked)sel.push(cals[i]);});
  if(sel.length===cals.length)sel=[];              // all ticked = "all" = empty
  await api("/dreamlayer/config",{method:"POST",body:JSON.stringify({calendar_names:sel})});
  toast("Calendars updated");loadAgenda();loadCalendars();}
async function saveCalSync(){const on=$("calSync").checked;
  await api("/dreamlayer/config",{method:"POST",body:JSON.stringify({calendar_sync:on})});
  toast(on?"Calendar sync on":"Calendar sync off");loadCalendars();loadAgenda();}
async function syncCalNow(){$("calStatus").textContent="Syncing…";
  const r=await api("/dreamlayer/calendar/sync",{method:"POST",body:"{}"});
  toast(`Synced ${r.synced||0} event(s)`);loadAgenda();loadCalendars();loadHistory();}

async function loadPeople(){let r;try{r=await api("/dreamlayer/people");}catch(e){return;}
  const items=r.items||[];
  $("people").innerHTML=items.length?items.map(p=>{
    const tags=(p.tags||[]).map(t=>`<span class="tag">${esc(t)}</span>`).join(" ");
    const synced=p.source==="contacts";
    const badge=synced?`<span class="tag">contact</span>`:"";
    const rm=synced?"":`<button class="sm ghost" onclick='rmPerson(${JSON.stringify(p.name)})'>Remove</button>`;
    return `<li><div><div class="q">${esc(p.name)} ${badge}</div>`+
      `<div class="a">${esc(p.note||"")} ${tags}</div></div>${rm}</li>`;}).join("")
    :'<li class="empty">No one yet — introduce people or sync your Contacts.</li>';}
async function addPerson(){const n=$("pName").value.trim();if(!n)return;
  const tags=$("pTags").value.split(",").map(s=>s.trim()).filter(Boolean);
  await api("/dreamlayer/people",{method:"POST",body:JSON.stringify({name:n,note:$("pNote").value.trim(),tags:tags})});
  $("pName").value="";$("pNote").value="";$("pTags").value="";toast("Person added");loadPeople();loadHistory();}
async function rmPerson(name){await api("/dreamlayer/people",{method:"POST",body:JSON.stringify({remove:true,name:name})});
  toast("Removed");loadPeople();loadHistory();}
async function loadContactsSync(){let r;try{r=await api("/dreamlayer/contacts");}catch(e){return;}
  $("conSync").checked=!!r.sync;
  $("conStatus").textContent=r.last_sync?`${r.count||0} contact(s) · synced ${fmtWhen(r.last_sync)}`:(r.sync?"Syncing…":"Contacts sync is off");}
async function saveConSync(){const on=$("conSync").checked;
  await api("/dreamlayer/config",{method:"POST",body:JSON.stringify({contacts_sync:on})});
  toast(on?"Contacts sync on":"Contacts sync off");loadContactsSync();loadPeople();}
async function syncConNow(){$("conStatus").textContent="Syncing…";
  const r=await api("/dreamlayer/contacts/sync",{method:"POST",body:"{}"});
  toast(`Synced ${r.synced||0} contact(s)`);loadPeople();loadContactsSync();loadHistory();}

async function loadReminders(){let r;try{r=await api("/dreamlayer/reminders");}catch(e){return;}
  $("remSync").checked=!!r.sync;
  const lists=r.lists||[]; const sel=r.selected||[];
  $("remPick").style.display=(r.sync&&lists.length>1)?"":"none";
  $("remAllHint").textContent=sel.length?"":"(all)";
  $("remList").innerHTML=lists.map(c=>{const on=sel.length===0||sel.includes(c);
    return `<label class="tog" style="display:flex;gap:6px;align-items:center;color:var(--muted);cursor:pointer">`+
      `<input type="checkbox" ${on?"checked":""} onchange="toggleRemList()" style="accent-color:var(--memory)"> ${esc(c)}</label>`;}).join("");
  $("remStatus").textContent=r.last_sync?`${(r.items||[]).length} open · synced ${fmtWhen(r.last_sync)}`:(r.sync?"Syncing…":"Reminders sync is off");
  const items=r.items||[];
  $("reminders").innerHTML=items.length?items.map(t=>
    `<li><div><div class="q">${esc(t.title)}</div><div class="a">${t.ts?esc(fmtWhen(t.ts)):"no due date"}${t.list?" · "+esc(t.list):""}</div></div></li>`).join("")
    :'<li class="empty">No open reminders.</li>';}
async function toggleRemList(){const boxes=[...$("remList").querySelectorAll("input")];
  const names=boxes.map(b=>b.parentElement.textContent.trim());
  let sel=[];boxes.forEach((b,i)=>{if(b.checked)sel.push(names[i]);});
  if(sel.length===names.length)sel=[];
  await api("/dreamlayer/config",{method:"POST",body:JSON.stringify({reminder_lists:sel})});
  toast("Lists updated");loadReminders();}
async function saveRemSync(){const on=$("remSync").checked;
  await api("/dreamlayer/config",{method:"POST",body:JSON.stringify({reminders_sync:on})});
  toast(on?"Reminders sync on":"Reminders sync off");loadReminders();}
async function syncRemNow(){$("remStatus").textContent="Syncing…";
  const r=await api("/dreamlayer/reminders/sync",{method:"POST",body:"{}"});
  toast(`Synced ${r.synced||0} reminder(s)`);loadReminders();loadHistory();}

function sysRow(name,state,cls){return `<div class="sys"><span class="sdot ${cls}"></span>`+
  `<span class="sname">${name}</span><span class="sstate">${state}</span></div>`;}
async function refreshStatus(){
  let s; try{s=await api("/dreamlayer/status");}catch(e){return;}
  if(s.error)return;
  const phone = s.phone_ago==null ? ["Not paired yet","off"]
    : s.phone_ago<120 ? [`Connected · seen ${s.phone_ago}s ago`,"ok"]
    : [`Paired · last seen ${Math.floor(s.phone_ago/60)}m ago`,"warn"];
  const model = s.model==="ollama"
    ? (ollamaOK===true?["Ollama · reachable","ok"]:ollamaOK===false?["Ollama · needs setup","warn"]:["Ollama · checking…","warn"])
    : ["Keyword · active","ok"];
  const cloudTxt = s.cloud ? (s.cloud_ready?"<b>On · ready</b>":"<b>On · not configured</b>") : "Off";
  const incogTxt = s.incognito ? (s.quiet?"<b>On · quiet hours</b>":"<b>On</b>") : "Off";
  $("sysrows").innerHTML=
    sysRow("Brain","<b>Online</b>","ok")+
    sysRow("Model",`<b>${model[0]}</b>`,model[1])+
    sysRow("Cloud",cloudTxt,s.cloud?(s.cloud_ready?"ok":"warn"):"off")+
    sysRow("Incognito",incogTxt,s.incognito?"warn":"off")+
    sysRow("Phone",phone[0].replace(/^([^·]+)/,'<b>$1</b>'),phone[1])+
    sysRow("Index",`<b>${s.stats.files}</b> files · <b>${s.stats.passages}</b> passages`,s.stats.files?"ok":"off")+
    ((s.missing&&s.missing.length)?sysRow("⚠ Folders",`<b>${s.missing.length}</b> missing`,"warn"):"");
  $("egress").innerHTML=`The cloud has been used <b>${s.cloud_calls||0}</b> time${s.cloud_calls===1?'':'s'} since setup — every one is logged below.`;
  const idxa=s.index_ago==null?"never":s.index_ago<90?"just now":s.index_ago<3600?Math.floor(s.index_ago/60)+"m ago":Math.floor(s.index_ago/3600)+"h ago";
  let info=`Indexed ${idxa}`;
  if(s.email_docs) info+=` · ${s.email_docs} mail/chat docs`;
  if(s.missing&&s.missing.length) info+=` · <span style="color:var(--amber)">${s.missing.length} folder(s) missing</span>`;
  $("idxinfo").innerHTML=info;
}

async function saveConn(){
  const incog=$("incognito").checked, cloud=$("cloud").checked; $("cloud").disabled=incog;
  await api("/dreamlayer/config",{method:"POST",body:JSON.stringify({
    network_mode:incog?"lan_only":"connected", cloud_enabled:incog?false:cloud})});
  toast(incog?"Incognito on — cloud off, LAN only":(cloud?"Cloud on":"Cloud off")); load();
}
async function addFolder(){const el=$("folderPath"),p=el.value.trim();if(!p)return;
  await api("/dreamlayer/folders",{method:"POST",body:JSON.stringify({action:"add",path:p})});
  el.value="";toast("Folder added — indexing");load();}
async function rmFolder(p){await api("/dreamlayer/folders",{method:"POST",body:JSON.stringify({action:"remove",path:p})});
  toast("Folder removed");load();}

/* folder browser */
async function browseOpen(path){$("browser").classList.add("show");await browseTo(path||"");}
function browseClose(){$("browser").classList.remove("show");}
async function browseTo(path){
  let r; try{r=await api("/dreamlayer/browse?path="+encodeURIComponent(path||""));}catch(e){toast("Can't browse from here");return;}
  if(r.error){toast("Folder browsing is local-only — open localhost");return;}
  browsePath=r.path; $("curpath").textContent=r.path;
  let html="";
  if(r.parent) html+=`<div class="diritem up" onclick="browseTo('${esc(r.parent)}')">.. up one level</div>`;
  (r.dirs||[]).forEach(d=>{const full=(r.path.endsWith('/')?r.path:r.path+'/')+d;
    html+=`<div class="diritem" onclick="browseTo('${esc(full)}')">${esc(d)}</div>`;});
  if(!(r.dirs||[]).length && !r.parent) html+='<div class="empty">No subfolders here</div>';
  $("dirlist").innerHTML=html||'<div class="empty">No subfolders here</div>';
}
async function browseAdd(){if(!browsePath)return;
  await api("/dreamlayer/folders",{method:"POST",body:JSON.stringify({action:"add",path:browsePath})});
  browseClose();toast("Watching "+browsePath.split('/').pop());load();}

/* model setup */
function pickModel(m,silent){modelSel=m;
  document.querySelectorAll("#modelSeg button").forEach(b=>b.classList.toggle("on",b.dataset.m===m));
  const f=$("ollamaFields"),on=m==="ollama";
  f.style.maxHeight=on?"200px":"0";f.style.opacity=on?"1":"0";f.style.marginTop=on?"12px":"0";
  if(!silent&&m==="keyword"){saveModel(true);}
  renderModel();
  if(m==="ollama") checkModel();
}
function renderModel(){
  const el=$("modelStatus");
  if(modelSel==="keyword"){ollamaOK=null;
    el.innerHTML='<div class="mstat"><div class="head"><span class="sdot ok"></span>'+
      '<b>Active</b></div><div class="lead" style="margin:0">Keyword search over your files. '+
      'No model, no setup — works fully offline.</div></div>'; refreshStatus(); return;}
  el.innerHTML='<div class="mstat"><div class="shimmer"></div><div class="shimmer s2"></div></div>';
}
async function checkModel(){
  if(modelSel!=="ollama")return;
  let r; try{r=await api("/dreamlayer/model/status");}catch(e){r={reachable:false};}
  ollamaOK=!!r.reachable; refreshStatus();
  const el=$("modelStatus");
  if(!r.reachable){
    el.innerHTML='<div class="mstat"><div class="head"><span class="sdot warn"></span>'+
      `<b>Ollama isn't running</b></div><div class="lead" style="margin:0 0 4px">`+
      `Not reachable at <code>${esc(r.url||"http://127.0.0.1:11434")}</code>. Set it up on this Mac mini:</div>`+
      '<ol class="steps">'+
      '<li><code>brew install ollama</code></li>'+
      '<li><code>ollama serve</code> &nbsp;(leave it running)</li>'+
      '<li><code>ollama pull llama3.2 llama3.2-vision nomic-embed-text</code></li>'+
      '<li>Set the URL/models above, hit <b>Save</b>, then <b>Check again</b></li></ol>'+
      '<div style="margin-top:12px"><button class="sm" onclick="checkModel()">Check again</button></div></div>';
    return;
  }
  const rows=[["Chat",r.want.chat,r.have.chat],["Vision",r.want.vision,r.have.vision],["Embed",r.want.embed,r.have.embed]];
  let miss=[];
  let body=rows.map(([lbl,nm,have])=>{
    if(!nm)return `<div class="mrow"><span class="lbl">${lbl}</span><span class="nm off-t">not set</span><span class="st off-t">optional</span></div>`;
    if(!have)miss.push(nm);
    return `<div class="mrow"><span class="lbl">${lbl}</span><span class="nm">${esc(nm)}</span>`+
      `<span class="st ${have?'ok-t':'warn-t'}">${have?'✓ ready':'not pulled'}</span></div>`;}).join("");
  let pull = miss.length?`<div class="lead" style="margin:12px 0 0">Pull the missing model${miss.length>1?'s':''}: `+
      `<code>ollama pull ${esc(miss.join(' '))}</code></div>`:'';
  el.innerHTML='<div class="mstat"><div class="head"><span class="sdot ok"></span>'+
    `<b>Ollama reachable</b></div><div class="lead" style="margin:0 0 8px">at <code>${esc(r.url)}</code></div>`+
    body+pull+'<div style="margin-top:12px"><button class="sm ghost" onclick="checkModel()">Check again</button></div></div>';
}
async function saveModel(silent){
  await api("/dreamlayer/config",{method:"POST",body:JSON.stringify({model:modelSel,
    ollama_url:$("ourl").value,ollama_chat_model:$("ochat").value,
    ollama_vision_model:$("ovis").value,email_enabled:$("email").checked})});
  if(!silent)toast("Saved"); if(modelSel==="ollama")checkModel(); load();
}
async function ask(){const q=$("q").value.trim();if(!q)return;
  $("answer").innerHTML='<div class="ans"><div class="shimmer"></div><div class="shimmer s2"></div></div>';
  const r=await api("/dreamlayer/brain/ask",{method:"POST",body:JSON.stringify({query:q})});
  $("answer").innerHTML=r&&r.text?`<div class="ans">${esc(r.text)}<div class="src">`+
    `<span class="tier">${esc(r.tier||"local")}</span>${esc((r.sources||[]).join(", "))}</div></div>`
    :'<div class="ans" style="border-left-color:var(--ghost);color:var(--muted)">Nothing in your files matches that yet.</div>';
  loadHistory();
}
async function brief(){const o=$("briefout");
  o.innerHTML='<div class="ans"><div class="shimmer"></div><div class="shimmer s2"></div></div>';
  const r=await api("/dreamlayer/brief",{method:"POST",body:"{}"});
  const miss=r.missed?`${r.missed.texts} text(s) · ${r.missed.emails} email(s)`:"";
  o.innerHTML=`<div class="ans">${esc(r.text)}<div class="src">${esc(miss)}</div></div>`;}
async function pair(){const out=$("pairout");out.innerHTML='<div class="paircode"><div class="shimmer"></div></div>';
  let r;try{r=await api("/dreamlayer/pair");}catch(e){r=null;}
  if(!r||!r.code){out.innerHTML='<div class="paircode" style="border-color:var(--line)"><div class="conn-s">'+
    'Pairing is offered only from the Brain itself. On the Mac mini open <b>http://localhost:7777/</b> '+
    '(not the network address) and try again — the code still points your phone at this Mac\'s LAN address.</div></div>';return;}
  window._pc=r.code;
  const qr=r.qr?`<div class="qrbox">${r.qr}</div><div class="conn-s" style="margin:6px 0 10px">Scan this in the phone app → Brain → Pair a device</div>`:"";
  out.innerHTML=`<div class="paircode">${qr}<div class="code" id="thecode">${esc(r.code)}</div>`+
    `<div class="foot"><span class="url">${esc(r.url)}</span><button class="sm" onclick="copyPair()">Copy code</button></div></div>`;
  toast("Pairing code ready");
}
function copyPair(){const c=window._pc||"";if(navigator.clipboard){navigator.clipboard.writeText(c).then(()=>toast("Copied"));}
  else{const r=document.createRange();r.selectNode($("thecode"));getSelection().removeAllRanges();getSelection().addRange(r);toast("Selected — ⌘C");}}
async function loadHistory(){const h=await api("/dreamlayer/history");
  $("history").innerHTML=(h.items||[]).map(x=>{
    const tag=x.kind==="ask"?(x.tier||"ask"):x.kind;
    const title=x.kind==="ask"?x.query:x.text;
    const sub=x.kind==="ask"?x.text:"";
    return `<li><div><div class="q">${esc(title)}</div>`+(sub?`<div class="a">${esc(sub)}</div>`:"")+
      `</div><span class="tag ${esc(x.kind)}">${esc(tag)}</span></li>`;}).join("")
    ||'<li class="empty">Nothing yet — add a folder, ask a question, pair your phone.</li>';
}

/* cloud provider */
async function saveCloud(){const body={cloud_base_url:$("cbase").value,cloud_model:$("cmodel").value};
  const k=$("ckey").value.trim(); if(k) body.cloud_api_key=k;
  await api("/dreamlayer/config",{method:"POST",body:JSON.stringify(body)});$("ckey").value="";
  toast("Cloud provider saved");load();}
async function testCloud(){const el=$("cloudStatus");el.innerHTML='<div class="mstat"><div class="shimmer"></div></div>';
  await saveCloud();
  const r=await api("/dreamlayer/cloud/test",{method:"POST",body:"{}"});
  el.innerHTML=`<div class="mstat"><div class="head"><span class="sdot ${r.ok?'ok':'warn'}"></span>`+
    `<b>${r.ok?'Connected':'Not working'}</b></div><div class="lead" style="margin:0">`+
    (r.ok?`Provider replied: <code>${esc(r.reply||'ok')}</code>`:`${esc(r.error||'no reply — check the key, URL and model')}`)+`</div></div>`;
}

/* trust & data */
async function showToken(){const r=await api("/dreamlayer/token");const o=$("tokenout");
  if(!r||r.error){o.innerHTML='<div class="paircode"><div class="conn-s">Open http://localhost:7777/ on the Mac mini to see the token.</div></div>';return;}
  o.innerHTML=`<div class="paircode"><div class="code">${esc(r.token||'(none set)')}</div></div>`;}
async function rotateToken(){if(!confirm("Rotate the token? Every paired phone will need to pair again."))return;
  const r=await api("/dreamlayer/token/rotate",{method:"POST",body:"{}"});
  $("tokenout").innerHTML=`<div class="paircode"><div class="code">${esc(r.token)}</div>`+
    `<div class="foot"><span class="url">new token — re-pair your phone</span></div></div>`;toast("Token rotated");load();}
async function clearData(what){const names={history:"all questions",activity:"the activity log",folders:"all watched folders"};
  if(!confirm("Erase "+names[what]+"? This can't be undone."))return;
  await api("/dreamlayer/clear",{method:"POST",body:JSON.stringify({what})});toast("Erased "+what);load();}
async function reindex(){toast("Re-indexing…");const r=await api("/dreamlayer/reindex",{method:"POST",body:"{}"});
  toast("Indexed "+(r.stats?r.stats.files:0)+" files");load();}
async function backup(){const r=await api("/dreamlayer/backup");
  if(r.error){toast("Backup is local-only — open localhost");return;}
  const blob=new Blob([JSON.stringify(r,null,2)],{type:"application/json"});
  const a=document.createElement("a");a.href=URL.createObjectURL(blob);
  a.download="dreamlayer-backup.json";a.click();URL.revokeObjectURL(a.href);toast("Backup downloaded");}
async function restore(ev){const f=ev.target.files&&ev.target.files[0];ev.target.value="";if(!f)return;
  if(!confirm("Restore from this backup? It replaces your current settings, history and agenda."))return;
  try{const data=JSON.parse(await f.text());
    const r=await api("/dreamlayer/restore",{method:"POST",body:JSON.stringify(data)});
    if(r.error){toast(r.error);}else{toast("Restored");load();}}
  catch(e){toast("That's not a valid backup file");}}

/* knowledge filters */
function toggleAdv(){const a=$("adv"),open=a.style.maxHeight!=="0px"&&a.style.maxHeight!=="";
  a.style.maxHeight=open?"0":"260px";a.style.opacity=open?"0":"1";
  $("advtog").textContent=open?"Advanced filters ▸":"Advanced filters ▾";}
async function saveFilters(){
  await api("/dreamlayer/config",{method:"POST",body:JSON.stringify({
    semantic_search:$("semantic").checked,
    index_extensions:$("exts").value.split(",").map(x=>x.trim()).filter(Boolean),
    max_file_kb:parseInt($("maxkb").value)||2000,
    exclude_globs:$("excl").value.split(",").map(x=>x.trim()).filter(Boolean)})});
  toast("Filters saved — re-indexing");load();}

/* messages — the read feed the glasses surface (reply happens on the glasses) */
async function loadMessages(){let r;try{r=await api("/dreamlayer/messages/recent");}catch(e){return;}
  const ul=$("msgfeed");
  if(!r.items||!r.items.length){ul.innerHTML='<li class="empty">No recent messages'+
    (r.enabled?' — nothing to relay right now.':'. Turn on “Read email &amp; iMessage” to relay them to your glasses.')+'</li>';return;}
  ul.innerHTML=r.items.map(m=>{
    const who=m.from_me?"You":esc(m.who||"unknown");
    const raw=m.summary?m.summary:(m.subject?m.subject+" — "+(m.text||""):(m.text||""));
    const body=esc(raw).slice(0,160)+(m.summary?' ':'');
    const tag=m.summary?'summary':m.channel;
    return `<li><div><div class="q">${who}</div><div class="a">${body}</div></div>`+
      `<span class="tag ${m.channel==='email'?'config':'pair'}">${esc(tag)}</span></li>`;}).join("");
}
async function saveSummarize(){
  await api("/dreamlayer/config",{method:"POST",body:JSON.stringify({summarize_emails:$("summarize").checked})});
  toast($("summarize").checked?"Emails will be summarized":"Full emails");load();
}

/* ops */
async function saveOps(){const bh=$("briefhour").value.trim();
  await api("/dreamlayer/config",{method:"POST",body:JSON.stringify({
    quiet_hours:$("quiet").value.trim(),retention_days:parseInt($("retain").value)||0,
    brief_hour:bh===""?-1:(parseInt(bh)||0)})});
  toast("Schedule saved");load();}
async function loadHealth(){let h;try{h=await api("/dreamlayer/health");}catch(e){return;}
  const up=h.uptime_s<3600?Math.floor(h.uptime_s/60)+"m":Math.floor(h.uptime_s/3600)+"h";
  $("health").innerHTML=
    `<div class="mrow"><span class="lbl">Version</span><span class="nm">v${esc(h.version)}</span><span class="st off-t">running</span></div>`+
    `<div class="mrow"><span class="lbl">Index</span><span class="nm">${h.disk_kb} KB</span><span class="st off-t">on disk</span></div>`+
    `<div class="mrow"><span class="lbl">Model</span><span class="nm">${h.ollama_ms==null?'—':h.ollama_ms+' ms'}</span><span class="st ${h.ollama_ms==null?'off-t':'ok-t'}">${h.ollama_ms==null?'keyword / offline':'ollama latency'}</span></div>`+
    `<div class="mrow"><span class="lbl">Uptime</span><span class="nm">${up}</span><span class="st off-t">since boot</span></div>`;
}

/* drag & drop — files only */
const drop=$("drop");
["dragover","dragenter"].forEach(e=>drop.addEventListener(e,ev=>{ev.preventDefault();drop.classList.add("hot")}));
["dragleave"].forEach(e=>drop.addEventListener(e,ev=>{ev.preventDefault();drop.classList.remove("hot")}));
drop.addEventListener("drop",async ev=>{
  ev.preventDefault();drop.classList.remove("hot");
  let hasDir=false; const items=ev.dataTransfer.items;
  if(items){for(const it of items){const e=it.webkitGetAsEntry&&it.webkitGetAsEntry();if(e&&e.isDirectory)hasDir=true;}}
  if(hasDir){toast('Use "Choose a folder…" to watch a whole directory');return;}
  const files=ev.dataTransfer.files;
  if(!files||!files.length){toast("Drop files here to add them");return;}
  const folder=$("dropTarget").value;
  if(!folder){toast("Add a folder first, then drop files into it");return;}
  let n=0;
  for(const f of files){const body=await f.text();
    await fetch("/dreamlayer/upload?folder="+encodeURIComponent(folder)+"&name="+encodeURIComponent(f.name),
      {method:"POST",headers:TOKEN?{"X-DreamLayer-Token":TOKEN}:{},body});n++;}
  toast(n===1?"1 file added":n+" files added");load();
});
$("browser").addEventListener("click",e=>{if(e.target.id==="browser")browseClose();});

load();
setInterval(refreshStatus,4000);
setInterval(()=>{if(modelSel==="ollama")checkModel();},15000);
</script></body></html>"""
