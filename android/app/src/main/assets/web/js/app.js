/* =========================================================================
   国医大师孙光荣中医知识图谱 · 应用逻辑
   Sun Guangrong TCM Knowledge Graph — application logic
   研发：孙光荣大师弟子田建辉团队 × 医哲未来人工智能研究院 (IMPF-AI Institute)
   ========================================================================= */
'use strict';

/* ---------- 0. 小工具 ------------------------------------------------- */
const $  = (s, r) => (r || document).querySelector(s);
const $$ = (s, r) => Array.prototype.slice.call((r || document).querySelectorAll(s));
const esc = (s) => String(s == null ? '' : s).replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
const fmt = (n) => Number(n).toLocaleString('en-US');
const clamp = (v, a, b) => v < a ? a : v > b ? b : v;

let toastTimer = null;
function toast(msg) {
  const t = $('#toast');
  t.textContent = msg; t.classList.add('on');
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => t.classList.remove('on'), 1900);
}

/* 五类知识来源配色（与 CSS 变量同步） */
const ROLE_KEYS = ['sun_original', 'sun_compiled', 'classical_source', 'third_party_clinical', 'general_tcm'];
const ROLE_VAR = {
  sun_original: '--r-sun-original', sun_compiled: '--r-sun-compiled',
  classical_source: '--r-classical', third_party_clinical: '--r-third-party',
  general_tcm: '--r-general',
};
let CSSVAR = {};
function readTheme() {
  const cs = getComputedStyle(document.documentElement);
  CSSVAR = {};
  ['--canvas-bg', '--edge', '--edge-hi', '--ink', '--ink-3', '--paper', '--cinnabar', '--paper-2', '--line-2']
    .forEach(k => CSSVAR[k] = cs.getPropertyValue(k).trim());
  ROLE_KEYS.forEach(k => CSSVAR[k] = cs.getPropertyValue(ROLE_VAR[k]).trim());
}

/* =========================================================================
   1. 状态
   ========================================================================= */
const S = {
  D: null,                 // 原始数据
  n: 0, m: 0,
  X: null, Y: null, G: null,   // 坐标 / 度
  RI: null, TI: null,          // role index / type index
  ES: null, ET: null, ER: null,
  adjStart: null, adjList: null,   // CSR 邻接（存边号）
  vis: null,                       // 可见位
  roleOn: {}, docOn: {}, typeOn: {},
  typeKeys: [], roleLbl: {}, typeLbl: {}, relLbl: {},
  grid: null,
  sel: -1,
  focus: null,
  view: 'home',
  hist: [],                        // 详情浏览历史
};

/* =========================================================================
   2. 数据装载
   ========================================================================= */
function loadData() {
  const msg = $('#load-msg');
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open('GET', 'data/graph.json', true);
    xhr.responseType = 'text';
    xhr.onprogress = (e) => {
      const mb = (e.loaded / 1048576).toFixed(1);
      msg.textContent = '正 在 展 卷 · ' + mb + 'MB';
    };
    xhr.onerror = () => reject(new Error('network'));
    xhr.onload = () => {
      if (xhr.status && xhr.status >= 400) return reject(new Error('http ' + xhr.status));
      msg.textContent = '正 在 结 网';
      setTimeout(() => {
        try { resolve(JSON.parse(xhr.responseText)); } catch (err) { reject(err); }
      }, 16);
    };
    xhr.send();
  });
}

function buildIndexes(D) {
  S.D = D;
  const N = D.nodes, E = D.edges;
  const n = S.n = N.length, m = S.m = E.length;

  S.X = new Float32Array(n); S.Y = new Float32Array(n); S.G = new Uint16Array(n);
  S.RI = new Uint8Array(n); S.TI = new Uint8Array(n);

  S.typeKeys = Object.keys(D.types);
  const tIdx = {}; S.typeKeys.forEach((t, k) => tIdx[t] = k);
  const rIdx = {}; ROLE_KEYS.forEach((r, k) => rIdx[r] = k);

  for (let i = 0; i < n; i++) {
    const nd = N[i];
    S.X[i] = nd.x; S.Y[i] = nd.y; S.G[i] = Math.min(65535, nd.g);
    S.RI[i] = rIdx[nd.r] == null ? 4 : rIdx[nd.r];
    S.TI[i] = tIdx[nd.t] == null ? 0 : tIdx[nd.t];
  }

  S.ES = new Int32Array(m); S.ET = new Int32Array(m); S.ER = new Uint8Array(m);
  const cnt = new Int32Array(n);
  for (let k = 0; k < m; k++) {
    const e = E[k];
    S.ES[k] = e.s; S.ET[k] = e.t; S.ER[k] = rIdx[e.r] == null ? 4 : rIdx[e.r];
    cnt[e.s]++; cnt[e.t]++;
  }
  S.adjStart = new Int32Array(n + 1);
  for (let i = 0; i < n; i++) S.adjStart[i + 1] = S.adjStart[i] + cnt[i];
  S.adjList = new Int32Array(S.adjStart[n]);
  {
    const cur = S.adjStart.slice(0, n);
    for (let k = 0; k < m; k++) { S.adjList[cur[S.ES[k]]++] = k; S.adjList[cur[S.ET[k]]++] = k; }
  }

  S.vis = new Uint8Array(n).fill(1);

  ROLE_KEYS.forEach(r => S.roleOn[r] = true);
  Object.keys(D.docs).forEach(d => S.docOn[d] = true);
  S.typeKeys.forEach(t => S.typeOn[t] = true);
  Object.entries(D.roles).forEach(([k, v]) => S.roleLbl[k] = v.zh);
  Object.entries(D.types).forEach(([k, v]) => S.typeLbl[k] = v.zh);
  Object.entries(D.rels).forEach(([k, v]) => S.relLbl[k] = v.zh);

  // 类型计数
  S.typeCount = {};
  for (let i = 0; i < n; i++) { const t = N[i].t; S.typeCount[t] = (S.typeCount[t] || 0) + 1; }
  S.roleCount = {};
  for (let i = 0; i < n; i++) { const r = N[i].r; S.roleCount[r] = (S.roleCount[r] || 0) + 1; }
  S.docCount = {};
  for (let i = 0; i < n; i++) (N[i].d || []).forEach(d => S.docCount[d] = (S.docCount[d] || 0) + 1);

  buildGrid();
}

/* 均匀网格：视口裁剪 + 命中测试 */
const GRID_CELL = 34, GRID_PAD = 1500;
function buildGrid() {
  const side = Math.ceil((GRID_PAD * 2) / GRID_CELL);
  const cells = side * side;
  const cnt = new Int32Array(cells);
  const cellOf = (i) => {
    const cx = clamp(Math.floor((S.X[i] + GRID_PAD) / GRID_CELL), 0, side - 1);
    const cy = clamp(Math.floor((S.Y[i] + GRID_PAD) / GRID_CELL), 0, side - 1);
    return cy * side + cx;
  };
  for (let i = 0; i < S.n; i++) cnt[cellOf(i)]++;
  const start = new Int32Array(cells + 1);
  for (let c = 0; c < cells; c++) start[c + 1] = start[c] + cnt[c];
  const items = new Int32Array(S.n);
  const cur = start.slice(0, cells);
  for (let i = 0; i < S.n; i++) items[cur[cellOf(i)]++] = i;
  S.grid = { side, start, items };
}
function gridQuery(x0, y0, x1, y1, fn) {
  const g = S.grid, side = g.side;
  const a = clamp(Math.floor((x0 + GRID_PAD) / GRID_CELL), 0, side - 1);
  const b = clamp(Math.floor((x1 + GRID_PAD) / GRID_CELL), 0, side - 1);
  const c = clamp(Math.floor((y0 + GRID_PAD) / GRID_CELL), 0, side - 1);
  const d = clamp(Math.floor((y1 + GRID_PAD) / GRID_CELL), 0, side - 1);
  for (let cy = c; cy <= d; cy++) {
    const row = cy * side;
    for (let cx = a; cx <= b; cx++) {
      const k = row + cx;
      for (let p = g.start[k]; p < g.start[k + 1]; p++) fn(g.items[p]);
    }
  }
}

