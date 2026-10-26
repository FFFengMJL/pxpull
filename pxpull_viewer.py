"""HTML 查看器生成器：把解析后的 .pxcp 导出成浏览器里可点选/测量的页面。"""

from __future__ import annotations

import json
import os
import re


def _safe_name(s: str) -> str:
    s = re.sub(r'[\\/:*?"<>|\r\n\t]+', "_", s).strip(" .")
    return s or "unnamed"


TEMPLATE = r"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>__TITLE__ · PxCook 设计稿查看器</title>
<style>
  :root{
    --bg:#0d1117; --panel:#161b22; --panel2:#1c2129; --line:#2a3038;
    --fg:#d6dde6; --dim:#8b949e; --accent:#3fb1ff;
    --text:#4ea1ff; --shape:#59d9a4; --image:#ffb454; --empty:#6e7681;
  }
  *{box-sizing:border-box}
  html,body{height:100%}
  body{margin:0;background:var(--bg);color:var(--fg);
       font:13px/1.5 -apple-system,"Segoe UI","Noto Sans CJK SC","Microsoft YaHei",sans-serif;
       overflow:hidden}
  #app{display:flex;flex-direction:column;height:100vh}

  header{display:flex;align-items:center;gap:14px;padding:8px 14px;
         background:var(--panel);border-bottom:1px solid var(--line);flex:none}
  header h1{font-size:14px;margin:0;font-weight:600;white-space:nowrap}
  header .meta{color:var(--dim);font-size:12px;white-space:nowrap}
  header .spacer{flex:1}
  header .coord{color:var(--dim);font-variant-numeric:tabular-nums;font-size:12px;
                min-width:150px;text-align:right}
  .btn{background:var(--panel2);border:1px solid var(--line);color:var(--fg);
       border-radius:6px;padding:4px 10px;cursor:pointer;font-size:12px}
  .btn:hover{border-color:#3d4652;background:#232a33}
  .btn.on{background:#12324a;border-color:#1f5f8b;color:#bfe6ff}
  .seg{display:flex;gap:4px}
  .zoom{display:flex;align-items:center;gap:6px;color:var(--dim);font-size:12px}
  .zoom input{width:110px}

  main{display:flex;flex:1;min-height:0}
  #layers{width:250px;flex:none;background:var(--panel);border-right:1px solid var(--line);
          display:flex;flex-direction:column;min-height:0}
  .tabs{display:flex;border-bottom:1px solid var(--line)}
  .tab{flex:1;background:none;border:0;border-bottom:2px solid transparent;color:var(--dim);
       padding:7px 0;cursor:pointer;font-size:12px}
  .tab.on{color:var(--fg);border-bottom-color:var(--accent)}
  #layers .search{padding:8px;border-bottom:1px solid var(--line)}
  .asset{display:flex;align-items:center;gap:8px;padding:6px;border-radius:6px;cursor:pointer;
         text-decoration:none;color:var(--fg)}
  .asset:hover{background:#1b2129}
  .asset img{width:42px;height:42px;object-fit:contain;background:#0b0f14;border-radius:4px;flex:none}
  .asset .an{flex:1;font-size:12px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
  .asset .asz{color:var(--dim);font-size:11px}
  #layers input{width:100%;background:var(--panel2);border:1px solid var(--line);
                border-radius:6px;color:var(--fg);padding:5px 8px;font-size:12px;outline:none}
  #layers input:focus{border-color:#2f6f9e}
  #list{overflow:auto;flex:1;padding:4px 0}
  .row{display:flex;align-items:center;gap:8px;padding:4px 10px;cursor:pointer;
       border-left:2px solid transparent}
  .row:hover{background:#1b2129}
  .row.sel{background:#12324a;border-left-color:var(--accent)}
  .dot{width:7px;height:7px;border-radius:50%;flex:none}
  .row .nm{flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
  .row .sz{color:var(--dim);font-size:11px;font-variant-numeric:tabular-nums}

  #stagewrap{flex:1;overflow:auto;position:relative;background:
      repeating-conic-gradient(#11161c 0% 25%, #0d1117 0% 50%) 50%/24px 24px;
      display:flex;align-items:flex-start;justify-content:center;padding:24px}
  #fit{position:relative;flex:none}
  #stage{position:relative;transform-origin:0 0;box-shadow:0 0 0 1px #2a3038,0 8px 40px #0008;
         background:#000;width:100%;height:100%}
  #artboard{display:block;width:100%;height:100%;image-rendering:auto;user-select:none;-webkit-user-drag:none}
  #boxes{position:absolute;inset:0}
  .box{position:absolute;border:1px solid transparent;cursor:crosshair}
  body.showboxes .box{border-color:rgba(63,177,255,.35)}
  body.showboxes .box.k-text{border-color:rgba(78,161,255,.45)}
  body.showboxes .box.k-image{border-color:rgba(255,180,84,.45)}
  body.showboxes .box.k-shape{border-color:rgba(89,217,164,.35)}
  .box:hover{border-color:#fff!important;background:rgba(63,177,255,.10)}
  .box.sel{border-color:#ffd166!important;background:rgba(255,209,102,.10);
           box-shadow:0 0 0 1px #ffd16680}
  #tip{position:fixed;pointer-events:none;background:#000c;border:1px solid #3d4652;
       border-radius:4px;padding:3px 7px;font-size:11px;color:#dce6f2;display:none;z-index:99;
       white-space:nowrap}

  #inspect{width:330px;flex:none;background:var(--panel);border-left:1px solid var(--line);
           overflow:auto;padding:10px 12px}
  #inspect h2{font-size:12px;color:var(--dim);margin:2px 0 8px;font-weight:600;letter-spacing:.04em}
  .field{display:flex;gap:8px;padding:2px 0;font-size:12px}
  .field .k{color:var(--dim);width:64px;flex:none}
  .field .v{flex:1;word-break:break-all;font-variant-numeric:tabular-nums}
  .swatch{display:inline-block;width:11px;height:11px;border-radius:2px;
          border:1px solid #ffffff33;vertical-align:-1px;margin-right:5px}
  .sect{margin:12px 0 4px;border-top:1px solid var(--line);padding-top:10px}
  pre{margin:6px 0;background:#0b0f14;border:1px solid var(--line);border-radius:6px;
      padding:8px;overflow:auto;font:11.5px/1.55 "JetBrains Mono",Consolas,monospace;color:#c9d4e0;
      white-space:pre-wrap;word-break:break-all}
  .empty{color:var(--dim);padding:30px 6px;text-align:center;line-height:1.8}
  .tag{display:inline-block;padding:0 6px;border-radius:999px;font-size:11px;
       background:#1f6feb22;color:#7cc0ff;border:1px solid #1f6feb44}
</style>
</head>
<body>
<div id="app">
  <header>
    <h1 id="title">__TITLE__</h1>
    <span class="meta" id="meta"></span>
    <span class="spacer"></span>
    <span class="coord" id="coord">&nbsp;</span>
    <div class="zoom"><input id="zoom" type="range" min="10" max="200" step="5" value="__FIT__">
      <span id="zoomv">100%</span></div>
    <div class="seg">
      <button class="btn on" id="btn-boxes">框线</button>
      <button class="btn" id="btn-dim">遮罩</button>
      <button class="btn" id="btn-hide">只看框线</button>
    </div>
  </header>
  <main>
    <aside id="layers">
      <div class="tabs">
        <button class="tab on" data-tab="list">图层</button>
        <button class="tab" data-tab="assetlist">切图</button>
      </div>
      <div class="search"><input id="q" placeholder="搜索图层名 / 文本…"></div>
      <div id="list"></div>
      <div id="assetlist" style="display:none;overflow:auto;flex:1;padding:6px"></div>
    </aside>
    <section id="stagewrap">
      <div id="fit" style="width:__W__px;height:__H__px">
        <div id="stage" style="width:__W__px;height:__H__px">
          <img id="artboard" src="artboard@2x.png" alt="artboard">
          <div id="boxes"></div>
        </div>
      </div>
    </section>
    <aside id="inspect"><div class="empty">点选任意图层<br>查看尺寸、颜色、字体与 CSS</div></aside>
  </main>
</div>
<div id="tip"></div>
<script>
const DATA = __DATA__;
const W = __W__, H = __H__, RETINA = __RETINA__;
const KIND_CN = {text:"文本", shape:"形状", image:"图片", empty:"容器"};
const KIND_COLOR = {text:"var(--text)", shape:"var(--shape)", image:"var(--image)", empty:"var(--empty)"};
const els = DATA.elements;
const stage = document.getElementById('stage');
const fitEl = document.getElementById('fit');
const boxes = document.getElementById('boxes');
const listEl = document.getElementById('list');
const inspect = document.getElementById('inspect');
const tip = document.getElementById('tip');
const coord = document.getElementById('coord');
let scale = 1, sel = -1;

document.getElementById('meta').textContent =
  `${DATA.artboard.width} × ${DATA.artboard.height} · ${els.length} 个图层 · ${DATA.assets.length} 个切图`;

function hex(argb){ return argb ? '#' + argb.slice(2) : ''; }
function esc(s){ return (s||'').replace(/[&<>"]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c])); }

/* ---------- 图层列表 ---------- */
function renderList(filter){
  const f = (filter||'').toLowerCase();
  listEl.innerHTML = '';
  for(let i=els.length-1;i>=0;i--){
    const e = els[i];
    if (f && !(e.name||'').toLowerCase().includes(f) && !(e.text||'').toLowerCase().includes(f)) continue;
    const row = document.createElement('div');
    row.className = 'row' + (i===sel?' sel':'');
    row.dataset.i = i;
    row.innerHTML = `<span class="dot" style="background:${KIND_COLOR[e.kind]}"></span>
      <span class="nm">${esc(e.name || e.text || '(未命名)')}</span>
      <span class="sz">${Math.round(e.width)}×${Math.round(e.height)}</span>`;
    row.onclick = ()=> select(i, true);
    row.ondblclick = ()=> zoomTo(i);
    row.onmouseenter = ()=> highlight(i, true);
    row.onmouseleave = ()=> highlight(i, false);
    listEl.appendChild(row);
  }
  if(!listEl.children.length) listEl.innerHTML = '<div class="empty">没有匹配的图层</div>';
}

/* ---------- 画框 ---------- */
function buildBoxes(){
  const frag = document.createDocumentFragment();
  els.forEach((e,i)=>{
    const d = document.createElement('div');
    d.className = 'box k-'+e.kind;
    d.style.left = e.x+'px'; d.style.top = e.y+'px';
    d.style.width = Math.max(1,e.width)+'px'; d.style.height = Math.max(1,e.height)+'px';
    d.dataset.i = i;
    d.onclick = ev => { ev.stopPropagation(); select(i, true); };
    d.onmouseenter = ev => { highlight(i,true); showTip(ev,i); };
    d.onmousemove = showTip;
    d.onmouseleave = ev => { highlight(i,false); tip.style.display='none'; };
    frag.appendChild(d);
  });
  boxes.appendChild(frag);
}
function boxOf(i){ return boxes.querySelector('.box[data-i="'+i+'"]'); }
function highlight(i,on){
  const b = boxOf(i); if(!b) return;
  b.style.outline = on ? '2px solid #fff' : '';
}
function showTip(ev,i){
  const e = els[i];
  tip.style.display='block';
  tip.innerHTML = `${esc(e.name||e.text||'')} &nbsp;<span style="color:#8b949e">${Math.round(e.width)}×${Math.round(e.height)} @ ${Math.round(e.x)},${Math.round(e.y)}</span>`;
  tip.style.left = (ev.clientX+14)+'px';
  tip.style.top = (ev.clientY+16)+'px';
}

/* ---------- 选中 ---------- */
function select(i, scrollList){
  sel = i;
  boxes.querySelectorAll('.box.sel').forEach(b=>b.classList.remove('sel'));
  const b = boxOf(i); if(b) b.classList.add('sel');
  document.querySelectorAll('.row.sel').forEach(r=>r.classList.remove('sel'));
  const row = listEl.querySelector('.row[data-i="'+i+'"]');
  if(row){ row.classList.add('sel'); if(scrollList) row.scrollIntoView({block:'nearest'}); }
  renderInspector(els[i]);
}
function cssOf(e){
  const L = [];
  L.push(`position:absolute;`);
  L.push(`left:${round(e.x)}px; top:${round(e.y)}px;`);
  L.push(`width:${round(e.width)}px; height:${round(e.height)}px;`);
  if(e.kind==='text'){
    const f = e.font||{};
    L.push(`font-family:"${f.family||''}", "Noto Sans CJK SC", sans-serif;`);
    L.push(`font-size:${f.size}px; color:${hex(f.color)};`);
    if(f.line_height) L.push(`line-height:${round(f.line_height)}px;`);
    if(f.align && f.align!=='left') L.push(`text-align:${f.align};`);
    if(f.letter_spacing) L.push(`letter-spacing:${f.letter_spacing}px;`);
    if(f.bold) L.push(`font-weight:700;`);
  } else {
    const fills = e.fill||[];
    if(fills.length){
      const f = fills[0];
      if(f.type==='solid') L.push(`background:${hex(f.color)};`);
      else {
        const g = f.kind==='linear' ? `linear-gradient(${f.angle}deg, ` +
          f.stops.map(s=>`${hex(s.color)} ${round(s.pos*100)}%`).join(', ') + `)` : hex(f.color);
        L.push(`background:${g};`);
      }
    }
    if(e.radius && e.radius.length){
      const r = e.radius; L.push(`border-radius:${r.map(round).join('px ')}px;`);
    }
    if(e.stroke && e.stroke.length){
      const s = e.stroke[0];
      L.push(`border:${round(s.width)}px solid ${hex(s.color)};`);
    }
    if(e.shadow && e.shadow.length){
      const s = e.shadow[0];
      L.push(`box-shadow:${round(s.x)}px ${round(s.y)}px ${round(s.blur)}px ${hex(s.color)};`);
    }
  }
  if(e.opacity!==undefined && e.opacity<1) L.push(`opacity:${e.opacity};`);
  return L.join('\n');
}
function round(v){ return Math.round(v*100)/100; }

function rowHtml(k,v){ return `<div class="field"><span class="k">${k}</span><span class="v">${v}</span></div>`; }
function swatch(argb){ return `<span class="swatch" style="background:${hex(argb)}"></span>`; }

function renderInspector(e){
  if(!e) return;
  let h = `<h2>图层信息 <span class="tag">${KIND_CN[e.kind]||e.kind}</span></h2>`;
  h += rowHtml('名称', esc(e.name||'(未命名)'));
  h += rowHtml('位置', `x ${round(e.x)} &nbsp; y ${round(e.y)}`);
  h += rowHtml('尺寸', `${round(e.width)} × ${round(e.height)} px`);
  if(e.opacity!==undefined && e.opacity<1) h += rowHtml('透明度', e.opacity);
  if(e.text){
    h += rowHtml('文本', `<span style="white-space:pre-wrap">${esc(e.text)}</span>`);
  }
  if(e.font){
    const f=e.font;
    h += `<div class="sect"><h2>字体</h2>`;
    h += rowHtml('字体', `${esc(f.family||'')} &nbsp;${f.size}px`);
    h += rowHtml('颜色', `${swatch(f.color)} ${hex(f.color)}`);
    h += rowHtml('行高', `${round(f.line_height)}px &nbsp; 对齐 ${f.align}`);
    if(f.bold) h += rowHtml('字重', 'Bold');
    h += `</div>`;
  }
  if(e.fill && e.fill.length){
    h += `<div class="sect"><h2>填充</h2>`;
    for(const f of e.fill){
      if(f.type==='solid') h += rowHtml('纯色', `${swatch(f.color)} ${hex(f.color)}`);
      else h += rowHtml('渐变', `${f.kind} ${f.angle}° ` + f.stops.map(s=>`${swatch(s.color)}${hex(s.color)} ${round(s.pos*100)}%`).join(' → '));
    }
    h += `</div>`;
  }
  if(e.stroke && e.stroke.length){
    const s=e.stroke[0];
    h += `<div class="sect"><h2>描边</h2>` + rowHtml('线条', `${round(s.width)}px ${swatch(s.color)} ${hex(s.color)} (${s.position})`) + `</div>`;
  }
  if(e.shadow && e.shadow.length){
    h += `<div class="sect"><h2>阴影</h2>`;
    for(const s of e.shadow) h += rowHtml('阴影', `${swatch(s.color)} ${round(s.x)},${round(s.y)} 模糊${round(s.blur)}`);
    h += `</div>`;
  }
  h += `<div class="sect"><h2>CSS</h2><pre id="css">${esc(cssOf(e))}</pre>
        <button class="btn" id="copycss">复制 CSS</button>
        <button class="btn" id="crop">导出切图</button></div>`;
  inspect.innerHTML = h;
  document.getElementById('copycss').onclick = ()=> copy(cssOf(e), 'CSS 已复制');
  document.getElementById('crop').onclick = ()=> exportCrop(e);
}

/* ---------- 切图导出 ---------- */
function exportCrop(e){
  const img = document.getElementById('artboard');
  const k = (img.naturalWidth||W*RETINA) / W;
  const x = Math.max(0, Math.round(e.x*k)), y = Math.max(0, Math.round(e.y*k));
  const w = Math.min(img.naturalWidth-x, Math.round(e.width*k));
  const h = Math.min(img.naturalHeight-y, Math.round(e.height*k));
  if(w<=0||h<=0) return;
  const c = document.createElement('canvas'); c.width=w; c.height=h;
  c.getContext('2d').drawImage(img, x,y,w,h, 0,0,w,h);
  c.toBlob(b=>{
    const a=document.createElement('a');
    a.href=URL.createObjectURL(b);
    a.download=(e.name||'slice').replace(/[\\/:*?"<>|]/g,'_')+`@${k}x.png`;
    a.click(); setTimeout(()=>URL.revokeObjectURL(a.href),3000);
  }, 'image/png');
}

function copy(text, msg){
  navigator.clipboard.writeText(text).then(()=>toast(msg)).catch(()=>toast('复制失败'));
}
let toastT;
function toast(msg){
  let el = document.getElementById('toast');
  if(!el){ el=document.createElement('div'); el.id='toast'; el.style.cssText=
    'position:fixed;left:50%;bottom:26px;transform:translateX(-50%);background:#1f6feb;color:#fff;'+
    'padding:6px 14px;border-radius:6px;font-size:12px;z-index:100;opacity:.95'; document.body.appendChild(el); }
  el.textContent=msg; el.style.display='block';
  clearTimeout(toastT); toastT=setTimeout(()=>el.style.display='none',1400);
}

/* ---------- 切图面板 ---------- */
function renderAssets(){
  const box = document.getElementById('assetlist');
  box.innerHTML = '';
  (DATA.assets||[]).forEach(a=>{
    const el = document.createElement('a');
    el.className='asset'; el.href=a.file; el.download=a.file.split('/').pop();
    el.innerHTML = `<img src="${a.file}" alt=""><span class="an">${esc(a.name)}</span>
                    <span class="asz">${a.w||''}×${a.h||''}</span>`;
    box.appendChild(el);
  });
  if(!box.children.length) box.innerHTML='<div class="empty">没有内嵌切图</div>';
}
document.querySelectorAll('.tab').forEach(t=>{
  t.onclick = ()=>{
    document.querySelectorAll('.tab').forEach(x=>x.classList.toggle('on', x===t));
    const showAssets = t.dataset.tab==='assetlist';
    document.getElementById('list').style.display = showAssets?'none':'block';
    document.getElementById('assetlist').style.display = showAssets?'block':'none';
    document.querySelector('#layers .search').style.display = showAssets?'none':'block';
  };
});

/* ---------- 缩放到图层 ---------- */
function zoomTo(i){
  const e = els[i], wrap = document.getElementById('stagewrap');
  if(!e) return;
  const pad = 90;
  const k = Math.min((wrap.clientWidth-pad)/Math.max(e.width,4),
                     (wrap.clientHeight-pad)/Math.max(e.height,4));
  scale = Math.max(0.1, Math.min(3, Math.round(k*100)/100));
  document.getElementById('zoom').value = Math.round(scale*100);
  applyScale();
  select(i, true);
  requestAnimationFrame(()=>{
    wrap.scrollLeft = Math.max(0, e.x*scale + 24 - (wrap.clientWidth - e.width*scale)/2);
    wrap.scrollTop  = Math.max(0, e.y*scale + 24 - (wrap.clientHeight - e.height*scale)/2);
  });
}

/* ---------- 缩放 ---------- */
function applyScale(){
  fitEl.style.width = (W*scale)+'px';
  fitEl.style.height = (H*scale)+'px';
  stage.style.transform = `scale(${scale})`;
  document.getElementById('zoomv').textContent = Math.round(scale*100)+'%';
}
function fit(){
  const wrap = document.getElementById('stagewrap');
  const k = Math.min((wrap.clientWidth-52)/W, (wrap.clientHeight-52)/H);
  scale = Math.max(0.1, Math.round(k*100)/100);
  const z=document.getElementById('zoom'); z.value=Math.round(scale*100);
  applyScale();
}

/* ---------- 交互 ---------- */
document.getElementById('zoom').oninput = ev=>{
  scale = ev.target.value/100; applyScale();
};
document.getElementById('stagewrap').addEventListener('mousemove', ev=>{
  const r = stage.getBoundingClientRect();
  const x = (ev.clientX-r.left)/scale, y=(ev.clientY-r.top)/scale;
  if(x>=0&&y>=0&&x<=W&&y<=H) coord.textContent = `x ${x.toFixed(0)}  y ${y.toFixed(0)}`;
});
document.getElementById('q').oninput = ev=> renderList(ev.target.value);
document.getElementById('btn-boxes').onclick = ev=>{
  document.body.classList.toggle('showboxes');
  ev.target.classList.toggle('on');
};
document.getElementById('btn-dim').onclick = ev=>{
  const on = !document.body.classList.contains('dimmed');
  document.body.classList.toggle('dimmed', on);
  stage.style.opacity = on ? '.35' : '1';
  ev.target.classList.toggle('on', on);
};
document.getElementById('btn-hide').onclick = ev=>{
  const on = !document.body.classList.contains('hideart');
  document.body.classList.toggle('hideart', on);
  document.body.classList.add('showboxes');
  document.getElementById('btn-boxes').classList.add('on');
  document.getElementById('artboard').style.visibility = on ? 'hidden' : 'visible';
  stage.style.background = on ? '#0b0f14' : '#000';
  ev.target.classList.toggle('on', on);
};
document.addEventListener('keydown', ev=>{
  if(ev.key==='Escape'){ sel=-1;
    boxes.querySelectorAll('.box.sel').forEach(b=>b.classList.remove('sel'));
    document.querySelectorAll('.row.sel').forEach(r=>r.classList.remove('sel'));
    inspect.innerHTML='<div class="empty">点选任意图层<br>查看尺寸、颜色、字体与 CSS</div>'; }
  if(ev.key==='+'||ev.key==='='){ scale=Math.min(2,scale+0.1); applyScale(); }
  if(ev.key==='-'){ scale=Math.max(0.1,scale-0.1); applyScale(); }
});
window.addEventListener('resize', ()=>{});

/* ---------- 启动 ---------- */
document.body.classList.add('showboxes');
buildBoxes();
renderList('');
renderAssets();
fit();
if(els.length) { /* 默认不选中，避免遮挡 */ }
</script>
</body>
</html>
"""


def build_viewer(doc, outdir: str, max_density: int | None = None,
                 densities: str = "best") -> int:
    os.makedirs(outdir, exist_ok=True)
    # 1. 画板整图
    if doc.artboard_png:
        with open(os.path.join(outdir, "artboard@2x.png"), "wb") as fh:
            fh.write(doc.artboard_png)
    else:
        raise SystemExit("该文件没有内嵌画板整图，无法生成查看器")
    # 2. 资源
    assets_dir = os.path.join(outdir, "assets")
    os.makedirs(assets_dir, exist_ok=True)
    asset_meta = []
    for a in doc.assets:
        sub = os.path.join(assets_dir, _safe_name(a.name))
        os.makedirs(sub, exist_ok=True)
        best = a.best_png(max_density=max_density)
        kept = a.variants if densities == "all" else [best, a.svg()]
        for v in kept:
            if v is None:
                continue
            if max_density and (v.density or 0) * 100 > max_density + 1e-6:
                continue
            ext = v.fmt if v.fmt in ("png", "svg") else "bin"
            with open(os.path.join(sub, f"{v.name}.{ext}"), "wb") as fh:
                fh.write(v.data)
        if best:
            fn = _safe_name(a.name) + ".png"
            with open(os.path.join(assets_dir, fn), "wb") as fh:
                fh.write(best.data)
            asset_meta.append({"name": a.name, "file": "assets/" + fn,
                               "w": best.size[0] if best.size else None,
                               "h": best.size[1] if best.size else None,
                               "variants": [v.name for v in a.variants]})
    # 3. 元素 JSON
    elements = []
    for el in doc.elements:
        s = _simplify(doc, el)
        elements.append(s)
    data = {"artboard": {"name": doc.name, "width": doc.width, "height": doc.height,
                         "retina": doc.retina_scale},
            "source": doc.source_path, "project": doc.project, "platform": doc.platform,
            "assets": asset_meta, "elements": elements}
    with open(os.path.join(outdir, "elements.json"), "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=1)
    # 4. HTML
    payload = json.dumps({"artboard": data["artboard"], "assets": asset_meta,
                          "elements": elements}, ensure_ascii=False)
    payload = payload.replace("</", "<\\/")
    html = (TEMPLATE
            .replace("__TITLE__", _html_escape(doc.name or os.path.basename(outdir)))
            .replace("__W__", str(doc.width))
            .replace("__H__", str(doc.height))
            .replace("__RETINA__", str(doc.retina_scale))
            .replace("__FIT__", "100")
            .replace("__DATA__", payload))
    with open(os.path.join(outdir, "viewer.html"), "w", encoding="utf-8") as fh:
        fh.write(html)
    print(f"查看器已生成: {os.path.join(outdir, 'viewer.html')}")
    print(f"  - 画板图  : artboard@2x.png ({doc.retina_scale}x)")
    print(f"  - 元素数据: elements.json ({len(elements)} 个)")
    print(f"  - 切图    : assets/ ({len(asset_meta)} 组)")
    return 0


def _html_escape(s: str) -> str:
    return (s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


def _simplify(doc, el: dict) -> dict:
    bi = el.get("baseInfo") or {}
    ri = el.get("rectInfo") or {}
    vi = el.get("vectorInfo") or {}
    fi = el.get("fontInfo") or {}
    out = {"id": bi.get("id"), "name": bi.get("name", ""),
           "kind": doc.element_kind(el),
           "x": ri.get("x", 0), "y": ri.get("y", 0),
           "width": ri.get("width", 0), "height": ri.get("height", 0),
           "opacity": bi.get("opacity", 1)}
    fills = []
    for c in (vi.get("fill") or {}).get("colors", []):
        g = c.get("gradientColor") or {}
        if g.get("colors"):
            fills.append({"type": "gradient", "kind": g.get("type", "linear"),
                          "angle": g.get("angle", 90),
                          "stops": [{"pos": p, "color": f"{col & 0xFFFFFFFF:08x}"}
                                    for p, col in zip(g.get("colorPos", []), g.get("colors", []), strict=False)]})
        else:
            col = ((c.get("solidColor") or {}).get("color", 0)) & 0xFFFFFFFF
            if col >> 24:  # 非全透明
                fills.append({"type": "solid", "color": f"{col:08x}"})
    if fills:
        out["fill"] = fills
    strokes = []
    for s in (vi.get("stroke") or {}).get("styles", []):
        col = (((s.get("color") or {}).get("solidColor") or {}).get("color", 0)) & 0xFFFFFFFF
        strokes.append({"width": s.get("thickness", 1), "position": s.get("position", "inside"),
                        "color": f"{col:08x}"})
    if strokes:
        out["stroke"] = strokes
    if vi.get("radius"):
        out["radius"] = vi["radius"]
    shadows = []
    for sh in (el.get("effectInfo") or {}).get("shadows", []):
        shadows.append({"x": sh.get("x", 0), "y": sh.get("y", 0), "blur": sh.get("blur", 0),
                        "spread": sh.get("spread", 0), "inner": sh.get("inner", False),
                        "color": "%08x" % (sh.get("color", 0) & 0xFFFFFFFF)})
    if shadows:
        out["shadow"] = shadows
    if fi.get("text"):
        f = (fi.get("fonts") or [{}])[0]
        out["text"] = fi["text"]
        out["font"] = {"family": f.get("name"), "size": f.get("size"),
                       "color": "%08x" % (f.get("color", 0) & 0xFFFFFFFF),
                       "line_height": f.get("lineHeight"), "align": f.get("alignment"),
                       "letter_spacing": f.get("letterSpacing", 0),
                       "bold": f.get("bold", False), "italic": f.get("italic", False)}
    return out
