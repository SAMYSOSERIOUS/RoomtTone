/* Roomtone floating gallery: example posts from every source, drifting like pinned screenshots.
   Identity is never in the data (names and avatars are black bars); personal details in the text
   were replaced by black bars in the pipeline. Mounts itself once the dashboard has rendered. */
(function(){
  const CSS=`
  #rt-float{max-width:1440px;margin:0 auto;padding:0 clamp(16px,3vw,40px) 26px}
  #rt-float .band{position:relative;height:520px;border-radius:14px;overflow:hidden;background:#10161d;
    background-image:radial-gradient(ellipse at 30% 20%,rgba(42,120,214,.18),transparent 55%),radial-gradient(ellipse at 75% 80%,rgba(235,104,52,.16),transparent 50%),linear-gradient(rgba(255,255,255,.035) 1px,transparent 1px),linear-gradient(90deg,rgba(255,255,255,.035) 1px,transparent 1px);
    background-size:auto,auto,40px 40px,40px 40px}
  #rt-float .head{position:absolute;left:20px;top:16px;z-index:3;color:#c3cad2;pointer-events:none}
  #rt-float .head b{display:block;font:400 22px/1.1 'Instrument Serif',Georgia,serif;color:#fff;margin-bottom:4px}
  #rt-float .head span{font:400 11px/1.4 'IBM Plex Mono',monospace;letter-spacing:.06em;text-transform:uppercase}
  #rt-float .legend{position:absolute;right:20px;top:20px;z-index:3;font:400 11px 'IBM Plex Mono',monospace;color:#8a96a3;pointer-events:none}
  #rt-float .card{position:absolute;width:300px;transition:opacity .9s ease;background:#fff;border-radius:10px;padding:12px 14px 10px;box-shadow:0 18px 40px rgba(0,0,0,.45),0 0 0 1px rgba(255,255,255,.06);
    font-family:'IBM Plex Sans',system-ui,sans-serif;color:#10161d;cursor:default;will-change:transform;animation:rt-drift var(--dur) ease-in-out infinite alternate;animation-delay:var(--delay);transform:rotate(var(--rot))}
  #rt-float .card::after{content:"";position:absolute;inset:0;border-radius:10px;background:linear-gradient(115deg,rgba(255,255,255,.35),transparent 40%);pointer-events:none}
  #rt-float .card:hover{animation-play-state:paused;z-index:5;transform:rotate(0) scale(1.06);box-shadow:0 26px 60px rgba(0,0,0,.6),0 0 0 2px #eb6834}
  #rt-float .top{display:flex;align-items:center;gap:9px;margin-bottom:8px}
  #rt-float .av{width:30px;height:30px;border-radius:50%;flex:none;background:repeating-linear-gradient(45deg,#10161d 0 3px,#2b3540 3px 6px)}
  #rt-float .id{flex:1;display:flex;flex-direction:column;gap:5px}
  #rt-float .id i{display:block;height:9px;background:#10161d;border-radius:2px}
  #rt-float .id i+i{height:7px;background:#c3cad2}
  #rt-float .src{font:500 10px 'IBM Plex Mono',monospace;letter-spacing:.06em;text-transform:uppercase;color:#4d5966;text-align:right;line-height:1.3}
  #rt-float .txt{font-size:12.5px;line-height:1.45;word-break:break-word}
  #rt-float .txt em{font-style:normal;background:rgba(235,104,52,.16);box-shadow:0 0 0 2px rgba(235,104,52,.16);border-radius:2px}
  #rt-float .txt s{text-decoration:none;background:#10161d;color:#10161d;border-radius:2px}
  #rt-float .sig{display:flex;flex-wrap:wrap;gap:4px;margin-top:8px}
  #rt-float .sig span{font:400 10px 'IBM Plex Mono',monospace;background:#f1f3f5;border:1px solid rgba(16,22,29,.08);border-radius:4px;padding:2px 6px;color:#4d5966}
  #rt-float .foot{display:flex;justify-content:space-between;align-items:center;margin-top:8px;font:400 10.5px 'IBM Plex Mono',monospace;color:#4d5966}
  #rt-float .foot b{color:#b8461b;font-weight:500}
  #rt-float .bar{display:inline-block;width:46px;height:4px;background:#e1e5ea;border-radius:2px;vertical-align:middle;margin:0 4px;overflow:hidden}
  #rt-float .bar i{display:block;height:100%;background:#eb6834}
  @keyframes rt-drift{from{translate:0 0}to{translate:var(--dx) var(--dy)}}
  @media (prefers-reduced-motion:reduce){#rt-float .card{animation:none}}
  @media (max-width:760px){#rt-float .band{height:520px}#rt-float .card{width:240px}}`;
  function esc(s){return s.replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;")}
  function render(text){
    return esc(text).replace(/\[\[(.*?)\]\]/g,"<em>$1</em>").replace(/█+/g,m=>"<s>"+m+"</s>");
  }
  function hl(h){const d=Math.floor(h/24)+1,hr=((h%24)+24)%24,ap=hr<12?"am":"pm",h12=hr%12===0?12:hr%12;return "day "+d+", "+h12+ap;}
  function rng(seed){let a=seed;return()=>{a|=0;a=a+0x6D2B79F5|0;let t=Math.imul(a^a>>>15,1|a);t=t+Math.imul(t^t>>>7,61|t)^t;return((t^t>>>14)>>>0)/4294967296;};}
  function mount(){
    const RT=window.RT; if(!RT) return false;
    const nav=[...document.querySelectorAll("button")].find(b=>/All datasets/.test(b.textContent||""));
    if(!nav) return false;
    let host=nav; for(let i=0;i<4&&host.parentElement;i++){host=host.parentElement; if(host.offsetWidth>1000) break;}
    const anchor=host.parentElement.children[Array.prototype.indexOf.call(host.parentElement.children,host)];
    if(document.getElementById("rt-float")) return true;
    const gallery=(RT.sources&&RT.sources.all&&RT.sources.all.gallery)||RT.gallery||[];
    if(!gallery.length) return true;
    const st=document.createElement("style"); st.textContent=CSS; document.head.appendChild(st);
    const wrap=document.createElement("section"); wrap.id="rt-float";
    const band=document.createElement("div"); band.className="band"; band.setAttribute("aria-label","Example automated-looking posts, identity hidden");
    band.innerHTML='<div class="head"><b>What the ghosts look like</b><span>'+gallery.length+' example posts from every source · names, avatars and personal details blacked out · hover to hold</span></div><div class="legend">orange = stock phrase · black = redacted</div>';
    const r=rng(7), slots=Math.min(gallery.length,9), cols=3;
    const cardFor=(e,i)=>{
      const c=document.createElement("article"); c.className="card";
      const col=i%cols,row=Math.floor(i/cols);
      const left=4+col*31+r()*5, top=15+row*21+r()*5;
      c.style.left=left+"%"; c.style.top=top+"%";
      c.style.setProperty("--rot",((r()-.5)*7).toFixed(1)+"deg");
      c.style.setProperty("--dx",((r()-.5)*40).toFixed(0)+"px"); c.style.setProperty("--dy",((r()-.5)*30).toFixed(0)+"px");
      c.style.setProperty("--dur",(9+r()*8).toFixed(1)+"s"); c.style.setProperty("--delay",(-r()*10).toFixed(1)+"s");
      c.innerHTML='<div class="top"><div class="av" title="avatar hidden"></div><div class="id" title="name hidden"><i style="width:'+(80+Math.round(r()*70))+'px"></i><i style="width:'+(50+Math.round(r()*50))+'px"></i></div><div class="src">'+esc(e[8]||"")+'<br>'+esc(hl(e[4]))+' · '+esc(e[7]||"")+'</div></div>'
        +'<div class="txt">'+render(e[0])+'</div>'
        +'<div class="sig">'+(e[2]||[]).map(s=>'<span>'+esc(s)+'</span>').join("")+'</div>'
        +'<div class="foot"><span>score <span class="bar"><i style="width:'+Math.round(e[3]*100)+'%"></i></span>'+e[3].toFixed(2)+'</span><b>'+e[5]+' replies · '+e[6]+' likes from people</b></div>';
      return c;
    };
    const live=[]; for(let i=0;i<slots;i++){const c=cardFor(gallery[i],i);band.appendChild(c);live.push(c);}
    // the rest float through: every few seconds one card fades out and the next example takes its slot
    if(gallery.length>slots && !(window.matchMedia&&matchMedia("(prefers-reduced-motion: reduce)").matches)){
      let next=slots, k=0;
      setInterval(()=>{const i=k%slots;k++;const old=live[i];if(!old||old.matches(":hover"))return;old.style.opacity="0";
        setTimeout(()=>{const c=cardFor(gallery[next%gallery.length],i);next++;c.style.opacity="0";band.replaceChild(c,old);live[i]=c;requestAnimationFrame(()=>{c.style.opacity="1"});},900);},4000);
    }
    wrap.appendChild(band);
    host.parentElement.insertBefore(wrap,anchor);
    return true;
  }
  let tries=0; const t=setInterval(()=>{ if(mount()||++tries>200) clearInterval(t); },150);
})();