/* 过滤 */
function refilter() {
  const N = S.D.nodes;
  let shown = 0;
  for (let i = 0; i < S.n; i++) {
    const nd = N[i];
    let ok = S.roleOn[nd.r] && S.typeOn[nd.t];
    if (ok && nd.d && nd.d.length) {
      ok = false;
      for (let k = 0; k < nd.d.length; k++) if (S.docOn[nd.d[k]]) { ok = true; break; }
    }
    S.vis[i] = ok ? 1 : 0;
    if (ok) shown++;
  }
  let se = 0;
  for (let k = 0; k < S.m; k++) if (S.vis[S.ES[k]] && S.vis[S.ET[k]]) se++;
  S.shownN = shown; S.shownE = se;
  $('#ghud').innerHTML = '实体 <b>' + fmt(shown) + '</b> / ' + fmt(S.n) +
    '<br>关系 <b>' + fmt(se) + '</b> / ' + fmt(S.m);
  GR.invalidateBase();
  if (S.focus) enterFocus(S.focus.center);   // 聚焦视图跟随筛选一起更新
}

/* =========================================================================
   3. 图形引擎
   ========================================================================= */
const GR = {
  cv: null, ctx: null, W: 0, H: 0, dpr: 1,
  scale: 1, tx: 0, ty: 0,
  base: null, bctx: null, baseOK: false, BASE: 1600, baseScale: 1,
  moving: false, settleTimer: null, raf: 0,

  init() {
    this.cv = $('#cv');
    this.ctx = this.cv.getContext('2d', { alpha: false });
    this.dpr = Math.min(window.devicePixelRatio || 1, 2.5);
    this.base = document.createElement('canvas');
    this.BASE = (window.innerWidth * window.innerHeight > 900 * 1800) ? 1800 : 1500;
    this.base.width = this.base.height = this.BASE;
    this.bctx = this.base.getContext('2d', { alpha: false });
    this.baseScale = this.BASE / (GRID_PAD * 2);
    this.resize();
    // 旋转 / 分屏后重算：聚焦视图的坐标依赖画布尺寸，必须重新铺一次
    let rzTimer = null;
    window.addEventListener('resize', () => {
      clearTimeout(rzTimer);
      rzTimer = setTimeout(() => {
        this.resize();
        this.invalidateBase();
        if (S.focus) enterFocus(S.focus.center);
        this.request();
      }, 90);
    });
    this.bindTouch();
  },

  resize() {
    const st = $('#stage');
    const w = st.clientWidth || window.innerWidth, h = st.clientHeight || window.innerHeight;
    this.W = this.cv.width = Math.round(w * this.dpr);
    this.H = this.cv.height = Math.round(h * this.dpr);
    this.cv.style.width = w + 'px'; this.cv.style.height = h + 'px';
    this.cw = w; this.ch = h;
  },

  invalidateBase() { this.baseOK = false; this.request(); },

  /* --- 视图变换：屏幕(css px) = 世界 * scale + t --- */
  toScreen(x, y) { return [x * this.scale + this.tx, y * this.scale + this.ty]; },
  toWorld(px, py) { return [(px - this.tx) / this.scale, (py - this.ty) / this.scale]; },

  /* 适配可见节点。quantile<1 时只框住中心密集区（外圈孤岛留到视野外，
     初次进入图谱时观感更饱满，点「适配」仍可退回全图）。 */
  fit(animated, quantile) {
    const xs = [], ys = [];
    for (let i = 0; i < S.n; i++) { if (S.vis[i]) { xs.push(S.X[i]); ys.push(S.Y[i]); } }
    if (!xs.length) { xs.push(-100, 100); ys.push(-100, 100); }
    xs.sort((a, b) => a - b); ys.sort((a, b) => a - b);
    const q = quantile || 1;
    const lo = Math.floor((1 - q) / 2 * (xs.length - 1));
    const hi = xs.length - 1 - lo;
    const x0 = xs[lo], x1 = xs[hi], y0 = ys[lo], y1 = ys[hi];
    const pad = 16;
    const s = Math.min((this.cw - pad * 2) / Math.max(1, x1 - x0),
                       (this.ch - pad * 2 - 96) / Math.max(1, y1 - y0));
    this.animateTo(clamp(s, 0.02, 40), this.cw / 2 - (x0 + x1) / 2 * s,
                   (this.ch + 22) / 2 - (y0 + y1) / 2 * s, animated !== false);
  },

  centerOn(i, targetScale) {
    const s = targetScale || Math.max(this.scale, 2.4);
    this.animateTo(s, this.cw / 2 - S.X[i] * s, this.ch * 0.38 - S.Y[i] * s, true);
  },

  animateTo(s, tx, ty, animated) {
    if (!animated) { this.scale = s; this.tx = tx; this.ty = ty; this.request(); return; }
    const s0 = this.scale, x0 = this.tx, y0 = this.ty, t0 = performance.now(), dur = 360;
    this.moving = true;
    const step = (t) => {
      const k = clamp((t - t0) / dur, 0, 1);
      const e = 1 - Math.pow(1 - k, 3);
      this.scale = s0 + (s - s0) * e; this.tx = x0 + (tx - x0) * e; this.ty = y0 + (ty - y0) * e;
      this.draw();
      if (k < 1) requestAnimationFrame(step); else { this.moving = false; this.settle(); }
    };
    requestAnimationFrame(step);
  },

  request() {
    if (this.raf) return;
    this.raf = requestAnimationFrame(() => { this.raf = 0; this.draw(); });
  },

  settle() {
    clearTimeout(this.settleTimer);
    this.settleTimer = setTimeout(() => { this.moving = false; this.draw(); }, 130);
  },

  /* --- 底图（低倍率平移时的位图代理） --- */
  renderBase() {
    const b = this.bctx, B = this.BASE, k = this.baseScale;
    b.setTransform(1, 0, 0, 1, 0, 0);
    b.fillStyle = CSSVAR['--canvas-bg']; b.fillRect(0, 0, B, B);
    b.setTransform(k, 0, 0, k, B / 2, B / 2);

    b.lineWidth = edgeWidth(k) / k; b.strokeStyle = CSSVAR['--edge'];
    b.beginPath();
    for (let e = 0; e < S.m; e++) {
      const a = S.ES[e], c = S.ET[e];
      if (!S.vis[a] || !S.vis[c]) continue;
      b.moveTo(S.X[a], S.Y[a]); b.lineTo(S.X[c], S.Y[c]);
    }
    b.stroke();

    for (let r = 0; r < 5; r++) {
      b.fillStyle = CSSVAR[ROLE_KEYS[r]];
      b.beginPath();
      for (let i = 0; i < S.n; i++) {
        if (!S.vis[i] || S.RI[i] !== r) continue;
        const rad = worldRadius(S.G[i], k);
        b.moveTo(S.X[i] + rad, S.Y[i]);
        b.arc(S.X[i], S.Y[i], rad, 0, 6.2832);
      }
      b.fill();
    }
    this.baseOK = true;
  },

  draw() {
    if (S.focus) return this.drawFocus();
    const ctx = this.ctx, dpr = this.dpr;
    ctx.setTransform(1, 0, 0, 1, 0, 0);
    ctx.fillStyle = CSSVAR['--canvas-bg'];
    ctx.fillRect(0, 0, this.W, this.H);

    const useProxy = this.moving && this.scale < this.baseScale * 2.2;
    if (useProxy) {
      if (!this.baseOK) this.renderBase();
      const k = this.scale / this.baseScale;
      const w = this.BASE * k;
      ctx.imageSmoothingEnabled = true;
      ctx.drawImage(this.base, 0, 0, this.BASE, this.BASE,
        (this.tx - GRID_PAD * this.scale) * dpr, (this.ty - GRID_PAD * this.scale) * dpr, w * dpr, w * dpr);
    } else {
      this.drawVector();
    }
    if (S.sel >= 0) this.drawHighlight();
  },

  /* 视口内矢量精绘（含裁剪） */
  drawVector() {
    const ctx = this.ctx, dpr = this.dpr, s = this.scale;
    ctx.setTransform(s * dpr, 0, 0, s * dpr, this.tx * dpr, this.ty * dpr);
    const [wx0, wy0] = this.toWorld(-60, -60);
    const [wx1, wy1] = this.toWorld(this.cw + 60, this.ch + 60);

    // 边
    ctx.lineWidth = edgeWidth(s) / s;
    ctx.strokeStyle = CSSVAR['--edge'];
    ctx.beginPath();
    let drawn = 0;
    for (let e = 0; e < S.m; e++) {
      const a = S.ES[e], c = S.ET[e];
      if (!S.vis[a] || !S.vis[c]) continue;
      const ax = S.X[a], ay = S.Y[a], cx = S.X[c], cy = S.Y[c];
      if ((ax < wx0 && cx < wx0) || (ax > wx1 && cx > wx1) ||
          (ay < wy0 && cy < wy0) || (ay > wy1 && cy > wy1)) continue;
      ctx.moveTo(ax, ay); ctx.lineTo(cx, cy);
      if (++drawn > 60000) break;
    }
    ctx.stroke();

    // 节点（按来源分色批量填充）
    const buckets = [[], [], [], [], []];
    gridQuery(wx0, wy0, wx1, wy1, (i) => { if (S.vis[i]) buckets[S.RI[i]].push(i); });
    for (let r = 0; r < 5; r++) {
      if (!buckets[r].length) continue;
      ctx.fillStyle = CSSVAR[ROLE_KEYS[r]];
      ctx.beginPath();
      for (const i of buckets[r]) {
        const rad = worldRadius(S.G[i], s);
        ctx.moveTo(S.X[i] + rad, S.Y[i]);
        ctx.arc(S.X[i], S.Y[i], rad, 0, 6.2832);
      }
      ctx.fill();
    }

    // 标签
    if (s > 1.15) this.drawLabels(buckets, s);
  },

  /* 标签：按度数优先，用屏幕像素占位网格做去重叠，纸色描边保证可读 */
  drawLabels(buckets, s) {
    const ctx = this.ctx;
    const all = [].concat(buckets[0], buckets[1], buckets[2], buckets[3], buckets[4]);
    if (all.length > 4000) return;
    all.sort((a, b) => S.G[b] - S.G[a]);

    const fs = 12 / s;                       // 屏幕上恒为 12px
    ctx.font = fs + 'px "Noto Serif CJK SC","Songti SC",serif';
    ctx.textBaseline = 'middle';
    ctx.lineJoin = 'round';
    ctx.lineWidth = 3.2 / s;
    ctx.strokeStyle = CSSVAR['--canvas-bg'];

    const CW = 9, CH = 15;                   // 占位格（屏幕像素）
    const occ = new Set();
    const cols = Math.ceil(this.cw / CW) + 4;
    let drawn = 0, scanned = 0;

    for (const i of all) {
      if (++scanned > 2500 || drawn >= 90) break;
      const px = S.X[i] * s + this.tx, py = S.Y[i] * s + this.ty;
      if (px < -30 || py < 8 || px > this.cw + 30 || py > this.ch - 4) continue;

      const label = S.D.nodes[i].l;
      const txt = label.length > 12 ? label.slice(0, 11) + '…' : label;
      const wWorld = ctx.measureText(txt).width;
      const x0 = px + (worldRadius(S.G[i], s) * s) + 3;
      const wPx = wWorld * s;
      if (x0 + wPx > this.cw + 26) continue;

      const row = Math.floor(py / CH);
      const c0 = Math.floor(x0 / CW), c1 = Math.floor((x0 + wPx) / CW);
      let free = true;
      for (let r = row - 1; r <= row + 1 && free; r++) {
        for (let c = c0; c <= c1; c++) { if (occ.has(r * cols + c)) { free = false; break; } }
      }
      if (!free) continue;
      for (let c = c0; c <= c1; c++) occ.add(row * cols + c);

      const wx = S.X[i] + worldRadius(S.G[i], s) + 3 / s;
      ctx.strokeText(txt, wx, S.Y[i]);
      ctx.fillStyle = CSSVAR['--ink'];
      ctx.fillText(txt, wx, S.Y[i]);
      drawn++;
    }
  },

  /* 选中节点：高亮其邻域 */
  drawHighlight() {
    const ctx = this.ctx, dpr = this.dpr, s = this.scale, i = S.sel;
    ctx.setTransform(s * dpr, 0, 0, s * dpr, this.tx * dpr, this.ty * dpr);
    ctx.lineWidth = 1.5 / s;
    ctx.strokeStyle = CSSVAR['--edge-hi'];
    ctx.beginPath();
    const nb = [];
    for (let p = S.adjStart[i]; p < S.adjStart[i + 1]; p++) {
      const e = S.adjList[p], a = S.ES[e], c = S.ET[e];
      if (!S.vis[a] || !S.vis[c]) continue;
      ctx.moveTo(S.X[a], S.Y[a]); ctx.lineTo(S.X[c], S.Y[c]);
      nb.push(a === i ? c : a);
    }
    ctx.stroke();
    for (const j of nb) {
      ctx.beginPath();
      ctx.arc(S.X[j], S.Y[j], worldRadius(S.G[j], s) + 1.6 / s, 0, 6.2832);
      ctx.fillStyle = CSSVAR[ROLE_KEYS[S.RI[j]]]; ctx.fill();
    }
    // 选中环
    const R = worldRadius(S.G[i], s) + 4 / s;
    ctx.beginPath(); ctx.arc(S.X[i], S.Y[i], R, 0, 6.2832);
    ctx.fillStyle = CSSVAR[ROLE_KEYS[S.RI[i]]]; ctx.fill();
    ctx.lineWidth = 2 / s; ctx.strokeStyle = CSSVAR['--paper']; ctx.stroke();
    ctx.beginPath(); ctx.arc(S.X[i], S.Y[i], R + 3.5 / s, 0, 6.2832);
    ctx.lineWidth = 1.2 / s; ctx.strokeStyle = CSSVAR['--cinnabar']; ctx.stroke();
  },

  /* --- 聚焦（自我中心网络） --- */
  drawFocus() {
    const ctx = this.ctx, dpr = this.dpr, F = S.focus;
    ctx.setTransform(1, 0, 0, 1, 0, 0);
    ctx.fillStyle = CSSVAR['--canvas-bg']; ctx.fillRect(0, 0, this.W, this.H);
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);

    const cx = this.cw / 2, cy = F.cy;
    // 同心椭圆环（ctx.ellipse 在很旧的 WebView 上缺失，退化为缩放圆）
    ctx.strokeStyle = CSSVAR['--line-2']; ctx.lineWidth = 0.7;
    const hasEllipse = typeof ctx.ellipse === 'function';
    for (const r of F.rings) {
      ctx.beginPath();
      if (hasEllipse) {
        ctx.ellipse(cx, cy, r.rx, r.ry, 0, 0, 6.2832);
        ctx.stroke();
      } else {
        ctx.save(); ctx.translate(cx, cy); ctx.scale(1, r.ry / r.rx);
        ctx.arc(0, 0, r.rx, 0, 6.2832); ctx.restore(); ctx.stroke();
      }
    }

    // 连线
    ctx.strokeStyle = CSSVAR['--edge-hi']; ctx.lineWidth = 1;
    ctx.beginPath();
    for (const it of F.items) { ctx.moveTo(cx, cy); ctx.lineTo(cx + it.px, cy + it.py); }
    ctx.stroke();

    // 邻居：先画圆点，再放标签（带占位检测，重叠则让位）
    ctx.textBaseline = 'middle';
    ctx.textAlign = 'left';
    for (const it of F.items) {
      const x = cx + it.px, y = cy + it.py;
      ctx.beginPath(); ctx.arc(x, y, it.r, 0, 6.2832);
      ctx.fillStyle = CSSVAR[ROLE_KEYS[S.RI[it.i]]]; ctx.fill();
    }
    // 中心名先占位，邻居标签一律为它让路
    const cLabel = S.D.nodes[F.center].l;
    const cTxt = cLabel.length > 16 ? cLabel.slice(0, 15) + '…' : cLabel;
    ctx.font = '600 14px "Noto Serif CJK SC","Songti SC",serif';
    const cW = ctx.measureText(cTxt).width;
    const boxes = [{ x0: cx - cW / 2 - 4, y0: cy - 42, x1: cx + cW / 2 + 4, y1: cy - 20 }];

    ctx.font = '11px "Noto Serif CJK SC","Songti SC",serif';
    ctx.lineJoin = 'round'; ctx.lineWidth = 3;
    for (const it of F.items) {
      const x = cx + it.px, y = cy + it.py;
      const lab = S.D.nodes[it.i].l;
      const txt = lab.length > 9 ? lab.slice(0, 8) + '…' : lab;
      const w = ctx.measureText(txt).width;
      let lx = it.px >= 0 ? x + it.r + 4 : x - it.r - 4 - w;
      lx = clamp(lx, 3, this.cw - w - 3);
      const bx = { x0: lx - 1, y0: y - 7, x1: lx + w + 1, y1: y + 7 };
      let hit = false;
      for (const o of boxes) {
        if (bx.x0 < o.x1 && bx.x1 > o.x0 && bx.y0 < o.y1 && bx.y1 > o.y0) { hit = true; break; }
      }
      if (hit) continue;
      boxes.push(bx);
      ctx.strokeStyle = CSSVAR['--canvas-bg']; ctx.strokeText(txt, lx, y);
      ctx.fillStyle = CSSVAR['--ink']; ctx.fillText(txt, lx, y);
    }

    // 中心节点
    const c = F.center;
    ctx.beginPath(); ctx.arc(cx, cy, 15, 0, 6.2832);
    ctx.fillStyle = CSSVAR[ROLE_KEYS[S.RI[c]]]; ctx.fill();
    ctx.lineWidth = 2.4; ctx.strokeStyle = CSSVAR['--paper']; ctx.stroke();
    ctx.beginPath(); ctx.arc(cx, cy, 19, 0, 6.2832);
    ctx.lineWidth = 1; ctx.strokeStyle = CSSVAR['--cinnabar']; ctx.stroke();

    ctx.font = '600 14px "Noto Serif CJK SC","Songti SC",serif';
    ctx.textAlign = 'center'; ctx.lineWidth = 3.4;
    ctx.strokeStyle = CSSVAR['--canvas-bg']; ctx.strokeText(cTxt, cx, cy - 30);
    ctx.fillStyle = CSSVAR['--ink']; ctx.fillText(cTxt, cx, cy - 30);
    ctx.textAlign = 'left';
  },

  /* --- 命中测试 --- */
  hit(px, py) {
    if (S.focus) {
      const cx = this.cw / 2, cy = S.focus.cy;
      if (Math.hypot(px - cx, py - cy) < 22) return S.focus.center;
      let best = -1, bd = 26 * 26;
      for (const it of S.focus.items) {
        const ddx = px - cx - it.px, ddy = py - cy - it.py; const d = ddx * ddx + ddy * ddy;
        if (d < bd) { bd = d; best = it.i; }
      }
      return best;
    }
    const [wx, wy] = this.toWorld(px, py);
    const tol = 18 / this.scale;              // 指尖容差固定为 18 屏幕像素
    let best = -1, bd = Infinity;
    gridQuery(wx - tol, wy - tol, wx + tol, wy + tol, (i) => {
      if (!S.vis[i]) return;
      const ddx = S.X[i] - wx, ddy = S.Y[i] - wy; const d = ddx * ddx + ddy * ddy;
      const r = Math.max(worldRadius(S.G[i], this.scale), tol * 0.6);
      if (d < r * r && d < bd) { bd = d; best = i; }
    });
    return best;
  },

  /* --- 触摸手势 --- */
  bindTouch() {
    const cv = this.cv;
    let mode = 0;               // 0 idle, 1 pan, 2 pinch
    let sx = 0, sy = 0, lx = 0, ly = 0, moved = 0, t0 = 0;
    let pd0 = 0, ps0 = 1, pmx = 0, pmy = 0, ptx = 0, pty = 0;
    let lastTap = 0, lastTapX = 0, lastTapY = 0;

    const pt = (e, i) => { const r = cv.getBoundingClientRect(); const t = e.touches[i];
      return [t.clientX - r.left, t.clientY - r.top]; };

    cv.addEventListener('touchstart', (e) => {
      if (e.touches.length === 1) {
        mode = 1; [sx, sy] = pt(e, 0); lx = sx; ly = sy; moved = 0; t0 = performance.now();
      } else if (e.touches.length >= 2) {
        mode = 2;
        const [ax, ay] = pt(e, 0), [bx, by] = pt(e, 1);
        pd0 = Math.hypot(bx - ax, by - ay) || 1;
        pmx = (ax + bx) / 2; pmy = (ay + by) / 2;
        ps0 = this.scale; ptx = this.tx; pty = this.ty;
      }
      this.moving = true;
    }, { passive: true });

    cv.addEventListener('touchmove', (e) => {
      e.preventDefault();
      if (mode === 1 && e.touches.length === 1) {
        const [x, y] = pt(e, 0);
        this.tx += x - lx; this.ty += y - ly;
        moved += Math.abs(x - lx) + Math.abs(y - ly);
        lx = x; ly = y;
        if (!S.focus) this.request();
      } else if (mode === 2 && e.touches.length >= 2) {
        const [ax, ay] = pt(e, 0), [bx, by] = pt(e, 1);
        const d = Math.hypot(bx - ax, by - ay) || 1;
        const mx = (ax + bx) / 2, my = (ay + by) / 2;
        const f = clamp((d / pd0), 0.05, 20);
        const ns = clamp(ps0 * f, 0.03, 60);
        const k = ns / ps0;
        // 以初始中点为不动点，并跟随中点平移
        this.scale = ns;
        this.tx = mx - (pmx - ptx) * k;
        this.ty = my - (pmy - pty) * k;
        moved += 12;
        if (!S.focus) this.request();
      }
    }, { passive: false });

    const end = (e) => {
      if (e.touches.length === 0) {
        const wasMode = mode; mode = 0;
        this.settle();
        if (wasMode === 1 && moved < 12 && performance.now() - t0 < 420) {
          const now = performance.now();
          const isDouble = now - lastTap < 300 && Math.hypot(sx - lastTapX, sy - lastTapY) < 40;
          lastTap = now; lastTapX = sx; lastTapY = sy;
          if (isDouble && !S.focus) {
            const ns = clamp(this.scale * 2.1, 0.03, 60);
            const k = ns / this.scale;
            this.animateTo(ns, sx - (sx - this.tx) * k, sy - (sy - this.ty) * k, true);
            return;
          }
          const i = this.hit(sx, sy);
          if (i >= 0) selectNode(i, true);
          else if (!S.focus) { S.sel = -1; closeSheet(); this.request(); }
        }
      } else if (e.touches.length === 1) {
        mode = 1; [sx, sy] = pt(e, 0); lx = sx; ly = sy; moved = 99;
      }
    };
    cv.addEventListener('touchend', end, { passive: true });
    cv.addEventListener('touchcancel', end, { passive: true });

    // 桌面/调试
    let md = false;
    cv.addEventListener('mousedown', (ev) => { md = true; lx = ev.offsetX; ly = ev.offsetY; sx = lx; sy = ly; moved = 0; this.moving = true; });
    window.addEventListener('mouseup', (ev) => {
      if (!md) return; md = false; this.settle();
      if (moved < 6) { const i = this.hit(sx, sy); if (i >= 0) selectNode(i, true); else if (!S.focus) { S.sel = -1; closeSheet(); this.request(); } }
    });
    cv.addEventListener('mousemove', (ev) => {
      if (!md) return;
      this.tx += ev.offsetX - lx; this.ty += ev.offsetY - ly;
      moved += Math.abs(ev.offsetX - lx) + Math.abs(ev.offsetY - ly);
      lx = ev.offsetX; ly = ev.offsetY; if (!S.focus) this.request();
    });
    cv.addEventListener('wheel', (ev) => {
      ev.preventDefault();
      const f = ev.deltaY < 0 ? 1.14 : 1 / 1.14;
      const ns = clamp(this.scale * f, 0.03, 60), k = ns / this.scale;
      this.tx = ev.offsetX - (ev.offsetX - this.tx) * k;
      this.ty = ev.offsetY - (ev.offsetY - this.ty) * k;
      this.scale = ns; this.moving = true; this.request(); this.settle();
    }, { passive: false });
  },
};

