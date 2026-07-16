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
<link rel="icon" href='data:image/svg+xml,<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64"><circle cx="32" cy="32" r="26" fill="none" stroke="%232CC79A" stroke-width="4"/><circle cx="32" cy="32" r="6" fill="%232CC79A"/></svg>'>
<style>
  /* ============================================================
     DreamLayer Brain — Mac OS 8.1 "Platinum" control panel.
     Matches dreamlayer.app: Chicago chrome, hard bevels, paper
     surfaces, pinstriped card headers, selection-blue navigation.
     Fonts self-hosted via /panel-assets/ — still zero external
     requests. Every selector below predates the reskin; the JS
     contract (ids, classes, var() tokens) is unchanged.
     ============================================================ */
  @font-face{font-family:"ChicagoFLF";src:url("/panel-assets/ChicagoFLF.woff2") format("woff2");font-display:swap}
  @font-face{font-family:"Space Grotesk";src:url("/panel-assets/SpaceGrotesk-latin.woff2") format("woff2");font-weight:300 700;font-display:swap}
  :root{
    /* same token NAMES the JS references; Platinum values (AA on paper) */
    --bg:#0F1A1D; --surf:#FFFFFF; --surf2:#E9ECEB; --line:#C2C8C6;
    --memory:#0B6B52; --attention:#B3402E; --success:#1F8A3D; --error:#C0392B;
    --amber:#8A5A00; --text:#141414; --muted:#4A5054; --ghost:#8A9296;
    --r-sm:2px; --r-lg:2px; --r-pill:4px; --ease:cubic-bezier(.16,1,.3,1);
    --paper:#EFEFEF; --plat:#DDDDDD; --plat2:#CCCCCC; --frame:#000000; --hi:#333399;
    --chi:"ChicagoFLF","Charcoal","Geneva",system-ui,sans-serif;
    --sg:"Space Grotesk",ui-sans-serif,system-ui,-apple-system,"SF Pro Text",Segoe UI,Roboto,sans-serif;
    --bev-out:inset 1px 1px 0 #FFFFFF, inset -1px -1px 0 #8E8E8E;
    --bev-in:inset 1px 1px 0 #8E8E8E, inset -1px -1px 0 #FFFFFF;
    --stripes:repeating-linear-gradient(180deg,#FFFFFF 0 1px,#DDDDDD 1px 2px,#ACACAC 2px 3px);
  }
  *{box-sizing:border-box}
  html,body{margin:0}
  body{
    /* the desktop, glimpsed at the edges of the app shell */
    background-color:var(--bg);
    background-image:
      radial-gradient(rgba(44,199,154,.10) 1px, transparent 1.2px),
      conic-gradient(from 90deg at 1px 1px, rgba(255,255,255,.05) 90deg, transparent 0);
    background-size:96px 96px, 4px 4px;
    color:var(--text); -webkit-font-smoothing:antialiased;
    font:15px/1.55 var(--sg);
    min-height:100vh;
  }
  .wrap{max-width:760px;margin:0 auto;padding:0 20px 96px}
  .bar{display:flex;align-items:center;gap:12px;padding:14px 0 10px;margin-bottom:6px}
  .brand{font-weight:600;letter-spacing:-.01em;font-size:1.05rem}
  .brand b{color:var(--memory)}
  .live{display:flex;align-items:center;gap:8px;margin-left:auto;color:var(--muted);
        font:12.5px var(--chi);background:var(--surf);border:1px solid var(--frame);
        box-shadow:var(--bev-out),1px 1px 0 rgba(0,0,0,.18);padding:4px 11px}
  .live .dot{width:8px;height:8px;border-radius:50%;background:var(--success);
        animation:pulse 2.4s var(--ease) infinite}
  @keyframes pulse{0%{box-shadow:0 0 0 0 rgba(31,138,61,.5)}70%{box-shadow:0 0 0 7px rgba(31,138,61,0)}100%{box-shadow:0 0 0 0 rgba(31,138,61,0)}}
  h1{font-weight:700;letter-spacing:-.025em;font-size:2.1rem;margin:6px 0 2px;font-family:var(--sg)}
  .sub{color:var(--muted);margin:0 0 20px}
  /* every card is a little Platinum window: white body, black frame,
     hard offset shadow, and a pinstriped strip across the top */
  main>section{background:var(--surf);border:1px solid var(--frame);border-radius:0;
        box-shadow:var(--bev-out),3px 3px 0 rgba(0,0,0,.22);
        padding:30px 20px 20px;margin-bottom:18px;position:relative;
        opacity:0;transform:translateY(14px);animation:rise .5s var(--ease) forwards}
  main>section::before{content:"";position:absolute;top:6px;left:6px;right:6px;height:11px;
        background:var(--stripes);pointer-events:none}
  main>section:nth-child(1){animation-delay:.02s} main>section:nth-child(2){animation-delay:.06s}
  main>section:nth-child(3){animation-delay:.10s} main>section:nth-child(4){animation-delay:.14s}
  main>section:nth-child(5){animation-delay:.18s} main>section:nth-child(6){animation-delay:.22s}
  @keyframes rise{to{opacity:1;transform:none}}
  h2{font-weight:700;font-size:1.12rem;margin:0 0 4px;letter-spacing:-.01em;font-family:var(--sg)}
  .eyebrow{font:11.5px var(--chi);letter-spacing:.06em;
           text-transform:uppercase;color:var(--memory);margin-bottom:8px;
           border-bottom:1px solid rgba(11,107,82,.35);display:inline-block;padding-bottom:2px}
  .lead{color:var(--muted);font-size:.92rem;margin:0 0 16px}
  .row{display:flex;gap:10px;align-items:center;flex-wrap:wrap}
  input[type=text]{flex:1;min-width:180px}
  input,select,textarea{background:#FFFFFF;border:1px solid var(--frame);color:var(--text);
        border-radius:0;box-shadow:var(--bev-in);padding:10px 12px;font:inherit;font-family:var(--sg)}
  input:focus,select:focus,textarea:focus{outline:2px solid var(--memory);outline-offset:-1px}
  input::placeholder,textarea::placeholder{color:var(--ghost)}
  button{background:linear-gradient(180deg,#49E8BC,#17AE85);color:#00251C;border:1px solid var(--frame);
         border-radius:7px;box-shadow:var(--bev-out),2px 2px 0 rgba(0,0,0,.2);
         padding:9px 16px;font:14px var(--chi);cursor:pointer}
  button:hover{filter:brightness(1.04)}
  button:active{background:#0B6B52;color:#fff;box-shadow:var(--bev-in);transform:none;filter:none}
  button.ghost{background:linear-gradient(180deg,#F6F6F6,#D2D2D2);color:#141414}
  button.ghost:hover{color:#000;filter:brightness(1.02)}
  button.ghost:active{background:#6E6E6E;color:#fff}
  button.sm{padding:6px 12px;font-size:12.5px}
  button.danger{color:var(--error);background:linear-gradient(180deg,#F6F6F6,#D2D2D2)}
  pre{overflow-x:auto}

  /* system status */
  .sys{display:flex;align-items:center;gap:12px;padding:12px 0;border-top:1px solid var(--line)}
  .sys:first-child{border-top:0}
  .sdot{width:9px;height:9px;border-radius:50%;flex:none;background:var(--ghost);
        box-shadow:inset 0 0 0 1px rgba(0,0,0,.35)}
  .sdot.ok{background:var(--success)}
  .sdot.warn{background:#D89614}
  .sdot.off{background:var(--ghost)}
  .sname{font-size:.98rem;min-width:96px}
  .sstate{color:var(--muted);font-size:.88rem;margin-left:auto;text-align:right}
  .sstate b{color:var(--text);font-weight:600}

  /* connections + switches — the toggle is a Platinum slide switch */
  .conn{display:flex;gap:18px;align-items:center;justify-content:space-between;padding:16px 0;border-top:1px solid var(--line)}
  .conn:first-of-type{border-top:0;padding-top:4px}
  .conn-t{font-size:1rem;font-weight:600} .conn-s{font-size:.85rem;color:var(--muted);margin-top:3px;max-width:46ch}
  .sw{position:relative;display:inline-block;width:46px;height:24px;flex:none;cursor:pointer}
  .sw input{opacity:0;width:0;height:0;position:absolute}
  .sw .track{position:absolute;inset:0;background:#FFFFFF;border:1px solid var(--frame);border-radius:3px;
        box-shadow:var(--bev-in);transition:background .15s}
  .sw .track:before{content:"";position:absolute;left:2px;top:2px;width:19px;height:18px;border-radius:2px;
        background:linear-gradient(135deg,#F2F2F6,#B9B9D6);border:1px solid var(--frame);
        box-shadow:inset 1px 1px 0 rgba(255,255,255,.8);transition:transform .15s var(--ease)}
  .sw input:checked + .track{background:rgba(11,107,82,.18)}
  .sw input:checked + .track:before{transform:translateX(20px);background:linear-gradient(135deg,#49E8BC,#17AE85)}
  .sw input:checked + .track.red{background:rgba(179,64,46,.16)}
  .sw input:checked + .track.red:before{background:linear-gradient(135deg,#E8907E,#B3402E)}
  .sw input:disabled + .track{opacity:.4;cursor:not-allowed}

  /* folders */
  ul{list-style:none;margin:6px 0 0;padding:0}
  li.folder{display:flex;justify-content:space-between;align-items:center;gap:12px;padding:12px 0;border-top:1px solid var(--line)}
  li.folder:first-child{border-top:0}
  .path{font:13px ui-monospace,Menlo,monospace;color:var(--muted);word-break:break-all}
  .path:before{content:"";display:inline-block;width:7px;height:7px;background:var(--memory);margin-right:9px;vertical-align:middle}
  .drop{margin-top:14px;border:1.5px dashed #9AA19E;padding:24px;text-align:center;color:var(--ghost);transition:.15s}
  .drop.hot{border-color:var(--memory);color:var(--memory);background:rgba(11,107,82,.05)}
  .empty{color:var(--ghost);font-size:.9rem;padding:14px 0;text-align:center}

  /* segmented (Platinum tabs) + model status */
  .seg{display:inline-flex;background:var(--plat);border:1px solid var(--frame);border-radius:0;
       box-shadow:var(--bev-out);padding:2px;gap:2px}
  .seg button{background:transparent;color:var(--muted);border:1px solid transparent;border-radius:0;
       box-shadow:none;padding:7px 15px;font:13px var(--chi)}
  .seg button:active{background:#8E8E8E;color:#fff}
  .seg button.on{background:#FFFFFF;color:var(--text);border-color:var(--frame);box-shadow:var(--bev-out)}
  .mstat{margin-top:16px;background:#F7F8F7;border:1px solid var(--frame);box-shadow:var(--bev-out);
       border-radius:0;padding:16px}
  .mstat .head{display:flex;align-items:center;gap:10px;font-size:1rem;margin-bottom:4px;font-weight:600}
  .mrow{display:flex;align-items:center;gap:10px;padding:8px 0;border-top:1px solid var(--line);font-size:.9rem}
  .mrow:first-of-type{border-top:0}
  .mrow .lbl{min-width:64px;color:var(--muted)} .mrow .nm{font:12px ui-monospace,Menlo,monospace;color:var(--text)}
  .mrow .st{margin-left:auto;font-size:.82rem}
  .ok-t{color:var(--success)} .warn-t{color:var(--amber)} .off-t{color:var(--ghost)}
  .steps{margin:10px 0 0;padding:0;counter-reset:s}
  .steps li{list-style:none;display:flex;gap:10px;padding:6px 0;color:var(--muted);font-size:.9rem;border:0}
  .steps li:before{counter-increment:s;content:counter(s);flex:none;width:20px;height:20px;
        background:var(--plat);border:1px solid var(--frame);box-shadow:var(--bev-out);
        color:var(--text);font:11px/18px var(--chi);text-align:center}
  code{font:12px ui-monospace,Menlo,monospace;background:#FFFFFF;border:1px solid var(--frame);
       box-shadow:var(--bev-in);border-radius:0;padding:2px 7px;color:var(--memory);user-select:all}

  /* answer + pair */
  .ans{margin-top:14px;padding:14px 16px;background:#FFFFFF;border:1px solid var(--frame);
       border-left:3px solid var(--memory);box-shadow:var(--bev-out),2px 2px 0 rgba(0,0,0,.15);
       border-radius:0;animation:rise .35s var(--ease) both}
  .ans .src{display:inline-flex;gap:8px;align-items:center;font:11px ui-monospace,Menlo,monospace;color:var(--ghost);margin-top:8px}
  .tier{background:rgba(11,107,82,.12);color:var(--memory);border:1px solid rgba(11,107,82,.4);
       border-radius:0;padding:2px 8px;text-transform:uppercase;letter-spacing:.08em;font-family:var(--chi)}
  .shimmer{height:14px;margin:6px 0;background:linear-gradient(90deg,#E7EAE9,#F6F8F7,#E7EAE9);
       background-size:200% 100%;animation:sh 1.1s linear infinite}
  .shimmer.s2{width:70%}
  @keyframes sh{0%{background-position:200% 0}100%{background-position:-200% 0}}
  .paircode{margin-top:14px;background:#FFFFFF;border:1px solid var(--frame);box-shadow:var(--bev-out);
       border-radius:0;padding:14px;animation:rise .35s var(--ease) both}
  .paircode .code{font:13px/1.5 ui-monospace,Menlo,monospace;color:var(--memory);word-break:break-all;user-select:all}
  .paircode .foot{display:flex;justify-content:space-between;align-items:center;gap:12px;margin-top:12px;flex-wrap:wrap}
  .paircode .url{font:12px ui-monospace,Menlo,monospace;color:var(--ghost)}
  .qrbox{background:#fff;border:1px solid var(--frame);box-shadow:var(--bev-out),2px 2px 0 rgba(0,0,0,.18);
       border-radius:0;padding:12px;width:max-content;max-width:100%;margin:0 auto 4px}
  .qrbox svg{display:block;width:200px;height:200px;max-width:100%}

  /* activity feed */
  .feed li{display:flex;justify-content:space-between;align-items:flex-start;gap:12px;padding:12px 0;border-top:1px solid var(--line)}
  .feed li:first-child{border-top:0}
  .feed .q{color:var(--text)} .feed .a{color:var(--muted);font-size:.9rem;margin-top:2px}
  .tag{font:10px var(--chi);text-transform:uppercase;letter-spacing:.08em;flex:none;padding-top:3px;color:var(--memory)}
  .tag.folder{color:var(--amber)} .tag.upload{color:var(--success)} .tag.cloud{color:var(--memory)}
  .tag.privacy{color:var(--attention)} .tag.pair{color:#33418F} .tag.model,.tag.config{color:var(--muted)}

  /* modal (folder browser) — a real Platinum dialog */
  .overlay{position:fixed;inset:0;background:rgba(8,12,14,.35);z-index:60;
        display:none;align-items:center;justify-content:center;padding:20px}
  .overlay.show{display:flex}
  .modal{width:100%;max-width:560px;background:var(--plat);border:2px solid var(--frame);border-radius:0;
        box-shadow:var(--bev-out),inset 2px 2px 0 #EFEFEF,6px 6px 0 rgba(0,0,0,.35);
        padding:20px;max-height:80vh;display:flex;flex-direction:column;animation:rise .3s var(--ease) both}
  .modal h3{margin:0 0 4px;font:16px var(--chi);font-weight:400}
  .modal .cur{font:12px ui-monospace,Menlo,monospace;color:var(--muted);word-break:break-all;margin-bottom:12px}
  .dirlist{overflow-y:auto;background:#FFFFFF;border:1px solid var(--frame);box-shadow:var(--bev-in);
        border-radius:0;margin-bottom:14px}
  .diritem{display:flex;align-items:center;gap:10px;padding:10px 14px;cursor:pointer;
        border-bottom:1px solid #E2E5E4;color:var(--text);font-family:var(--chi);font-size:14px}
  .diritem:last-child{border-bottom:0}
  .diritem:hover{background:var(--hi);color:#fff}
  .diritem:before{content:"";width:8px;height:8px;background:var(--memory)}
  .diritem:hover:before{background:#fff}
  .diritem.up:before{background:var(--ghost);border-radius:50%}
  .modal .mfoot{display:flex;gap:10px;justify-content:flex-end}
  /* plugin detail */
  .modal.pd{max-width:600px;padding:0;overflow:hidden}
  .pd .shot{width:100%;display:block;border-bottom:1px solid var(--frame);background:#0E1416}
  .pd .pdbody{padding:22px;overflow-y:auto;background:var(--surf)}
  .pd h3{font-size:1.3rem} .pd .pdby{font:12px ui-monospace,Menlo,monospace;color:var(--muted);margin-bottom:14px}
  .pd .pdlong p{color:var(--muted);margin:0 0 11px;line-height:1.6}
  .pd .pdsec{font:11px var(--chi);text-transform:uppercase;letter-spacing:.08em;color:var(--memory);margin:18px 0 7px}
  .pd .permr{display:flex;gap:12px;align-items:baseline;margin:6px 0;font-size:.92rem;color:var(--text)}
  .pd .permr b{color:var(--attention);font:11px var(--chi);letter-spacing:.04em;min-width:66px;text-transform:uppercase;flex:none}
  .pd .pill{cursor:pointer}

  /* toast — Balloon Help */
  #toast{position:fixed;left:50%;bottom:30px;transform:translate(-50%,20px);background:#FFFFE8;
        border:1px solid var(--frame);border-radius:10px 10px 10px 2px;padding:10px 18px;color:#222;
        font-size:.9rem;opacity:0;pointer-events:none;transition:opacity .25s var(--ease),transform .25s var(--ease);
        z-index:80;box-shadow:2px 2px 0 rgba(0,0,0,.35)}
  #toast.show{opacity:1;transform:translate(-50%,0)}
  #toast .dot{display:inline-block;width:7px;height:7px;border-radius:50%;background:var(--success);margin-right:9px;vertical-align:middle}
  a{color:var(--memory)}
  /* the cinematic dusk layer is retired — the Platinum desktop is the scene.
     The divs remain in the markup (inert), so they are simply hidden. */
  .cine-bg,.grain,.vignette,.head-cine{display:none}
  .wrap{position:relative;z-index:2}
  /* feature explainers — Platinum chips that open an illustrated dialog */
  .xgrid{display:grid;grid-template-columns:repeat(auto-fill,minmax(150px,1fr));gap:10px;margin-top:6px}
  .xchip{display:flex;align-items:center;gap:9px;text-align:left;cursor:pointer;
    background:linear-gradient(180deg,#F6F6F6,#DEDEDE);border:1px solid var(--frame);border-radius:0;
    box-shadow:var(--bev-out),2px 2px 0 rgba(0,0,0,.16);
    padding:10px 13px;color:var(--text);font:13px var(--chi);transition:transform .12s var(--ease)}
  .xchip:hover{filter:brightness(1.03)}
  .xchip:active{background:#8E8E8E;color:#fff;box-shadow:var(--bev-in)}
  .xchip .xdot{width:7px;height:7px;background:var(--memory);flex:none}
  .xmodal{position:fixed;inset:0;z-index:50;display:none;align-items:center;justify-content:center;
    padding:24px;background:rgba(8,12,14,.35)}
  .xmodal.on{display:flex}
  .xcard{max-width:440px;width:100%;background:var(--plat);
    border:2px solid var(--frame);border-radius:0;overflow:hidden;
    box-shadow:var(--bev-out),inset 2px 2px 0 #EFEFEF,6px 6px 0 rgba(0,0,0,.35)}
  .xcard img{display:block;width:100%;background:#0E1416;border-bottom:1px solid var(--frame)}
  .xcard .xbody{padding:18px 20px;background:var(--surf)}
  .xcard .xbody h3{margin:2px 0 8px;font-size:1.3rem;letter-spacing:-.02em}
  .xcard .xbody p{margin:0;color:var(--muted);line-height:1.6}
  .xcard .xclose{margin:14px 20px 20px}
  /* ================= native app chrome ==================================
     The window never scrolls as a page: a fixed Platinum sidebar + an
     independently-scrolling paper content pane, with lavender Platinum
     scrollbar thumbs. Feels like a real (classic) Mac app. */
  html,body{height:100%}
  body{overflow:hidden;overscroll-behavior:none;-webkit-user-select:none;user-select:none;
    cursor:default}
  .wrap{max-width:none;width:100%;height:100vh;display:flex;gap:0;padding:0;align-items:stretch;z-index:2}
  .side{width:224px;flex:none;height:100vh;overflow-y:auto;display:flex;flex-direction:column;gap:1px;
    padding:14px 10px 16px;border-right:1px solid var(--frame);border-radius:0;
    background:linear-gradient(180deg,#E4E4E4,#D2D2D2);
    box-shadow:inset -1px 0 0 #9A9A9A, inset 1px 1px 0 #F4F4F4}
  .side .brand2{display:flex;align-items:center;gap:10px;padding:6px 10px 14px;
    font:16px var(--chi);font-weight:400;letter-spacing:.01em;color:#111}
  .side .brand2 .rd{position:relative;width:16px;height:16px;flex:none;border-radius:50%;
    border:2.5px solid var(--memory)}
  .side .brand2 .rd::after{content:"";position:absolute;inset:3.5px;border-radius:50%;background:var(--memory)}
  .side .navlabel{font:10.5px var(--chi);letter-spacing:.1em;text-transform:uppercase;
    color:#6E7671;padding:10px 11px 5px}
  .side button{display:flex;align-items:center;gap:11px;width:100%;text-align:left;background:none;border:0;
    color:#26292B;font:14px var(--chi);padding:7px 11px;border-radius:0;box-shadow:none;
    cursor:default;outline:none}
  .side button svg{width:16px;height:16px;flex:none;opacity:.9}
  .side button:hover{background:rgba(0,0,0,.07);color:#000;filter:none}
  .side button:active{background:var(--hi);color:#fff;box-shadow:none}
  .side button.on{background:var(--hi);color:#fff}
  .side button.on svg{opacity:1;color:#fff}
  .content{flex:1;min-width:0;height:100vh;overflow-y:auto;position:relative;padding:24px 40px 64px;
    background:var(--paper);box-shadow:inset 1px 1px 0 #9A9A9A}
  .content .bar{justify-content:flex-end;margin:0;padding:0;position:static;background:none}
  .content .bar .brand{display:none}     /* brand lives in the sidebar */
  h1#pageTitle{font-size:1.9rem;margin:2px 0 2px;letter-spacing:-.03em}
  .content>main{max-width:760px}
  /* Platinum scrollbars: dithered track, lavender thumb */
  .content::-webkit-scrollbar,.side::-webkit-scrollbar{width:15px;height:15px}
  .content::-webkit-scrollbar-track{background:#C6C6C6;border-left:1px solid var(--frame)}
  .content::-webkit-scrollbar-thumb{background:linear-gradient(135deg,#B8B8E8,#8989CE);
    border:1px solid var(--frame);box-shadow:inset 1px 1px 0 rgba(255,255,255,.75)}
  .side::-webkit-scrollbar-thumb{background:transparent}
  .side::-webkit-scrollbar-track{background:transparent}
  /* selection + normal cursor only where it belongs */
  input,textarea,pre,.line,.conn-s,.lead,p,#briefout,#recallout{-webkit-user-select:text;user-select:text}
  input,textarea{cursor:text}
  main>section{display:none}                       /* only the active view shows */
  main>section.pon{display:block;opacity:1;transform:none;
    animation:pagein .3s var(--ease) both}
  @keyframes pagein{from{opacity:0;transform:translateY(6px)}to{opacity:1;transform:none}}
  /* Juno — the desk accessory, exactly as she appears on dreamlayer.app:
     a tiny Platinum window in the corner, pixel sprite inside, watching. */
  .juno-hero{position:fixed;right:16px;bottom:16px;width:150px;z-index:15;pointer-events:none;
    background:var(--plat);border:1px solid var(--frame);
    box-shadow:var(--bev-out),3px 3px 0 rgba(0,0,0,.3);
    padding:17px 8px 8px;text-align:center}
  .juno-hero::after{content:"Juno";position:absolute;top:2px;left:50%;transform:translateX(-50%);
    font:11px var(--chi);color:#1A1A1A;background:var(--plat);padding:0 7px}
  .juno-hero::before{content:"";position:absolute;top:6px;left:6px;right:6px;height:8px;
    background:var(--stripes)}
  .juno-hero .jscreen{background:#0E1416;padding:9px 6px 7px}
  .juno-hero img{width:92px;height:auto;image-rendering:pixelated;
    filter:drop-shadow(0 0 12px rgba(44,199,154,.28));
    animation:jhFloat 10s ease-in-out infinite;will-change:transform}
  .juno-hero .jcap{display:block;margin-top:5px;font:10.5px var(--chi);color:#A8B8C0;line-height:1.4}
  .juno-hero[data-state="thinking"] img{filter:drop-shadow(0 0 16px rgba(44,199,154,.5))}
  .juno-hero[data-state="success"] img{filter:drop-shadow(0 0 16px rgba(86,211,100,.5))}
  @keyframes jhFloat{0%,100%{transform:translateY(0)}50%{transform:translateY(-4px)}}
  @media(max-width:760px){.juno-hero{display:none}}
  @media(prefers-reduced-motion:reduce){
    .juno-hero img{animation:none}
    main>section{animation-duration:.01s}
    .live .dot{animation:none}
  }
  @media(max-width:760px){body{overflow:auto}
    .wrap{flex-direction:column;height:auto}
    .side{width:auto;height:auto;flex-direction:row;flex-wrap:wrap;gap:4px;border-right:0;
      border-bottom:1px solid var(--frame);position:sticky;top:0;z-index:5}
    .side .brand2,.side .navlabel{width:100%}
    .side button{width:auto}
    .content{height:auto;padding:22px 20px 60px}}
</style></head><body>
<div class="cine-bg" aria-hidden="true"></div>
<div class="grain" aria-hidden="true"></div>
<div class="vignette" aria-hidden="true"></div>
<div class="wrap">
  <nav class="side" id="side"></nav>
  <div class="content">
  <div class="head-cine" aria-hidden="true"></div>
  <div class="bar"><span class="brand"><b>Dream</b>Layer</span>
    <span class="live"><span class="dot"></span><span id="livetext">Brain online</span></span></div>
  <h1 id="pageTitle">Home</h1>
  <p class="sub" id="pageSub">This Mac mini is the brain — your files, your memory, your reach.</p>

  <main>
  <section>
    <div class="eyebrow">System</div><h2>What's connected</h2>
    <div id="packNudge" style="display:none"></div>
    <div id="sysrows"></div>
  </section>

  <section>
    <div class="eyebrow">Learn</div><h2>How it works</h2>
    <p class="lead">The glasses show cards; this Brain makes them. Tap a feature to see what it does
      and the card it draws.</p>
    <div class="xgrid" id="xgrid"></div>
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
    <p class="lead">Everyone you know — names you've introduced here, your synced Contacts, and people you met on your Halo, complete with their relationship, notes, and any favors owed. The glasses greet them with what you know.</p>
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
    <p class="lead">Pick a provider — OpenAI, Anthropic, Gemini, or OpenRouter — or run a model
      locally with <b>Ollama</b> (free, no key, nothing leaves your Mac). Custom points at any
      OpenAI-compatible endpoint. Any key is stored only on this Mac mini and never shown again.</p>
    <div class="row" style="margin-bottom:12px">
      <select id="cprov" onchange="provPreset(true)" style="max-width:220px">
        <option value="openai">OpenAI</option>
        <option value="anthropic">Anthropic</option>
        <option value="gemini">Google Gemini</option>
        <option value="openrouter">OpenRouter</option>
        <option value="ollama">Ollama · local (free)</option>
        <option value="dreamlayer">DreamLayer Cloud</option>
        <option value="custom">Custom (OpenAI-compatible)</option>
      </select></div>
    <div class="row">
      <input type="text" id="cbase" placeholder="https://api.openai.com" style="max-width:230px">
      <input type="password" id="ckey" placeholder="API key" style="max-width:200px">
      <input type="text" id="cmodel" placeholder="gpt-4o-mini" style="max-width:150px"></div>
    <div class="row" style="margin-top:12px;justify-content:space-between">
      <button class="sm ghost" onclick="testCloud()">Test connection</button>
      <button class="sm" onclick="saveCloud()">Save cloud</button></div>
    <div id="cloudStatus"></div>
    <div style="margin-top:16px;border-top:1px solid var(--line);padding-top:12px">
      <div class="conn-t">What the cloud can see</div>
      <div class="conn-s" id="cloudSees">…</div>
      <ul id="cloudCant" style="margin:8px 0 0;padding-left:18px;font-size:.85rem;color:var(--muted)"></ul>
    </div>
  </section>

  <section>
    <div class="eyebrow">Plan</div><h2>Free · local &amp; open</h2>
    <p class="lead">DreamLayer runs entirely on your own hardware, on code you can read. Every feature
      here is free — bring your own AI key, or run a model locally with Ollama and pay nothing at all.</p>
    <div class="conn">
      <div style="flex:1"><div class="conn-t">DreamLayer&nbsp;Cloud <span id="planBadge" style="color:var(--amber)">· coming soon</span></div>
        <div class="conn-s">An optional hosted tier — everything below is <i>added</i>; the local app
          never loses a feature and always stays free and open.</div></div>
      <button class="ghost" id="notifyBtn" onclick="joinWaitlist()">Notify me</button></div>
    <div id="planRows"></div>
  </section>

  <section>
    <div class="eyebrow">Your data</div><h2>Your memory is a file</h2>
    <p class="lead">Everything the Juno remembers is one local SQLite file — browse it read-only, or take a copy. No cloud, no command line.</p>
    <div class="row" style="margin-top:6px"><span id="memfile" class="conn-s" style="margin:0">…</span></div>
    <div class="row" style="margin-top:14px">
      <button onclick="browseMemory()">Browse (read-only)</button>
      <button class="ghost" onclick="exportMemory()">Export a copy…</button>
    </div>
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
    <p class="lead">Keyword search works with no model at all. Add Ollama on this Mac mini for written answers and vision — or plug in your own agent (Hermes, OpenClaw, LM Studio, anything OpenAI-compatible) as the brain.</p>
    <div class="seg" id="modelSeg">
      <button data-m="keyword" onclick="pickModel('keyword')">Keyword</button>
      <button data-m="ollama" onclick="pickModel('ollama')">Ollama</button>
      <button data-m="api" onclick="pickModel('api')">Your API</button></div>
    <div class="fold" id="ollamaFields" style="max-height:0;overflow:hidden;opacity:0;transition:max-height .3s var(--ease),opacity .25s,margin .3s">
      <div class="row" style="margin-top:12px">
        <input type="text" id="ourl" placeholder="http://127.0.0.1:11434" style="max-width:230px">
        <input type="text" id="ochat" placeholder="chat · llama3.2" style="max-width:190px">
        <input type="text" id="ovis" placeholder="vision model" style="max-width:170px"></div>
    </div>
    <div class="fold" id="apiFields" style="max-height:0;overflow:hidden;opacity:0;transition:max-height .5s var(--ease),opacity .3s,margin .3s">
      <div class="conn" style="margin-top:12px"><div style="flex:1">
        <div class="conn-t">Agents running on this Mac</div>
        <div class="conn-s">We look for a local agent already running (Ollama, LM Studio, vLLM, llama.cpp, Jan) and connect it in one tap — nothing to type, nothing leaves your device.</div></div>
        <button class="sm ghost" onclick="scanAgents()">Scan</button></div>
      <div id="apiFound"></div>
      <div class="conn-s" style="margin:16px 0 8px;border-top:1px solid var(--line);padding-top:14px">
        …or set one up by hand — a local endpoint, or a cloud provider (paste your key):</div>
      <div class="row">
        <select id="aprov" onchange="apiPreset(true)" style="max-width:220px">
          <option value="custom">Custom (OpenAI-compatible)</option>
          <option value="openai">OpenAI</option>
          <option value="anthropic">Anthropic</option>
          <option value="gemini">Google Gemini</option>
          <option value="openrouter">OpenRouter</option>
          <option value="ollama">Ollama · local</option>
        </select>
        <input type="text" id="abase" placeholder="http://localhost:1234/v1" oninput="renderApiWarn()" style="max-width:230px">
        <input type="password" id="akey" placeholder="API key (blank if local)" style="max-width:180px">
        <input type="text" id="amodel" placeholder="model name" style="max-width:150px"></div>
      <div class="row" style="margin-top:12px">
        <button class="sm ghost" onclick="testApi()">Test connection</button>
        <button class="sm" onclick="saveApi()">Use this brain</button></div>
      <div id="apiStatus"></div>
      <div id="apiWarn"></div>
    </div>
    <div id="modelStatus"></div>
    <div class="row" style="margin-top:16px;justify-content:flex-end">
      <button class="sm" onclick="saveModel()">Save</button></div>
    <div class="conn" style="margin-top:14px">
      <div><div class="conn-t">Read email &amp; iMessage</div>
        <div class="conn-s">Let the Brain read Mail and Messages so a glance can catch a reply you owe.
          Nothing is sent; it stays on this Mac. Saves the moment you flip it.</div></div>
      <label class="sw"><input type="checkbox" id="email" onchange="saveEmail()"><span class="track"></span></label></div>
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
    <div class="eyebrow">Extend</div><h2>Plugins</h2>
    <p class="lead">Community plugins your Brain runs. Every one is validated —
      integrity, a capability scan, and a smoke test — before it's installed.
      <a href="https://dreamlayer.app/plugins.html" target="_blank">Browse the store ↗</a>
      &nbsp;·&nbsp; No code? <a href="/dreamlayer/build">Build a lens →</a> (deploys straight to this Brain)</p>
    <div class="conn-s" style="margin:0 0 8px">This Brain can grant:
      <span id="plugCaps">…</span></div>
    <ul id="plugins" class="feed"></ul>
    <div class="conn" style="border-bottom:0"><div style="flex:1"><div class="conn-t">Sideload a package</div>
      <div class="conn-s">Paste a plugin package (JSON: manifest + source) to install it directly. It passes the same gate.</div>
      <textarea id="plugPkg" placeholder='{"manifest": {...}, "source": "..."}' style="width:100%;min-height:64px;margin-top:6px;font-family:monospace;font-size:12px"></textarea>
      <div class="row" style="margin-top:6px"><button class="sm" onclick="installPlugin()">Install package</button>
        <span id="plugStatus" class="conn-s" style="margin:0"></span></div></div></div>
  </section>

  <section>
    <div class="eyebrow">System</div><h2>Capabilities</h2>
    <p class="lead">The Brain's optional powers — each runs a graceful fallback until its
      library is present, so nothing here is ever required. Installed ones switch off with one
      click (no uninstall); missing ones show the exact install.
      <a href="https://github.com/LetsGetToWorkBro/dreamlayer/blob/main/docs/DEPLOYMENT.md" target="_blank">How switching on works ↗</a></p>
    <div class="conn-s" id="capsum" style="margin:0 0 10px">…</div>
    <div class="xgrid" id="packgrid" style="margin:0 0 8px"></div>
    <div id="caprows"></div>
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
</div>

<div class="xmodal" id="xmodal" onclick="if(event.target===this)closeX()">
  <div class="xcard">
    <img id="ximg" alt="" src="">
    <div class="xbody"><div class="eyebrow" id="xkick"></div><h3 id="xtitle"></h3><p id="xtext"></p></div>
    <button class="ghost xclose" onclick="closeX()">Done</button>
  </div>
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
<div class="overlay" id="pdetail">
  <div class="modal pd"><div id="pdinner"></div></div>
</div>
<div id="toast"></div>
<div class="juno-hero" data-juno data-juno-state="idle" aria-hidden="true">
  <div class="jscreen"><img src="/panel-assets/juno_da.webp" alt="" width="96" height="96">
  <span class="jcap">the brain is listening.</span></div>
</div>
<script>
const TOKEN="__TOKEN__";
const H={"Content-Type":"application/json"}; if(TOKEN)H["X-DreamLayer-Token"]=TOKEN;
const api=(p,o={})=>fetch(p,Object.assign({headers:H},o)).then(r=>r.json());
// quotes included: esc() output also lands inside single-quoted onclick
// attributes (Remove buttons), where a stray ' would open an attribute break
const esc=s=>(s||"").replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
const $=id=>document.getElementById(id);
let modelSel="keyword", ollamaOK=null, browsePath="";

/* feature explainers — each pairs a real HUD card image with what it does */
const EXPLAINERS=[
  {t:"Juno",img:"juno_reply.png",b:"Ask anything out loud. Juno answers on the glass in a line or two — drawn from your own memory first, the web only when it must."},
  {t:"Morning brief",img:"morning_brief.png",b:"Each morning, a short synthesis of what's new and what's on you: messages, mail, calendar, and anything you're tracking."},
  {t:"Truth gauge",img:"truth_gauge.png",b:"When a claim sounds off, a quiet gauge shows how well it holds up — sourced and checked, never guessed."},
  {t:"Face recall",img:"person_dossier.png",b:"Glance at someone you've met and their name, how you know them, and your last note surface — privately, only to you."},
  {t:"Object recall",img:"object_recall.png",b:"“Where are my keys?” The card shows where you last saw the thing, as a place you can walk back to."},
  {t:"Proactive memory",img:"proactive_memory.png",b:"The layer surfaces what you'd want before you ask — the doc due Friday, the promise you made, the name you'll need."},
  {t:"Live caption",img:"live_caption.png",b:"Speech becomes text on the glass in real time — for a loud room, a fast talker, or a language you're still learning."},
  {t:"Privacy veil",img:"privacy_veil.png",b:"Drop the veil and the whole layer goes dark — nothing captured, nothing shown — until you lift it. Yours to command."},
];
function renderExplainers(){const g=$("xgrid");if(!g)return;
  g.innerHTML=EXPLAINERS.map((x,i)=>`<button class="xchip" onclick="openX(${i})"><span class="xdot"></span>${esc(x.t)}</button>`).join("");}
function openX(i){const x=EXPLAINERS[i];$("ximg").src="/panel-assets/"+x.img;$("xkick").textContent="How it works";
  $("xtitle").textContent=x.t;$("xtext").textContent=x.b;$("xmodal").classList.add("on");}
function closeX(){$("xmodal").classList.remove("on");}
document.addEventListener("keydown",e=>{if(e.key==="Escape")closeX();});

/* sidebar navigation — group the sections into app-style views. Each section
   is matched to a page by its heading, so the layout needs no per-section markup. */
const PAGES=[
  {id:"home",label:"Home",sub:"This Mac mini is the brain — your files, your memory, your reach.",match:["What's connected","Free · local"]},
  {id:"day",label:"Your day",sub:"Your morning brief, agenda, reminders, and the people you meet.",match:["Morning brief","Agenda","Who you","Reminders"]},
  {id:"mind",label:"Intelligence",sub:"Choose your AI, point it at your files, and tune how it thinks.",match:["Wire the cloud","Folders it reads","Ask your stuff","Model"]},
  {id:"reach",label:"Connections",sub:"Pair your phone and glasses, and decide how far the Brain reaches.",match:["Reach","On your glasses"]},
  {id:"privacy",label:"Privacy",sub:"What's kept, what's shared, and the controls that keep it yours.",match:["Privacy controls"]},
  {id:"plugins",label:"Plugins",sub:"Extend the Brain — browse, install, and manage plugins.",match:["Plugins"]},
  {id:"caps",label:"Capabilities",sub:"Every optional power of the Brain — what's on, what's off, and how to switch more on.",match:["Capabilities"]},
  {id:"learn",label:"Learn",sub:"How each feature works, with the card it draws on the glass.",match:["How it works"]},
  {id:"advanced",label:"Advanced",sub:"Activity, health, schedules, and maintenance.",match:["Activity","Health"]},
];
let curPage="home";
function pageOf(sec){
  const h=(sec.querySelector(".eyebrow")?.textContent||"")+" "+(sec.querySelector("h2")?.textContent||"");
  for(const p of PAGES){if(p.match.some(m=>h.includes(m)))return p.id;}
  return "home";
}
const _sv='<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round">';
const ICONS={
  home:_sv+'<path d="M3 11l9-8 9 8"/><path d="M5 10v10h14V10"/></svg>',
  day:_sv+'<rect x="4" y="5" width="16" height="16" rx="2"/><path d="M4 10h16M8 3v4M16 3v4"/></svg>',
  mind:_sv+'<rect x="6" y="6" width="12" height="12" rx="2"/><path d="M9 2v3M15 2v3M9 19v3M15 19v3M2 9h3M2 15h3M19 9h3M19 15h3"/></svg>',
  reach:_sv+'<path d="M10 13a5 5 0 0 0 7 0l2-2a5 5 0 0 0-7-7l-1 1"/><path d="M14 11a5 5 0 0 0-7 0l-2 2a5 5 0 0 0 7 7l1-1"/></svg>',
  privacy:_sv+'<path d="M12 3l7 3v5c0 4-3 7-7 9-4-2-7-5-7-9V6z"/></svg>',
  plugins:_sv+'<rect x="3" y="3" width="8" height="8" rx="1.4"/><rect x="13" y="3" width="8" height="8" rx="1.4"/><rect x="3" y="13" width="8" height="8" rx="1.4"/><rect x="13" y="13" width="8" height="8" rx="1.4"/></svg>',
  caps:_sv+'<circle cx="8" cy="12" r="5"/><path d="M8 7h8a5 5 0 0 1 0 10H8"/></svg>',
  learn:_sv+'<path d="M4 5a2 2 0 0 1 2-2h12v16H6a2 2 0 0 0-2 2z"/><path d="M18 3v18"/></svg>',
  advanced:_sv+'<path d="M4 8h10M18 8h2M4 16h2M10 16h10"/><circle cx="16" cy="8" r="2.2"/><circle cx="8" cy="16" r="2.2"/></svg>',
};
function buildNav(){
  document.querySelectorAll("main>section").forEach(s=>{s.dataset.page=pageOf(s);});
  $("side").innerHTML='<div class="brand2"><span class="rd"></span>DreamLayer</div>'+
    '<div class="navlabel">Brain</div>'+
    PAGES.map(p=>`<button data-p="${p.id}" onclick="showPage('${p.id}')">${ICONS[p.id]||''}<span>${esc(p.label)}</span></button>`).join("");
  showPage(curPage);
}
function showPage(id){curPage=id;
  document.querySelectorAll("main>section").forEach(s=>s.classList.toggle("pon",s.dataset.page===id));
  document.querySelectorAll(".side button").forEach(b=>b.classList.toggle("on",b.dataset.p===id));
  const p=PAGES.find(x=>x.id===id);
  if(p){$("pageTitle").textContent=p.label; if(p.sub)$("pageSub").textContent=p.sub;}
  const c=document.querySelector(".content"); if(c)c.scrollTop=0;
}

/* --- optional capabilities: live report + one-click on/off ---------------
   States come from /dreamlayer/capabilities (dreamlayer/capabilities.py):
   active = real path runs · off = installed, switched off here · missing =
   fallback runs · unsupported = wrong platform · external = a service. */
const CAPDOT={active:"var(--success)",off:"var(--amber)",missing:"var(--ghost)",
              unsupported:"var(--ghost)",external:"var(--memory)"};
let CAPFROZEN=false;
function capRight(it){
  if(it.state==="active"||it.state==="off"){
    const off=it.state==="off";
    return `<button class="ghost sm" onclick="toggleCap('${esc(it.key)}',${off?"false":"true"})">${off?"Turn on":"Turn off"}</button>`;
  }
  if(it.state==="missing"){
    const cmd=it.extra?`pip install "dreamlayer[${it.extra}]"`:(it.note||"manual install");
    if(CAPFROZEN) return `<span class="sstate">not in this build — runs on a source install</span>`;
    return `<code style="font-size:11px">${esc(cmd)}</code> <button class="ghost sm" onclick="copyCap('${esc(cmd)}')">Copy</button>`;
  }
  if(it.state==="external") return `<span class="sstate">${esc(it.note||"external service")}</span>`;
  return `<span class="sstate">macOS only</span>`;
}
async function loadCaps(){let r;try{r=await api("/dreamlayer/capabilities");}catch(e){return;}
  if(!r||!r.items)return; LASTCAPS=r; CAPFROZEN=!!r.frozen; renderCaps(r); renderPacks(r.packs);
  if((r.packs||[]).some(p=>p.install&&p.install.state==="installing"))schedulePackPoll();}
function renderCaps(r){
  const s=r.summary||{}; const order=["active","off","missing","unsupported","external"];
  $("capsum").textContent=order.filter(k=>s[k]).map(k=>`${s[k]} ${k}`).join(" · ")
    +(r.frozen?"  ·  bundled app (fixed set)":"");
  let tier="",html="";
  r.items.forEach(it=>{
    if(it.tier!==tier){tier=it.tier;
      html+=`<div class="navlabel" style="padding:12px 0 4px">${esc(tier)}</div>`;}
    html+=`<div class="conn" style="padding:8px 0">
      <span style="width:8px;height:8px;border-radius:50%;flex:none;background:${CAPDOT[it.state]||"var(--ghost)"}"></span>
      <div style="flex:1;min-width:0"><div class="conn-t">${esc(it.key)}
        <span class="conn-s" style="display:inline;margin-left:6px">${esc(it.title)}</span>
        ${it.impact?`<span class="tag" style="margin-left:6px">impact ${it.impact}/5</span>`:""}</div>
        ${it.gain?`<div class="conn-s" style="margin-top:2px">${esc(it.gain)}</div>`:""}</div>
      <div class="row" style="gap:8px;flex:none">${capRight(it)}</div></div>`;
  });
  $("caprows").innerHTML=html;
}
/* --- packs: curated upgrades so single capabilities are never overlooked --- */
const PACKSTATE={installed:"installed",partial:"partially installed",available:""};
function packCard(p){
  const job=p.install||null;
  let cta;
  if(job&&job.state==="installing") cta=`<span class="sstate">installing… ${esc(job.detail||"")}</span>`;
  else if(job&&job.state==="done") cta=`<span class="sstate" style="color:var(--success)">${esc(job.detail)}</span>`;
  else if(job&&job.state==="failed") cta=`<span class="sstate" style="color:var(--error)">failed — ${esc(job.detail||"")}</span> <button class="ghost sm" onclick="installPack('${p.key}')">Retry</button>`;
  else if(p.state==="installed") cta=`<span class="sstate" style="color:var(--success)">installed</span>`;
  else if(CAPFROZEN) cta=`<span class="sstate">runs on a source-install Brain</span>`;
  else cta=`<button class="sm" onclick="installPack('${p.key}')">${p.state==="partial"?"Complete pack":"Install pack"}</button>`;
  const stars="●".repeat(p.impact)+"○".repeat(5-p.impact);
  return `<div class="x" style="cursor:default">
    <div class="x-t">${esc(p.name)}${p.recommended?' <span class="tag" style="color:var(--memory)">recommended</span>':''}</div>
    <div class="x-b">${esc(p.tagline)}</div>
    <div class="conn-s" style="margin:8px 0 0">impact <span style="color:var(--memory)">${stars}</span> · download ${esc(p.size)} · ${p.caps.length} capabilities</div>
    <div class="row" style="margin-top:8px">${cta}</div></div>`;
}
function renderPacks(packs){
  const g=$("packgrid"); if(!g)return;
  g.innerHTML=(packs||[]).map(packCard).join("");
  renderPackNudge(packs||[]);
}
function renderPackNudge(packs){
  const el=$("packNudge"); if(!el)return;
  const todo=packs.filter(p=>p.state!=="installed"&&!(p.install&&p.install.state==="done"));
  if(CAPFROZEN||!todo.length||localStorage.dlPackNudgeDismissed){el.style.display="none";return;}
  const rec=todo.find(p=>p.recommended)||todo[0];
  el.style.display="";
  el.innerHTML=`<div class="conn" style="border:1px solid var(--line);border-radius:12px;padding:12px 14px;margin:0 0 12px;gap:12px">
    <span style="width:8px;height:8px;border-radius:50%;flex:none;background:var(--memory)"></span>
    <div style="flex:1"><div class="conn-t">Your Brain can do more</div>
      <div class="conn-s">${todo.length} upgrade pack${todo.length>1?"s":""} available — start with ${esc(rec.name)}: ${esc(rec.tagline)}</div></div>
    <button class="sm" onclick="showPage('caps')">See packs</button>
    <button class="ghost sm" onclick="dismissPackNudge()">Later</button></div>`;
}
function dismissPackNudge(){localStorage.dlPackNudgeDismissed="1";$("packNudge").style.display="none";}
async function installPack(key){
  const p=(LASTCAPS&&LASTCAPS.packs||[]).find(x=>x.key===key); if(!p)return;
  const warn=`Install the ${p.name} pack?\n\n${p.tagline}\n\n`+
    `What this does: downloads about ${p.size} of open-source AI libraries onto this Mac `+
    `(${p.caps.length} capabilities). Everything runs locally — nothing about you is uploaded, `+
    `and models may fetch extra data on their first use. The Brain stays usable while it installs, `+
    `and you can switch any capability off afterwards from this page.`;
  if(!confirm(warn))return;
  let r;try{r=await api("/dreamlayer/packs",{method:"POST",body:JSON.stringify({pack:key})});}
  catch(e){toast("Brain offline");return;}
  if(r&&r.error){toast(r.error);return;}
  if(r&&r.items){LASTCAPS=r;CAPFROZEN=!!r.frozen;renderCaps(r);renderPacks(r.packs);
    toast(p.name+" installing — this can take a while");
    schedulePackPoll();}
}
let packPollT=null;
function schedulePackPoll(){clearTimeout(packPollT);packPollT=setTimeout(async()=>{
  let r;try{r=await api("/dreamlayer/capabilities");}catch(e){return;}
  if(r&&r.items){LASTCAPS=r;renderCaps(r);renderPacks(r.packs);
    if((r.packs||[]).some(p=>p.install&&p.install.state==="installing"))schedulePackPoll();}
},5000);}
let LASTCAPS=null;

async function toggleCap(key,disabled){
  let r;try{r=await api("/dreamlayer/capabilities",{method:"POST",
    body:JSON.stringify({key:key,disabled:disabled})});}catch(e){toast("Brain offline");return;}
  if(r&&r.items){LASTCAPS=r;CAPFROZEN=!!r.frozen;renderCaps(r);renderPacks(r.packs);
    toast("Capability "+key+(disabled?" off":" on"));}
}
function copyCap(cmd){navigator.clipboard&&navigator.clipboard.writeText(cmd);toast("Install command copied");}

/* --- Plan section: cloud entitlements + waitlist ------------------------- */
const CLOUD_WAITLIST="https://api.dreamlayer.app/api/waitlist";
function renderPlan(plan){
  const rows=$("planRows"); if(!rows||!plan)return;
  const onCloud=plan.plan==="cloud";
  if(onCloud){$("planBadge").textContent="· active";$("planBadge").style.color="var(--success)";
    const b=$("notifyBtn"); if(b)b.style.display="none";}
  rows.innerHTML=(plan.cloud_caps||[]).map(c=>`
    <div class="conn" style="padding:8px 0">
      <span style="width:8px;height:8px;border-radius:50%;flex:none;background:${c.active?"var(--success)":"var(--ghost)"}"></span>
      <div class="conn-s" style="flex:1">${esc(c.info)}</div>
      <span class="sstate">${c.active?"active":"with Cloud"}</span></div>`).join("");
}
async function joinWaitlist(){
  const email=prompt("DreamLayer Cloud waitlist — we'll email you once, when it opens.\n\nYour email:");
  if(!email)return;
  try{
    const r=await fetch(CLOUD_WAITLIST,{method:"POST",headers:{"Content-Type":"application/json"},
      body:JSON.stringify({email:email})});
    const d=await r.json();
    if(r.ok&&d.joined){toast(d.already?"You're already on the list":"You're on the list — #"+d.count);}
    else toast(d.error||"That email didn't look right");
  }catch(e){toast("Couldn't reach the waitlist — try again later");}
}

let toastT; function toast(m){const t=$("toast");t.innerHTML='<span class="dot"></span>'+esc(m);
  t.classList.add("show");clearTimeout(toastT);toastT=setTimeout(()=>t.classList.remove("show"),1900);}

async function loadMemFile(){
  let r; try{r=await api("/dreamlayer/memory/file");}catch(e){return;}
  const el=$("memfile"); if(!el)return;
  el.textContent=r.exists?`${r.path}  (${Math.round(r.bytes/1024)} KB)`:"no memory file yet — it's created on your first memory";
}
async function browseMemory(){
  let r; try{r=await api("/dreamlayer/memory/browse",{method:"POST"});}catch(e){return;}
  if(r.url){window.open(r.url,"_blank");}
  else{alert("Datasette isn't installed. Run:\n\n"+(r.command||"pip install 'dreamlayer[infra]'"));}
}
async function exportMemory(){
  const dest=prompt("Export a copy of your memory to which path?"); if(!dest)return;
  let r; try{r=await api("/dreamlayer/memory/export",{method:"POST",body:JSON.stringify({dest})});}catch(e){return;}
  alert(r.ok?`Exported → ${r.dest} (${Math.round(r.bytes/1024)} KB)`:`Export failed: ${r.error||"unknown"}`);
}
async function loadCloudView(){
  let r; try{r=await api("/dreamlayer/cloud");}catch(e){return;}
  const s=$("cloudSees"); if(s){s.textContent=r.enabled
    ?`Vault ${r.vault?Math.round(r.vault.bytes/1024)+" KB ciphertext":"— no backup"} · ${(r.relay&&r.relay.rooms?r.relay.rooms.length:0)} relay room(s) · ${r.listings||0} listing(s) — opaque shapes only.`
    :"Cloud is off — the server holds nothing about you.";}
  const ul=$("cloudCant"); if(ul){ul.innerHTML="";(r.cannot_see||[]).forEach(x=>{ul.innerHTML+=`<li>${esc(x)}</li>`;});}
}
async function load(){
  loadMemFile(); loadCloudView();
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
  const mm=["keyword","ollama","api"].indexOf(c.config.model)>=0?c.config.model:"keyword";
  $("ourl").value=c.config.ollama_url||"";$("ochat").value=c.config.ollama_chat_model||"";
  $("ovis").value=c.config.ollama_vision_model||"";$("email").checked=!!c.config.email_enabled;
  // primary API brain
  $("aprov").value=c.config.api_provider||"custom";
  $("abase").value=c.config.api_base_url||"";$("amodel").value=c.config.api_model||"";
  $("akey").placeholder=c.config.api_key==="set"?"key saved — leave blank to keep":"API key (blank if local)";
  apiPreset(false);
  pickModel(mm,true);
  const cloud=$("cloud");cloud.checked=!incog&&!!c.config.cloud_enabled;cloud.disabled=incog;
  $("incognito").checked=incog;
  // cloud provider
  $("cprov").value=c.config.cloud_provider||"openai";
  $("cbase").value=c.config.cloud_base_url||"";$("cmodel").value=c.config.cloud_model||"";
  $("ckey").placeholder=c.config.cloud_api_key==="set"?"key saved — leave blank to keep":"API key";
  provPreset(false);   // reflect key-field visibility without clobbering saved values
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
  renderPlan(c.plan);
  refreshStatus(); loadHistory(); loadHealth(); loadAgenda(); loadPeople(); loadCalendars();
  loadContactsSync(); loadReminders(); loadCaps();
}

function fmtWhen(ts){if(!ts)return "";const d=new Date(ts*1000);
  return d.toLocaleString([], {weekday:"short",hour:"numeric",minute:"2-digit"});}
async function loadAgenda(){let r;try{r=await api("/dreamlayer/calendar");}catch(e){return;}
  const items=r.items||[];
  $("agenda").innerHTML=items.length?items.map(e=>{
    const synced=e.source==="calendar";
    const badge=synced?`<span class="tag">${esc(e.calendar||"Calendar")}</span>`:"";
    const rm=synced?"":`<button class="sm ghost" onclick='rmEvent(${esc(JSON.stringify(e.title))},${e.ts})'>Remove</button>`;
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

async function loadPeople(){
  // Two people stores merged by name: the dossier registry (/dreamlayer/people —
  // hand-added + Contacts sync) and the glasses' social memory
  // (/dreamlayer/social/people — relation, notes, and debts jotted on the HUD).
  let reg={items:[]}, soc={people:[]};
  try{reg=await api("/dreamlayer/people");}catch(e){}
  try{soc=await api("/dreamlayer/social/people");}catch(e){}
  // a real Map: names are user/contact data — on a plain object a person
  // named "__proto__" vanishes and "constructor" resolves to Object itself
  const map=new Map();
  (reg.items||[]).forEach(p=>{const k=(p.name||"").trim().toLowerCase();if(!k)return;
    map.set(k,{name:p.name,note:p.note||"",tags:p.tags||[],source:p.source||"",
            relation:"",notes:[],debts:[]});});
  (soc.people||[]).forEach(p=>{const k=(p.name||"").trim().toLowerCase();if(!k)return;
    const e=map.get(k)||{name:p.name,note:"",tags:[],source:"glasses",relation:"",notes:[],debts:[]};
    e.relation=p.relation||e.relation||"";
    e.notes=p.notes||[];e.debts=p.debts||[];e.last_seen=p.last_seen||"";
    map.set(k,e);});
  const items=[...map.values()];
  $("people").innerHTML=items.length?items.map(p=>{
    const tags=(p.tags||[]).map(t=>`<span class="tag">${esc(t)}</span>`).join(" ");
    const badge=p.source==="contacts"?`<span class="tag">contact</span>`
      :(p.source==="glasses"?`<span class="tag">met on Halo</span>`:"");
    const rel=p.relation?`<span class="tag">${esc(p.relation)}</span>`:"";
    const debts=(p.debts||[]).map(d=>`<span class="tag" style="background:#3a1420;color:#ff9db0;border-color:#5a2030">${esc(d)}</span>`).join(" ");
    const notes=(p.notes&&p.notes.length)?p.notes.map(esc).join(" · "):"";
    const detail=[esc(p.note||""),notes].filter(Boolean).join(" · ");
    const removable=p.source!=="contacts"&&p.source!=="glasses";
    const rm=removable?`<button class="sm ghost" onclick='rmPerson(${esc(JSON.stringify(p.name))})'>Remove</button>`:"";
    return `<li><div><div class="q">${esc(p.name)} ${rel} ${badge}</div>`+
      `<div class="a">${detail} ${tags} ${debts}</div></div>${rm}</li>`;}).join("")
    :'<li class="empty">No one yet — introduce people, sync your Contacts, or meet someone on your Halo.</li>';}
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
  const a=$("apiFields"),aon=m==="api";
  a.style.maxHeight=aon?"900px":"0";a.style.opacity=aon?"1":"0";a.style.marginTop=aon?"12px":"0";
  if(aon){renderApiWarn(); if(!silent) scanAgents();}   // auto-detect on open
  if(!silent&&m==="keyword"){saveModel(true);}
  renderModel();
  if(m==="ollama") checkModel();
}
// EXACT mirror of backends.is_local_endpoint / _LOCAL_NETS. Kept in lockstep so
// this warning never disagrees with the server's egress accounting. Local =
// localhost, *.local, IPv4 loopback/RFC-1918/link-local, or ::1. Everything
// else — a public IP, a bare hostname (a DNS search domain could resolve it to
// a public host), or anything unparseable — is a REMOTE endpoint your queries
// leave the device to reach.
function isLocalUrl(u){
  let host;try{host=new URL(u).hostname.toLowerCase();}catch(e){return null;}   // null = can't tell yet
  if(!host)return null;
  if(host[0]==="["&&host[host.length-1]==="]")host=host.slice(1,-1);            // strip IPv6 brackets
  if(host==="localhost"||host.endsWith(".local")||host==="::1")return true;
  const m=host.match(/^(\\d+)\\.(\\d+)\\.(\\d+)\\.(\\d+)$/);
  if(m){const a=+m[1],b=+m[2];
    return a===127||a===10||(a===192&&b===168)||(a===172&&b>=16&&b<=31)||(a===169&&b===254);}
  return false;                                                                 // public / bare host → remote
}
const APROV={custom:{base:"",model:"",key:true},openai:{base:"https://api.openai.com",model:"gpt-4o-mini",key:true},
  anthropic:{base:"https://api.anthropic.com",model:"claude-3-5-haiku-latest",key:true},
  gemini:{base:"https://generativelanguage.googleapis.com",model:"gemini-1.5-flash",key:true},
  openrouter:{base:"https://openrouter.ai/api",model:"openai/gpt-4o-mini",key:true},
  ollama:{base:"http://localhost:11434",model:"llama3.2",key:false}};
function apiPreset(apply){const p=APROV[$("aprov").value]||APROV.custom;
  if(apply){$("abase").value=p.base;$("amodel").value=p.model;}
  $("abase").placeholder=p.base||"http://localhost:1234/v1";$("amodel").placeholder=p.model||"model name";
  $("akey").style.display=p.key?"":"none";
  renderApiWarn();
}
function renderApiWarn(){const el=$("apiWarn");if(!el)return;
  const loc=isLocalUrl($("abase").value.trim());
  const lost='<b>What stays with DreamLayer:</b> your agent answers questions, but it does <b>not</b> run '+
    'DreamLayer\'s own on-device features. The fact-checker, memory lenses and private capture read '+
    'DreamLayer\'s local memory, not your agent\'s. Vision (naming what you look at) stays on the built-in path, '+
    'and answers aren\'t glasses-shaped the way the built-in brain\'s are.';
  if(loc===true){
    el.innerHTML='<div class="mstat" style="margin-top:12px"><div class="head"><span class="sdot ok"></span>'+
      '<b>On your device</b> &nbsp;<span class="tag privacy">local</span></div>'+
      '<div class="lead" style="margin:6px 0 0">This endpoint is on your machine or network, so questions '+
      'never leave your device and it keeps working while incognito — same as the built-in brain. '+lost+'</div></div>';
  }else if(loc===false){
    el.innerHTML='<div class="mstat" style="margin-top:12px;border-color:var(--amber)"><div class="head">'+
      '<span class="sdot warn"></span><b>Remote endpoint — your queries leave this device</b> &nbsp;'+
      '<span class="tag" style="color:var(--amber)">egress</span></div>'+
      '<div class="lead" style="margin:6px 0 0"><b>Privacy:</b> every question is sent to this service, '+
      '<b>counted and logged as cloud egress</b>, and <b>silenced while you\'re incognito</b> (it falls back to '+
      'on-device keyword search). DreamLayer can\'t see or control what that service does with your data. '+lost+'</div></div>';
  }else{
    el.innerHTML='<div class="conn-s" style="margin-top:12px">Enter your endpoint URL above. A localhost / LAN '+
      'address stays on-device; a public URL sends your questions off the device (logged as egress, off in incognito).</div>';
  }
}
async function saveApi(){const body={model:"api",api_provider:$("aprov").value,
    api_base_url:$("abase").value.trim(),api_model:$("amodel").value.trim()};
  const k=$("akey").value.trim(); if(k) body.api_key=k;
  await api("/dreamlayer/config",{method:"POST",body:JSON.stringify(body)});$("akey").value="";
  modelSel="api";toast("Your API is now the brain");load();}
async function testApi(){const el=$("apiStatus");el.innerHTML='<div class="mstat"><div class="shimmer"></div></div>';
  await saveApi();
  let r;try{r=await api("/dreamlayer/api/test",{method:"POST",body:"{}"});}catch(e){r={ok:false,error:"request failed"};}
  el.innerHTML='<div class="mstat"><div class="head"><span class="sdot '+(r.ok?'ok':'warn')+'"></span>'+
    '<b>'+(r.ok?'Connected':'Not working')+'</b></div><div class="lead" style="margin:0">'+
    (r.ok?'Your agent replied: <code>'+esc(r.reply||'ok')+'</code>':esc(r.error||'no reply — check the URL, model'+
    ' and key'))+'</div></div>';
}
// one-click discovery: find agents already running on this Mac and connect one
// with a single tap — nothing to type. Everything found is localhost.
let FOUND=[];
async function scanAgents(){const el=$("apiFound");
  el.innerHTML='<div class="mstat" style="margin-top:8px"><div class="shimmer"></div></div>';
  let r;try{r=await api("/dreamlayer/api/discover");}catch(e){r={agents:[]};}
  FOUND=r.agents||[];
  if(!FOUND.length){el.innerHTML='<div class="conn-s" style="margin:8px 0 0">No local agent found on the usual ports. '+
    'Start one (e.g. <code>ollama serve</code>) and scan again, or set it up by hand below.</div>'+
    '<div class="row" style="margin-top:8px"><button class="sm ghost" onclick="scanAgents()">Scan again</button></div>';return;}
  el.innerHTML=FOUND.map((a,i)=>{
    const ms=(a.models&&a.models.length)?a.models:[""];
    const pick=ms.length>1?'<select id="am'+i+'" style="max-width:170px">'+
      ms.map(m=>'<option>'+esc(m)+'</option>').join("")+'</select>'
      :'<span class="conn-s" style="flex:1">'+esc(ms[0]||"default model")+'</span>';
    return '<div class="mstat" style="margin-top:8px"><div class="head"><span class="sdot ok"></span>'+
      '<b>'+esc(a.label)+'</b> &nbsp;<span class="tag privacy">local · on-device</span></div>'+
      '<div class="conn-s" style="margin:4px 0 8px">'+esc(a.base_url)+'</div>'+
      '<div class="row" style="align-items:center;gap:8px">'+pick+
      '<button class="sm" onclick="connectFound('+i+')">Connect</button></div></div>';}).join("");
}
function connectFound(i){const a=FOUND[i];if(!a)return;
  const sel=$("am"+i);
  const model=(sel&&sel.value)||(a.models&&a.models[0])||"";
  $("aprov").value=a.provider;apiPreset(false);
  $("abase").value=a.base_url;$("amodel").value=model;$("akey").value="";
  renderApiWarn();
  saveApi();                                   // model=api + fields, zero typing
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
  let pull = miss.length?`<div class="lead" style="margin:12px 0 0">One-click pull the missing model${miss.length>1?'s':''}:</div>`+
      `<div class="row" style="margin-top:8px;flex-wrap:wrap;gap:8px">`+
      miss.map(nm=>`<button class="sm" onclick='pullModel(${esc(JSON.stringify(nm))})'>⬇ Pull ${esc(nm)}</button>`).join("")+
      `</div><div id="pullOut" class="conn-s" style="margin-top:8px"></div>`:'';
  el.innerHTML='<div class="mstat"><div class="head"><span class="sdot ok"></span>'+
    `<b>Ollama reachable</b></div><div class="lead" style="margin:0 0 8px">at <code>${esc(r.url)}</code></div>`+
    body+pull+'<div style="margin-top:12px"><button class="sm ghost" onclick="checkModel()">Check again</button></div></div>';
}
async function pullModel(name){const o=$("pullOut");
  if(o)o.textContent=`Pulling ${name}… this can take a few minutes.`;
  toast(`Pulling ${name}…`);
  let r;try{r=await api("/dreamlayer/model/pull",{method:"POST",body:JSON.stringify({model:name})});}catch(e){r={ok:false,status:"request failed"};}
  if(o)o.textContent=r.ok?`✓ ${name} pulled.`:`Couldn't pull ${name}: ${r.status||"error"}`;
  toast(r.ok?`${name} ready`:`Pull failed`);checkModel();}
async function saveModel(silent){
  await api("/dreamlayer/config",{method:"POST",body:JSON.stringify({model:modelSel,
    ollama_url:$("ourl").value,ollama_chat_model:$("ochat").value,
    ollama_vision_model:$("ovis").value})});
  if(!silent)toast("Saved"); if(modelSel==="ollama")checkModel(); load();
}
async function saveEmail(){   // the email/iMessage switch saves instantly, like the other toggles
  await api("/dreamlayer/config",{method:"POST",
    body:JSON.stringify({email_enabled:$("email").checked})});
  toast($("email").checked?"Reading email & iMessage":"Email & iMessage off"); load();
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

/* cloud provider — presets mirror backends.PROVIDER_PRESETS */
const CPROV={
  openai:{base:"https://api.openai.com",model:"gpt-4o-mini",key:true},
  anthropic:{base:"https://api.anthropic.com",model:"claude-3-5-haiku-latest",key:true},
  gemini:{base:"https://generativelanguage.googleapis.com",model:"gemini-1.5-flash",key:true},
  openrouter:{base:"https://openrouter.ai/api",model:"openai/gpt-4o-mini",key:true},
  ollama:{base:"http://localhost:11434",model:"llama3.2",key:false},
  dreamlayer:{base:"https://api.dreamlayer.app",model:"dreamlayer-standard",key:true},
  custom:{base:"",model:"",key:true},
};
function provPreset(apply){const p=CPROV[$("cprov").value]||CPROV.custom;
  if(apply){$("cbase").value=p.base;$("cmodel").value=p.model;}      // manual switch → fill
  $("cbase").placeholder=p.base||"https://…";$("cmodel").placeholder=p.model||"model name";
  $("ckey").style.display=p.key?"":"none";                          // Ollama-local needs no key
}
async function saveCloud(){const body={cloud_provider:$("cprov").value,
    cloud_base_url:$("cbase").value,cloud_model:$("cmodel").value};
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
  let html=
    `<div class="mrow"><span class="lbl">Version</span><span class="nm">v${esc(h.version)}</span><span class="st off-t">running</span></div>`+
    `<div class="mrow"><span class="lbl">Index</span><span class="nm">${h.disk_kb} KB</span><span class="st off-t">on disk</span></div>`+
    `<div class="mrow"><span class="lbl">Model</span><span class="nm">${h.ollama_ms==null?'—':h.ollama_ms+' ms'}</span><span class="st ${h.ollama_ms==null?'off-t':'ok-t'}">${h.ollama_ms==null?'keyword / offline':'ollama latency'}</span></div>`+
    `<div class="mrow"><span class="lbl">Uptime</span><span class="nm">${up}</span><span class="st off-t">since boot</span></div>`;
  // Per-seam failure ledger (HealthLedger.snapshot): degradation is silent for
  // the wearer, visible to the operator here. A seam with any failures shows the
  // count + its last error; a clean seam reads "ok".
  const seams=h.seams||{};const names=Object.keys(seams).sort();
  if(names.length){
    html+=`<div class="mrow" style="opacity:.55;margin-top:10px"><span class="lbl">Seams</span><span class="nm"></span><span class="st off-t">failures · last error</span></div>`;
    for(const nm of names){const s=seams[nm]||{};const bad=(s.failures||0)>0;
      const detail=bad?esc(String(s.last_error||"").slice(0,80)):`${s.successes||0} ok`;
      html+=`<div class="mrow"><span class="lbl">${esc(nm)}</span>`+
        `<span class="nm">${bad?s.failures+" fail":"ok"}</span>`+
        `<span class="st ${bad?'off-t':'ok-t'}">${detail}</span></div>`;}
  }
  $("health").innerHTML=html;
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
$("pdetail").addEventListener("click",e=>{if(e.target.id==="pdetail")closePluginDetail();});

const CAP_HELP={midi:"Send MIDI notes to music apps on your Mac (e.g. Ableton, VCV).",
  network:"Reach the internet to look things up.",vision:"Use the Brain’s on-device vision model to read what you see.",
  fs:"Read files you point it at.",mesh:"Talk to a GhostMode circle of nearby wearers.",
  object_lens:"Add rows to the look-at-a-thing panel.",glance:"Add a lens the look can route to.",
  cards:"Draw its own card on the HUD.",perception:"Use the fast on-glass perception tier.",
  ring:"Read your kept-memory ledger.",shop:"Feed prices/reviews into TasteLens."};
let pluginsById={};
async function loadPlugins(){let r;try{r=await api("/dreamlayer/plugins");}catch(e){const ul=$("plugins");if(ul){ul.innerHTML='<li class="conn-s" style="margin:0">Couldn’t reach the Brain — plugins unavailable.</li>';}return;}
  $("plugCaps").textContent=(r.capabilities||[]).join(", ")||"the basics";
  pluginsById={};(r.installed||[]).forEach(p=>{pluginsById[p.name]=p;});
  const ul=$("plugins");
  if(!(r.installed||[]).length){ul.innerHTML='<li class="conn-s" style="margin:0">No plugins installed yet — browse the store.</li>';return;}
  ul.innerHTML=(r.installed||[]).map(p=>{
    const perms=(p.requires||[]).length?(p.requires||[]).map(x=>"needs "+esc(x)).join(" · "):"no special access";
    return '<li class="conn"><div style="flex:1;cursor:pointer" onclick="openPluginDetail(\''+esc(p.name)+'\')"><div class="conn-t">'+esc(p.name)+' <span class="conn-s">v'+esc(p.version||"")+'</span>'+(p.official?' <span style="color:var(--memory)">✓ Official</span>':'')+'</div>'+
      '<div class="conn-s">'+perms+' · <span style="color:var(--memory)">See what it does →</span></div></div>'+
      '<button class="sm ghost" onclick="removePlugin(\''+esc(p.name)+'\')">Remove</button></li>';
  }).join("");}
function openPluginDetail(name){const p=pluginsById[name];if(!p)return;
  const long=((p.long&&p.long.length)?p.long:[p.description||""]).map(t=>'<p>'+esc(t)+'</p>').join("");
  const shot=p.screenshot?'<img class="shot" src="'+esc(p.screenshot)+'" alt="'+esc(p.name)+' preview">':"";
  const perms=(p.requires||[]).length
    ?(p.requires||[]).map(x=>'<div class="permr"><b>'+esc(x)+'</b><span>'+esc(CAP_HELP[x]||"a capability it requested")+'</span></div>').join("")
    :'<div class="permr"><span>No special access — it only extends the layer’s own surfaces.</span></div>';
  $("pdinner").innerHTML=shot+'<div class="pdbody">'+
    '<h3>'+esc(p.name)+'</h3><div class="pdby">v'+esc(p.version||"")+' · '+esc(p.author||"community")+(p.official?' · <span style="color:var(--memory)">✓ Official · built by the DreamLayer team</span>':'')+'</div>'+
    '<div class="pdlong">'+long+'</div>'+
    (p.forwho?'<div class="pdsec">Who it’s for</div><p style="color:var(--muted2,#b9c8c5);margin:0">'+esc(p.forwho)+'</p>':"")+
    '<div class="pdsec">Permissions it asks for</div>'+perms+
    '<div class="mfoot" style="margin-top:20px"><button class="ghost" onclick="closePluginDetail()">Close</button>'+
    '<button class="ghost" onclick="removePlugin(\''+esc(p.name)+'\');closePluginDetail()">Remove</button></div></div>';
  $("pdetail").classList.add("show");}
function closePluginDetail(){$("pdetail").classList.remove("show");}
window.openPluginDetail=openPluginDetail;window.closePluginDetail=closePluginDetail;
async function removePlugin(name){await api("/dreamlayer/plugins/remove",{method:"POST",body:JSON.stringify({name})});
  toast("Removed "+name);loadPlugins();}
async function installPlugin(){const raw=$("plugPkg").value.trim();if(!raw){return;}
  let body;try{body=JSON.parse(raw);}catch(e){$("plugStatus").textContent="not valid JSON";return;}
  $("plugStatus").textContent="Validating…";
  const r=await api("/dreamlayer/plugins/install",{method:"POST",body:JSON.stringify(body)});
  if(r.ok){$("plugPkg").value="";const w=(r.warnings||[]).length?" — note: "+(r.warnings||[]).join("; "):"";$("plugStatus").textContent=w;toast("Installed");loadPlugins();}
  else{$("plugStatus").textContent=(r.errors||["failed"]).join("; ");}}
window.removePlugin=removePlugin;

load();
loadPlugins();
renderExplainers();
buildNav();
setInterval(refreshStatus,4000);
setInterval(()=>{if(modelSel==="ollama")checkModel();},15000);
</script></body></html>"""
