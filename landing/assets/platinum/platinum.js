/* ============================================================
   DreamLayer Platinum — shared chrome runtime for sub-pages.
   Injects the menu bar (working pull-downs + live clock + Juno),
   the Juno desk accessory, and the footer strip. Configure per
   page BEFORE this script loads:
     window.PLATINUM = { app: "Lens Gallery", daLine: "every lens runs live." };
   ============================================================ */
(function(){
"use strict";
var CFG = window.PLATINUM || {};
document.documentElement.classList.add("platinum");

function h(html){ var t=document.createElement("template"); t.innerHTML=html.trim(); return t.content.firstChild; }

/* ---------- menu bar ---------- */
var bar = h('<header class="menubar" role="banner">\
  <nav class="mleft" aria-label="Site">\
    <button class="mitem logo" data-menu="pm-dl" aria-haspopup="true" aria-expanded="false" aria-label="DreamLayer menu"\
      data-balloon="The DreamLayer menu. About, downloads, early access."><span class="mark6" aria-hidden="true"></span></button>\
    <span class="mitem appname"><span class="apptxt"></span></span>\
    <button class="mitem" data-menu="pm-explore" aria-haspopup="true" aria-expanded="false">Explore</button>\
    <button class="mitem" data-menu="pm-apps" aria-haspopup="true" aria-expanded="false">Apps</button>\
  </nav>\
  <div class="mright">\
    <span class="mitem mjuno" data-balloon="Juno is running."><img src="assets/juno/juno_icon32b.png" alt="" width="32" height="32"></span>\
    <a class="mitem pulse" href="./#soon"><i class="dot" aria-hidden="true"></i>Early access</a>\
    <span class="mclock" id="pmclock">9:41 AM</span>\
  </div></header>');
bar.querySelector(".apptxt").textContent = CFG.app || "DreamLayer";
document.body.prepend(bar);

var panels = h('<div></div>');
panels.innerHTML = '\
<nav class="mpanel" id="pm-dl" aria-label="DreamLayer">\
  <a href="./">The Desktop <span class="mdim">home</span></a>\
  <hr>\
  <div class="mdl-head">Desktop Picture</div>\
  <button class="deskpick" data-pic="dusk"><span class="chk"></span>Dusk · Juno’s World</button>\
  <button class="deskpick" data-pic="dawn"><span class="chk"></span>Dawn</button>\
  <button class="deskpick" data-pic="juno"><span class="chk"></span>The Scene</button>\
  <button class="deskpick" data-pic="pattern"><span class="chk"></span>Platinum Pattern</button>\
  <hr>\
  <a href="https://github.com/LetsGetToWorkBro/dreamlayer/releases/latest/download/DreamLayer.dmg">Download for Mac <span class="mdim">.dmg</span></a>\
  <a href="https://github.com/LetsGetToWorkBro/dreamlayer" target="_blank" rel="noopener">GitHub <span class="mdim">↗</span></a>\
  <a href="https://letsgettoworkbro.github.io/dreamlayer-docs/" target="_blank" rel="noopener">Knowledge Base <span class="mdim">↗</span></a>\
  <hr>\
  <a href="./#soon">Get Early Access…</a>\
</nav>\
<nav class="mpanel" id="pm-explore" aria-label="Explore">\
  <a href="./#feel">What It Feels Like</a>\
  <a href="./#see">See It Move</a>\
  <a href="./#can">What It Can Do</a>\
  <a href="./#lenses">The Six Lenses</a>\
  <a href="./#brain">Architecture</a>\
  <a href="./#veil">Privacy Veil</a>\
  <a href="./#faq">How Is This Possible?</a>\
</nav>\
<nav class="mpanel" id="pm-apps" aria-label="Apps">\
  <a href="./simulator.html">Halo Simulator <span class="mdim">in the browser</span></a>\
  <a href="./lens-builder.html">Lens Builder <span class="mdim">no code</span></a>\
  <a href="./gallery.html">Lens Gallery <span class="mdim">remixable</span></a>\
  <a href="./golf.html">Figment Golf <span class="mdim">fewest bytes</span></a>\
  <a href="./plugins.html">Plugin Store <span class="mdim">community</span></a>\
  <a href="./playground.html">Web BLE Playground <span class="mdim">talk Lua</span></a>\
</nav>';
while(panels.firstChild) document.body.appendChild(panels.firstChild);

var openBtn=null;
function closeMenus(){
  if(!openBtn) return;
  document.getElementById(openBtn.dataset.menu).classList.remove("on");
  openBtn.setAttribute("aria-expanded","false"); openBtn=null;
}
function openMenu(btn){
  closeMenus();
  var p=document.getElementById(btn.dataset.menu);
  var r=btn.getBoundingClientRect();
  p.classList.add("on");
  p.style.left=Math.max(0,Math.min(r.left,innerWidth-p.getBoundingClientRect().width-6))+"px";
  btn.setAttribute("aria-expanded","true"); openBtn=btn;
}
bar.querySelectorAll(".mitem[data-menu]").forEach(function(b){
  b.addEventListener("click",function(e){ e.stopPropagation();
    (openBtn===b)?closeMenus():openMenu(b); });
  b.addEventListener("mouseenter",function(){ if(openBtn&&openBtn!==b) openMenu(b); });
});
document.addEventListener("click",function(e){
  if(openBtn && !e.target.closest(".mpanel")) closeMenus();
});
addEventListener("keydown",function(e){ if(e.key==="Escape") closeMenus(); });
document.querySelectorAll(".mpanel a").forEach(function(a){
  a.addEventListener("click",function(){ setTimeout(closeMenus,10); });
});

/* ---------- Desktop Picture picker (shared with the landing) ---------- */
(function(){
  var picks=[].slice.call(document.querySelectorAll(".deskpick"));
  var VALID={dusk:1,dawn:1,juno:1,pattern:1};
  function apply(pic){
    var b=document.body;
    b.classList.remove("desk-dusk","desk-dawn","desk-juno");
    b.classList.toggle("deskpic", pic!=="pattern");
    if(pic!=="pattern") b.classList.add("desk-"+pic);
    picks.forEach(function(p){ p.querySelector(".chk").textContent = p.dataset.pic===pic ? "✓" : ""; });
  }
  var pic="dusk";
  try{ var s=localStorage.getItem("dldeskpic"); if(s&&VALID[s]) pic=s; }catch(e){}
  apply(pic);
  picks.forEach(function(p){ p.addEventListener("click",function(){
    pic=p.dataset.pic; try{ localStorage.setItem("dldeskpic",pic); }catch(e){} apply(pic);
  }); });
})();

/* ---------- clock ---------- */
var clockEl=document.getElementById("pmclock");
function tick(){
  var d=new Date(), hh=d.getHours(), m=d.getMinutes();
  var ap=hh>=12?"PM":"AM"; hh=hh%12; if(hh===0)hh=12;
  clockEl.textContent=hh+":"+(m<10?"0":"")+m+" "+ap;
}
tick(); setInterval(tick,20000);

/* ---------- Juno desk accessory ---------- */
if(CFG.daLine !== false){
  var da = h('<aside class="mw sub da" id="junoDA" aria-hidden="true">\
    <div class="tbar"><span class="tstripes"></span><span class="ttext">Juno</span>\
      <span class="tstripes"></span>\
      <button class="wbox collapse" id="pdaShade" tabindex="-1"\
        data-balloon="WindowShade — roll Juno up. She won\'t mind."></button></div>\
    <div class="mbody">\
      <picture>\
        <source media="(prefers-reduced-motion: reduce)" srcset="assets/juno/juno_da_still.png">\
        <img class="dasprite" src="assets/juno/juno_da.webp" alt="" width="96" height="96">\
      </picture>\
      <div class="dacap"></div>\
    </div></aside>');
  da.querySelector(".dacap").textContent = CFG.daLine || "hi. i’m juno.";
  document.body.appendChild(da);
  try{ if(sessionStorage.getItem("dlda")==="shut") da.classList.add("shut"); }catch(e){}
  da.querySelector("#pdaShade").addEventListener("click",function(){
    var s=da.classList.toggle("shut");
    try{ sessionStorage.setItem("dlda", s?"shut":"open"); }catch(e){}
  });
}

/* ---------- footer ---------- */
if(CFG.footer !== false){
  document.body.appendChild(h('<footer class="pfoot"><div class="in">\
    <a class="wordmark" href="./"><span class="ring"></span>DREAMLAYER</a>\
    <span class="lnks"><a href="mailto:hello@dreamlayer.app">hello@dreamlayer.app</a>\
      &nbsp;·&nbsp; <a href="./">home</a>\
      &nbsp;·&nbsp; <a href="./plugins.html">plugin store</a>\
      &nbsp;·&nbsp; <a href="https://github.com/LetsGetToWorkBro/dreamlayer" target="_blank" rel="noopener">GitHub ↗</a></span>\
    <small>Private by architecture. Yours to run, yours to keep.</small>\
  </div></footer>'));
}

/* the desktop is ready */
requestAnimationFrame(function(){ document.body.classList.add("desk-in"); });
})();