/* 节点半径以「世界单位」定义，随缩放一起变大变小；
   再把屏幕上的实际直径夹在可读范围内，避免整图缩略时糊成一团、放大时又过分臃肿。 */
function nodeRadius(deg) { return 1.7 + Math.min(Math.sqrt(deg) * 1.15, 8.5); }
function worldRadius(deg, s) {
  const w = nodeRadius(deg);
  const px = w * s;
  if (px < 0.42) return 0.42 / s;
  if (px > 8.5) return 8.5 / s;
  return w;
}
/* 连线宽度（屏幕像素）：缩略时极细，放大时不超过 1.3px */
function edgeWidth(s) { return clamp(1.1 * Math.sqrt(s), 0.2, 1.05); }

/* =========================================================================
   4. 聚焦模式
   ========================================================================= */
function enterFocus(i) {
  const seen = new Set();
  const items = [];
  for (let p = S.adjStart[i]; p < S.adjStart[i + 1]; p++) {
    const e = S.adjList[p];
    const j = S.ES[e] === i ? S.ET[e] : S.ES[e];
    if (j === i || seen.has(j) || !S.vis[j]) continue;
    seen.add(j); items.push({ i: j, e });
  }
  items.sort((a, b) => S.G[b.i] - S.G[a.i]);
  const cap = items.slice(0, 60);

  // 可用画布：上方让开搜索条与聚焦条，四周留出标签余量。
  // 横竖屏都由这里推导，旋转后重新进入本函数即可自适应。
  const TOP = 118, BOT = 14, SIDE = 20, LABEL_PAD = 20;
  const cy = (TOP + (GR.ch - BOT)) / 2;
  let RX = Math.min(GR.cw * 0.34, (GR.cw - SIDE * 2) / 2);
  let RY = Math.max(46, (GR.ch - BOT - TOP) / 2 - LABEL_PAD);
  RY = Math.min(RY, RX * 1.9);                 // 不让竖屏拉得过于瘦长
  const rings = [];
  const per = 13;
  const nRings = Math.max(1, Math.ceil(cap.length / per));
  for (let r = 0; r < nRings; r++) rings.push(0.44 + 0.56 * (nRings === 1 ? 1 : r / (nRings - 1)));
  cap.forEach((it, k) => {
    const ring = k % nRings;
    const inRing = Math.ceil((cap.length - ring) / nRings);
    const pos = Math.floor(k / nRings);
    const a = (pos / inRing) * Math.PI * 2 - Math.PI / 2 + ring * 0.24;
    const f = rings[ring];
    it.px = Math.cos(a) * RX * f; it.py = Math.sin(a) * RY * f;
    it.r = clamp(3 + Math.sqrt(S.G[it.i]) * 0.9, 3.5, 10);
  });
  const ell = rings.map(f => ({ rx: RX * f, ry: RY * f }));
  const cyFocus = cy;
  S.focus = { center: i, items: cap, rings: ell, cy: cyFocus, total: items.length };
  const nd = S.D.nodes[i];
  $('#gfocus-name').textContent = nd.l.length > 12 ? nd.l.slice(0, 11) + '…' : nd.l;
  $('#gfocus-meta').textContent = (S.typeLbl[nd.t] || nd.t) + ' · 邻接 ' +
    items.length + (items.length > cap.length ? '（示度数最高 ' + cap.length + ' 个）' : '');
  document.body.classList.add('focusing');
  GR.request();
}
function exitFocus() {
  S.focus = null;
  document.body.classList.remove('focusing');
  GR.invalidateBase(); GR.request();
}

/* =========================================================================
   5. 详情抽屉
   ========================================================================= */
const REL_CAP = 6;

function selectNode(i, openSheetFlag) {
  S.sel = i;
  if (S.focus && S.focus.center !== i) { /* 聚焦模式下点邻居：先看详情 */ }
  GR.request();
  if (openSheetFlag !== false) openSheet(i);
}

function openSheet(i, pushHist) {
  const nd = S.D.nodes[i];
  if (pushHist !== false && S.hist[S.hist.length - 1] !== i) S.hist.push(i);
  S.sel = i;

  const roleColor = CSSVAR[ROLE_KEYS[S.RI[i]]];
  const head = $('#sheet-head');
  head.innerHTML =
    '<div class="sh-t">' + esc(nd.l) + '</div>' +
    (nd.e ? '<div class="sh-en">' + esc(nd.e) + '</div>' : '') +
    '<div style="margin-top:9px">' +
      '<span class="tag">' + esc(S.typeLbl[nd.t] || nd.t) + '</span>' +
      '<span class="tag role solid" style="background:' + roleColor + '">' + esc(S.roleLbl[nd.r] || nd.r) + '</span>' +
      '<span class="tag">关联 ' + fmt(nd.g) + '</span>' +
      (nd.d && nd.d.length > 1 ? '<span class="tag" style="color:var(--bamboo);border-color:var(--bamboo)">跨文献佐证</span>' : '') +
    '</div>' +
    '<div class="sh-acts">' +
      '<button id="sh-focus" class="hi">聚 焦</button>' +
      '<button id="sh-locate">图中定位</button>' +
      (S.hist.length > 1 ? '<button id="sh-back">返 回</button>' : '') +
    '</div>';

  const body = $('#sheet-body');
  let h = '';

  if (nd.a && nd.a.length) {
    h += '<div class="kv"><b>异名</b><span>' + nd.a.map(esc).join(' · ') + '</span></div>';
  }
  if (nd.d && nd.d.length) {
    h += '<div class="kv"><b>出处</b><span>' +
      nd.d.map(d => esc(d) + '《' + esc(String(S.D.docs[d] || '')) + '》').join('；') + '</span></div>';
  }
  h += '<div class="kv"><b>本体类</b><span style="font-size:11px;color:var(--ink-4)">' + esc(nd.t) + ' · ' + esc(nd.r) + '</span></div>';

  // 关系按类型分组
  const groups = new Map();
  for (let p = S.adjStart[i]; p < S.adjStart[i + 1]; p++) {
    const k = S.adjList[p], e = S.D.edges[k];
    const out = e.s === i;
    const other = out ? e.t : e.s;
    if (!S.vis[other]) continue;
    const key = e.y + (out ? '>' : '<');
    let g = groups.get(key);
    if (!g) { g = { y: e.y, out, list: [] }; groups.set(key, g); }
    g.list.push({ e, other });
  }
  const gs = Array.from(groups.values()).sort((a, b) => b.list.length - a.list.length);

  if (!gs.length) {
    h += '<div class="empty" style="padding:24px 0">当前筛选下无可见关系</div>';
  }
  gs.forEach((g, gi) => {
    h += '<div class="rel-group" data-g="' + gi + '">' +
      '<div class="rel-h">' + (g.out ? '→ ' : '← ') + esc(S.relLbl[g.y] || g.y) +
      '<small>' + esc(g.y) + '</small><em>' + g.list.length + '</em></div>' +
      '<div class="rel-list">' + g.list.slice(0, REL_CAP).map(x => relItem(x, i)).join('') + '</div>' +
      (g.list.length > REL_CAP
        ? '<button class="chip" style="margin-top:7px" data-more="' + gi + '">展开其余 ' + (g.list.length - REL_CAP) + ' 条</button>'
        : '') +
      '</div>';
  });
  body.innerHTML = h;
  body.scrollTop = 0;

  // 展开更多
  $$('[data-more]', body).forEach(btn => btn.onclick = () => {
    const gi = +btn.dataset.more, g = gs[gi];
    const holder = $('[data-g="' + gi + '"] .rel-list', body);
    holder.innerHTML = g.list.map(x => relItem(x, i)).join('');
    btn.remove();
    bindRelTaps(body);
  });
  bindRelTaps(body);

  $('#sh-focus').onclick = () => { closeSheet(); go('graph'); enterFocus(i); };
  $('#sh-locate').onclick = () => { closeSheet(); go('graph'); if (S.focus) exitFocus(); GR.centerOn(i, Math.max(GR.scale, 3.2)); };
  const bk = $('#sh-back');
  if (bk) bk.onclick = () => { S.hist.pop(); const prev = S.hist[S.hist.length - 1]; if (prev != null) openSheet(prev, false); };

  $('#sheet').classList.add('on');
}

function relItem(x, self) {
  const e = x.e, o = S.D.nodes[x.other];
  let h = '<div class="rel-i" data-node="' + x.other + '">' +
    '<div class="nm"><span class="dir">' + (e.s === self ? '→' : '←') + '</span>' + esc(o.l) + '</div>' +
    '<div class="mt">' + esc(S.typeLbl[o.t] || o.t) +
      (e.Q ? ' · <span style="color:var(--gamboge)">⚑ 待审</span>' : '') + '</div>';
  if (e.q) {
    h += '<div class="quote">「' + esc(e.q) + '」' +
      '<span class="src">' + esc(e.d ? e.d + '《' + (S.D.docs[e.d] || '') + '》' : '') +
      (e.c ? ' · ' + esc(e.c) : '') +
      ' · ' + esc((S.D.roles[e.r] || {}).zh || e.r) + '</span></div>';
  }
  return h + '</div>';
}

function bindRelTaps(root) {
  $$('.rel-i[data-node]', root).forEach(el => {
    el.onclick = () => openSheet(+el.dataset.node);
  });
}

function closeSheet() { $('#sheet').classList.remove('on'); }

/* 抽屉下拉关闭 */
function bindSheetDrag() {
  const sh = $('#sheet'), grip = $('.grip', sh);
  let y0 = 0, dy = 0, on = false;
  const start = (y) => { y0 = y; dy = 0; on = true; sh.style.transition = 'none'; };
  const move = (y) => { if (!on) return; dy = Math.max(0, y - y0); sh.style.transform = 'translateY(' + dy + 'px)'; };
  const end = () => {
    if (!on) return; on = false; sh.style.transition = '';
    sh.style.transform = '';
    if (dy > 70) closeSheet();
  };
  grip.addEventListener('touchstart', e => start(e.touches[0].clientY), { passive: true });
  grip.addEventListener('touchmove', e => { e.preventDefault(); move(e.touches[0].clientY); }, { passive: false });
  grip.addEventListener('touchend', end, { passive: true });
  grip.addEventListener('click', () => { if (dy < 6) closeSheet(); });
}

/* =========================================================================
   6. 检索
   ========================================================================= */
let qTypeFilter = null, qTimer = null;

function initSearch() {
  const box = $('#q-types');
  const mk = (key, label, color) => {
    const b = document.createElement('button');
    b.className = 'chip' + (qTypeFilter === key ? ' on' : '');
    b.innerHTML = (color ? '<i style="background:' + color + '"></i>' : '') + esc(label);
    b.onclick = () => { qTypeFilter = (qTypeFilter === key) ? null : key; initSearch(); runSearch(); };
    return b;
  };
  box.innerHTML = '';
  box.appendChild(mk(null, '全部'));
  ROLE_KEYS.forEach(r => box.appendChild(mk('r:' + r, S.roleLbl[r], CSSVAR[r])));
  S.typeKeys
    .slice().sort((a, b) => (S.typeCount[b] || 0) - (S.typeCount[a] || 0))
    .forEach(t => box.appendChild(mk('t:' + t, S.typeLbl[t] + ' ' + (S.typeCount[t] || 0))));

  const inp = $('#q');
  inp.oninput = () => {
    $('#q-clear').style.display = inp.value ? 'block' : 'none';
    clearTimeout(qTimer); qTimer = setTimeout(runSearch, 130);
  };
  $('#q-clear').onclick = () => { inp.value = ''; inp.focus(); $('#q-clear').style.display = 'none'; runSearch(); };
  runSearch();
}

function runSearch() {
  const raw = $('#q').value.trim();
  const v = raw.toLowerCase();
  const out = $('#q-res');
  const N = S.D.nodes;
  const hits = [];

  const roleF = qTypeFilter && qTypeFilter.startsWith('r:') ? qTypeFilter.slice(2) : null;
  const typeF = qTypeFilter && qTypeFilter.startsWith('t:') ? qTypeFilter.slice(2) : null;

  if (!v && !qTypeFilter) {
    // 空态：给出度数最高的入口
    const top = [];
    for (let i = 0; i < S.n; i++) top.push(i);
    top.sort((a, b) => S.G[b] - S.G[a]);
    out.innerHTML = '<div style="padding:14px 16px 4px;font-size:11px;color:var(--ink-4);letter-spacing:.14em">网 络 枢 纽 · HUBS</div>' +
      top.slice(0, 40).map(i => hitRow(i, '')).join('');
    bindHits(out);
    return;
  }

  for (let i = 0; i < S.n; i++) {
    const nd = N[i];
    if (roleF && nd.r !== roleF) continue;
    if (typeF && nd.t !== typeF) continue;
    if (v) {
      let ok = nd.l.toLowerCase().indexOf(v) >= 0;
      if (!ok && nd.e) ok = String(nd.e).toLowerCase().indexOf(v) >= 0;
      if (!ok && nd.a) { for (const a of nd.a) if (String(a).toLowerCase().indexOf(v) >= 0) { ok = true; break; } }
      if (!ok) continue;
    }
    hits.push(i);
    if (hits.length > 4000) break;
  }
  hits.sort((a, b) => {
    if (v) {
      const pa = N[a].l.toLowerCase().indexOf(v), pb = N[b].l.toLowerCase().indexOf(v);
      const ea = pa === 0 ? 0 : pa < 0 ? 2 : 1, eb = pb === 0 ? 0 : pb < 0 ? 2 : 1;
      if (ea !== eb) return ea - eb;
    }
    return S.G[b] - S.G[a];
  });

  if (!hits.length) { out.innerHTML = '<div class="empty">无 相 应 记 载</div>'; return; }
  out.innerHTML =
    '<div style="padding:12px 16px 2px;font-size:11px;color:var(--ink-4);letter-spacing:.1em">' +
    '共 ' + fmt(hits.length) + ' 条' + (hits.length > 120 ? '，示前 120 条' : '') + '</div>' +
    hits.slice(0, 120).map(i => hitRow(i, raw)).join('');
  bindHits(out);
}

function hl(text, q) {
  if (!q) return esc(text);
  const i = text.toLowerCase().indexOf(q.toLowerCase());
  if (i < 0) return esc(text);
  return esc(text.slice(0, i)) + '<mark>' + esc(text.slice(i, i + q.length)) + '</mark>' + esc(text.slice(i + q.length));
}

function hitRow(i, q) {
  const nd = S.D.nodes[i];
  return '<div class="hit" data-node="' + i + '">' +
    '<div class="bar" style="background:' + CSSVAR[ROLE_KEYS[S.RI[i]]] + '"></div>' +
    '<div class="tx">' +
      '<div class="l">' + hl(nd.l, q) + '</div>' +
      (nd.e ? '<div class="e">' + hl(String(nd.e), q) + '</div>' : '') +
      '<div class="m">' + esc(S.typeLbl[nd.t] || nd.t) + ' · ' + esc(S.roleLbl[nd.r] || nd.r) +
        ' · 关联 ' + nd.g + (nd.d && nd.d.length ? ' · ' + nd.d.join('/') : '') + '</div>' +
    '</div></div>';
}

function bindHits(root) {
  $$('.hit[data-node]', root).forEach(el => {
    el.onclick = () => { const i = +el.dataset.node; S.hist = []; openSheet(i); };
  });
}

/* =========================================================================
   7. 典籍
   ========================================================================= */
function initLibrary() {
  const CN = ['一', '二', '三', '四', '五', '六', '七', '八', '九', '十'];
  $('#lib-docs').innerHTML = Object.keys(S.D.docs).map((d, k) =>
    '<div class="doc" data-doc="' + d + '">' +
      '<div class="no">其' + (CN[k] || (k + 1)) + '</div>' +
      '<div class="t"><b>《' + esc(S.D.docs[d]) + '》</b><small>' + esc(d) + '</small></div>' +
      '<div class="n">' + fmt(S.docCount[d] || 0) + '<br><span style="font-size:9px;color:var(--ink-4)">实体</span></div>' +
    '</div>').join('');
  $$('#lib-docs .doc').forEach(el => el.onclick = () => {
    const d = el.dataset.doc;
    Object.keys(S.docOn).forEach(k => S.docOn[k] = (k === d));
    ROLE_KEYS.forEach(r => S.roleOn[r] = true);
    S.typeKeys.forEach(t => S.typeOn[t] = true);
    refilter(); syncFilterUI();
    go('graph'); if (S.focus) exitFocus();
    setTimeout(() => GR.fit(true), 60);
    toast('已单看《' + S.D.docs[d] + '》');
  });

  $('#lib-types').innerHTML = S.typeKeys
    .slice().sort((a, b) => (S.typeCount[b] || 0) - (S.typeCount[a] || 0))
    .map(t => '<div class="gcell" data-type="' + esc(t) + '"><span><b>' + esc(S.typeLbl[t]) +
      '</b><br><small>' + esc(t) + '</small></span><u>' + fmt(S.typeCount[t] || 0) + '</u></div>').join('');
  $$('#lib-types .gcell').forEach(el => el.onclick = () => {
    qTypeFilter = 't:' + el.dataset.type;
    go('search'); initSearch(); runSearch();
  });

  $('#lib-rels').innerHTML = '<div style="font-size:10.5px;color:var(--ink-4);margin-bottom:6px">' +
    '本体 v1.2.3 · 共 ' + Object.keys(S.D.rels).length + ' 类关系</div>' +
    Object.keys(S.D.rels).map(k => {
      const v = S.D.rels[k];
      return '<div class="o"><b>' + esc(v.zh) + '</b><small>' + esc(k) + '</small></div>';
    }).join('');
}

/* =========================================================================
   8. 筛选浮层
   ========================================================================= */
function initFilters() {
  const mkChip = (color, label, count, on, cb) => {
    const b = document.createElement('button');
    b.className = 'chip' + (on ? '' : ' off');
    b.innerHTML = (color ? '<i style="background:' + color + '"></i>' : '') +
      esc(label) + (count != null ? ' <span style="opacity:.62">' + count + '</span>' : '');
    b.onclick = () => { const nv = cb(); b.className = 'chip' + (nv ? '' : ' off'); refilter(); GR.request(); };
    return b;
  };
  const rb = $('#f-roles'); rb.innerHTML = '';
  ROLE_KEYS.forEach(r => rb.appendChild(mkChip(CSSVAR[r], S.roleLbl[r], S.roleCount[r] || 0, S.roleOn[r],
    () => (S.roleOn[r] = !S.roleOn[r]))));
  const db = $('#f-docs'); db.innerHTML = '';
  Object.keys(S.D.docs).forEach(d => db.appendChild(mkChip(null, d + ' 《' + String(S.D.docs[d]).slice(0, 9) + '》',
    S.docCount[d] || 0, S.docOn[d], () => (S.docOn[d] = !S.docOn[d]))));
  const tb = $('#f-types'); tb.innerHTML = '';
  S.typeKeys.slice().sort((a, b) => (S.typeCount[b] || 0) - (S.typeCount[a] || 0))
    .forEach(t => tb.appendChild(mkChip(null, S.typeLbl[t], S.typeCount[t] || 0, S.typeOn[t],
      () => (S.typeOn[t] = !S.typeOn[t]))));

  $$('[data-all]').forEach(el => el.onclick = () => {
    const g = el.dataset.all;
    if (g === 'role') ROLE_KEYS.forEach(r => S.roleOn[r] = true);
    if (g === 'doc') Object.keys(S.docOn).forEach(d => S.docOn[d] = true);
    if (g === 'type') S.typeKeys.forEach(t => S.typeOn[t] = true);
    refilter(); syncFilterUI(); GR.request();
  });
  $('#f-reset').onclick = () => {
    ROLE_KEYS.forEach(r => S.roleOn[r] = true);
    Object.keys(S.docOn).forEach(d => S.docOn[d] = true);
    S.typeKeys.forEach(t => S.typeOn[t] = true);
    refilter(); syncFilterUI(); GR.request(); toast('已重置筛选');
  };
}
function syncFilterUI() { initFilters(); }

/* =========================================================================
   9. 导航
   ========================================================================= */
const VIEWS = { home: '#v-home', graph: '#v-graph', search: '#v-search', lib: '#v-lib', about: '#v-about' };

function go(v) {
  if (!VIEWS[v]) return;
  S.view = v;
  Object.keys(VIEWS).forEach(k => $(VIEWS[k]).classList.toggle('on', k === v));
  $$('#nav .tab').forEach(t => t.classList.toggle('on', t.dataset.go === v));
  if (v === 'graph') { GR.resize(); GR.request(); }
  if (v === 'search') setTimeout(() => { if (!$('#q-res').children.length) runSearch(); }, 0);
}

function closeOverlays() {
  let closed = false;
  $$('.overlay.on').forEach(o => { o.classList.remove('on'); closed = true; });
  return closed;
}

/* Android 返回键 */
window.__appBack = function () {
  if (closeOverlays()) return true;
  if ($('#sheet').classList.contains('on')) { closeSheet(); return true; }
  if (S.focus) { exitFocus(); return true; }
  if (S.view !== 'home') { go('home'); return true; }
  return false;
};

/* =========================================================================
   10. 主题
   ========================================================================= */
function setTheme(t) {
  document.documentElement.setAttribute('data-theme', t);
  try { localStorage.setItem('sgr-theme', t); } catch (e) {}
  readTheme();
  if (S.D) { GR.invalidateBase(); GR.request(); renderRoleLegend(); initSearch(); }
  if (window.NativeApp && NativeApp.setTheme) { try { NativeApp.setTheme(t); } catch (e) {} }
}

function renderRoleLegend() {
  const rows = ROLE_KEYS.map(r =>
    '<div><i style="background:' + CSSVAR[r] + '"></i>' + esc(S.roleLbl[r] || r) + '</div>').join('');
  $('#glegend').innerHTML = rows;
  $('#home-roles').innerHTML = ROLE_KEYS.map(r =>
    '<div style="display:flex;align-items:center;gap:9px;padding:5px 0;font-size:12.5px">' +
      '<i style="width:9px;height:9px;border-radius:50%;background:' + CSSVAR[r] + ';flex:none"></i>' +
      '<b style="font-family:var(--f-serif);font-weight:500">' + esc(S.roleLbl[r]) + '</b>' +
      '<span style="margin-left:auto;color:var(--ink-4);font-size:11px">' + fmt(S.roleCount[r] || 0) + '</span>' +
    '</div>').join('');
  $('#about-roles').innerHTML = ROLE_KEYS.map(r =>
    '<div style="padding:7px 0;border-bottom:1px solid var(--line)">' +
      '<div style="display:flex;align-items:center;gap:8px">' +
      '<i style="width:9px;height:9px;border-radius:50%;background:' + CSSVAR[r] + ';flex:none"></i>' +
      '<b style="font-family:var(--f-serif);font-size:13.5px;font-weight:500">' + esc(S.roleLbl[r]) + '</b></div>' +
      '<div style="font-size:11px;color:var(--ink-4);margin-left:17px">' + esc((S.D.roles[r] || {}).en || '') + '</div>' +
    '</div>').join('');
}

/* =========================================================================
   11. 启动
   ========================================================================= */
function bindUI() {
  $$('[data-go]').forEach(el => el.onclick = () => {
    const v = el.dataset.go;
    if (v === 'graph' && S.focus) exitFocus();
    go(v);
  });
  $$('[data-close]').forEach(el => el.onclick = () => $('#' + el.dataset.close).classList.remove('on'));

  $('#g-search').onclick = () => { go('search'); setTimeout(() => $('#q').focus(), 240); };
  $('#g-filter').onclick = () => $('#ov-filter').classList.add('on');
  $('#g-fit').onclick = () => { if (S.focus) exitFocus(); else GR.fit(true); };
  $('#gfocus-exit').onclick = () => exitFocus();
  $('#g-in').onclick = () => { const ns = clamp(GR.scale * 1.7, .03, 60), k = ns / GR.scale;
    GR.animateTo(ns, GR.cw / 2 - (GR.cw / 2 - GR.tx) * k, GR.ch / 2 - (GR.ch / 2 - GR.ty) * k, true); };
  $('#g-out').onclick = () => { const ns = clamp(GR.scale / 1.7, .03, 60), k = ns / GR.scale;
    GR.animateTo(ns, GR.cw / 2 - (GR.cw / 2 - GR.tx) * k, GR.ch / 2 - (GR.ch / 2 - GR.ty) * k, true); };
  $('#g-theme').onclick = () => setTheme(document.documentElement.getAttribute('data-theme') === 'night' ? 'paper' : 'night');

  $('#e-random').onclick = () => {
    let i, guard = 0;
    do { i = Math.floor(Math.random() * S.n); guard++; } while ((!S.vis[i] || S.G[i] < 3) && guard < 400);
    S.hist = []; openSheet(i);
  };

  bindSheetDrag();
}

function boot() {
  // <head> 里的内联脚本已经定好主题，这里只做持久化与系统栏同步
  const cur = document.documentElement.getAttribute('data-theme') === 'night' ? 'night' : 'paper';
  try { localStorage.setItem('sgr-theme', cur); } catch (e) {}
  if (window.NativeApp && NativeApp.setTheme) { try { NativeApp.setTheme(cur); } catch (e) {} }
  readTheme();
  GR.init();
  bindUI();

  loadData().then(D => {
    buildIndexes(D);
    readTheme();

    $('#s-n').textContent = fmt(S.n);
    $('#s-e').textContent = fmt(S.m);
    $('#s-t').textContent = S.typeKeys.length;
    const a = D.meta.audit || {};
    $('#about-audit').innerHTML = '抽样审校精度：v2 <b>' + ((a.v2_strict || 0) * 100).toFixed(1) + '%</b>（n=' +
      (a.v2_n || 0) + '），v1 <b>' + ((a.v1_strict || 0) * 100).toFixed(1) + '%</b>（n=' + (a.v1_n || 0) + '）。' +
      '完整图共 ' + fmt(D.meta.nodes_total || S.n) + ' 节点，已隐藏 ' +
      fmt((D.meta.nodes_total || S.n) - S.n) + ' 个孤立节点。';

    renderRoleLegend();
    refilter();
    initSearch();
    initLibrary();
    initFilters();
    GR.fit(false, 0.93);      // 初次进入：框住中心密集区
    GR.draw();
    $('#loading').style.display = 'none';
    if (window.NativeApp && NativeApp.ready) { try { NativeApp.ready(); } catch (e) {} }
  }).catch(err => {
    $('#load-msg').innerHTML = '图谱数据装载失败<br><span style="font-size:10px">' + esc(String(err && err.message || err)) + '</span>';
    $('.spin').style.display = 'none';
  });
}

if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', boot);
else boot();
