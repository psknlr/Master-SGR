#!/usr/bin/env node
/**
 * 孙光荣中医知识图谱 · 离线布局预计算
 * Offline layout precomputation for the Sun Guangrong TCM knowledge graph.
 *
 * 思路 / Strategy
 *   1. 剥离叶节点(度=1)，只对"核心图"做力导向布局 —— 19343 个节点中有 11298 个是叶子，
 *      先算核心再把叶子以"花瓣"方式挂回锚点，既快又好看。
 *   2. 核心图按连通分量分别布局(ForceAtlas2 + Barnes-Hut 四叉树)，再做圆形装箱。
 *   3. 结果坐标写入 graph.json，App 启动即绘，无需在手机上跑物理迭代。
 */
import fs from 'fs';
import path from 'path';

const ROOT = path.resolve(path.dirname(new URL(import.meta.url).pathname), '..');
const RAW = path.join(ROOT, 'tools/build/raw.json');
const OUT = path.join(ROOT, 'android/app/src/main/assets/web/data/graph.json');

const t0 = Date.now();
const log = (...a) => console.log(`[${((Date.now() - t0) / 1000).toFixed(1)}s]`, ...a);

const D = JSON.parse(fs.readFileSync(RAW, 'utf8'));
const N = D.nodes, E = D.edges, n = N.length;
log(`loaded ${n} nodes / ${E.length} edges`);

/* ------------------------------------------------------------------ */
/* 1. 邻接表与度                                                        */
/* ------------------------------------------------------------------ */
const deg = new Int32Array(n);
for (const e of E) { deg[e.s]++; deg[e.t]++; }

const adjStart = new Int32Array(n + 1);
for (let i = 0; i < n; i++) adjStart[i + 1] = adjStart[i] + deg[i];
const adj = new Int32Array(adjStart[n]);
{
  const cur = adjStart.slice(0, n);
  for (const e of E) { adj[cur[e.s]++] = e.t; adj[cur[e.t]++] = e.s; }
}
const nbrs = (i) => adj.subarray(adjStart[i], adjStart[i + 1]);

/* ------------------------------------------------------------------ */
/* 2. 叶节点剥离：度为 1 且其锚点不是叶子                                */
/* ------------------------------------------------------------------ */
const isLeaf = new Uint8Array(n);
const anchor = new Int32Array(n).fill(-1);
for (let i = 0; i < n; i++) {
  if (deg[i] !== 1) continue;
  const a = adj[adjStart[i]];
  // 孤立的"哑铃"(两个互连的度-1 节点)不剥离，保留一端在核心里
  if (deg[a] === 1 && a > i) continue;
  if (deg[a] === 1 && a < i) { isLeaf[i] = 1; anchor[i] = a; continue; }
  isLeaf[i] = 1; anchor[i] = a;
}
const core = [];
for (let i = 0; i < n; i++) if (!isLeaf[i]) core.push(i);
const coreIdx = new Int32Array(n).fill(-1);
core.forEach((g, k) => { coreIdx[g] = k; });
const cn = core.length;
log(`core ${cn} nodes, leaves ${n - cn}`);

// 核心图的边（两端都在核心里）
const cs = [], ct = [];
for (const e of E) {
  const a = coreIdx[e.s], b = coreIdx[e.t];
  if (a >= 0 && b >= 0 && a !== b) { cs.push(a); ct.push(b); }
}
const CS = Int32Array.from(cs), CT = Int32Array.from(ct);
log(`core edges ${CS.length}`);

// 核心节点的"质量" = 自身度（含被剥离的叶子），用于 FA2 斥力
const mass = new Float64Array(cn);
for (let k = 0; k < cn; k++) mass[k] = deg[core[k]] + 1;

/* ------------------------------------------------------------------ */
/* 3. 连通分量（核心图）                                                */
/* ------------------------------------------------------------------ */
const cAdjDeg = new Int32Array(cn);
for (let i = 0; i < CS.length; i++) { cAdjDeg[CS[i]]++; cAdjDeg[CT[i]]++; }
const cStart = new Int32Array(cn + 1);
for (let i = 0; i < cn; i++) cStart[i + 1] = cStart[i] + cAdjDeg[i];
const cAdj = new Int32Array(cStart[cn]);
{
  const cur = cStart.slice(0, cn);
  for (let i = 0; i < CS.length; i++) { cAdj[cur[CS[i]]++] = CT[i]; cAdj[cur[CT[i]]++] = CS[i]; }
}
const comp = new Int32Array(cn).fill(-1);
const comps = [];
{
  const stack = new Int32Array(cn);
  for (let s = 0; s < cn; s++) {
    if (comp[s] >= 0) continue;
    const id = comps.length, members = [];
    let sp = 0; stack[sp++] = s; comp[s] = id;
    while (sp > 0) {
      const v = stack[--sp]; members.push(v);
      for (let p = cStart[v]; p < cStart[v + 1]; p++) {
        const w = cAdj[p];
        if (comp[w] < 0) { comp[w] = id; stack[sp++] = w; }
      }
    }
    comps.push(members);
  }
}
comps.sort((a, b) => b.length - a.length);
comps.forEach((m, id) => m.forEach(v => { comp[v] = id; }));
log(`components: ${comps.length}, largest ${comps[0].length}, 2nd ${comps[1] ? comps[1].length : 0}`);

/* ------------------------------------------------------------------ */
/* 4. Barnes-Hut 四叉树                                                 */
/* ------------------------------------------------------------------ */
function makeTree(cap) {
  return {
    cap,
    // 每个树节点: 4 个孩子 / 质心 / 质量 / 半宽 / 中心
    ch: new Int32Array(cap * 4),
    cx: new Float64Array(cap), cy: new Float64Array(cap), m: new Float64Array(cap),
    hx: new Float64Array(cap), hy: new Float64Array(cap), hw: new Float64Array(cap),
    body: new Int32Array(cap),
    count: 0,
  };
}

function bhBuild(T, idx, X, Y, M) {
  T.count = 0;
  let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity;
  for (const i of idx) {
    if (X[i] < minX) minX = X[i]; if (X[i] > maxX) maxX = X[i];
    if (Y[i] < minY) minY = Y[i]; if (Y[i] > maxY) maxY = Y[i];
  }
  const w = Math.max(maxX - minX, maxY - minY, 1e-6) * 0.5 + 1;
  const root = alloc(T, (minX + maxX) * 0.5, (minY + maxY) * 0.5, w);
  for (const i of idx) insert(T, root, i, X, Y, M, 0);
  return root;
}
function alloc(T, x, y, w) {
  const i = T.count++;
  if (i >= T.cap) grow(T);
  T.ch[i * 4] = T.ch[i * 4 + 1] = T.ch[i * 4 + 2] = T.ch[i * 4 + 3] = -1;
  T.cx[i] = 0; T.cy[i] = 0; T.m[i] = 0;
  T.hx[i] = x; T.hy[i] = y; T.hw[i] = w; T.body[i] = -1;
  return i;
}
function grow(T) {
  const nc = T.cap * 2;
  const g = (arr, Ctor) => { const a = new Ctor(nc * (Ctor === Int32Array && arr.length === T.cap * 4 ? 4 : 1)); a.set(arr); return a; };
  const ch = new Int32Array(nc * 4); ch.set(T.ch); T.ch = ch;
  for (const k of ['cx', 'cy', 'm', 'hx', 'hy', 'hw']) { const a = new Float64Array(nc); a.set(T[k]); T[k] = a; }
  const b = new Int32Array(nc); b.set(T.body); T.body = b;
  T.cap = nc;
}
function quadOf(T, t, x, y) {
  return (x >= T.hx[t] ? 1 : 0) + (y >= T.hy[t] ? 2 : 0);
}
function insert(T, t, i, X, Y, M, depth) {
  while (true) {
    T.cx[t] += X[i] * M[i]; T.cy[t] += Y[i] * M[i]; T.m[t] += M[i];
    const leafBody = T.body[t];
    const hasKids = T.ch[t * 4] >= 0 || T.ch[t * 4 + 1] >= 0 || T.ch[t * 4 + 2] >= 0 || T.ch[t * 4 + 3] >= 0;
    if (!hasKids && leafBody < 0) { T.body[t] = i; return; }
    if (!hasKids && leafBody >= 0) {
      T.body[t] = -1;
      if (depth > 40) { // 坐标完全重合时兜底，直接挂在同一格
        const q = quadOf(T, t, X[leafBody], Y[leafBody]);
        const c = childOf(T, t, q);
        T.cx[c] += X[leafBody] * M[leafBody]; T.cy[c] += Y[leafBody] * M[leafBody]; T.m[c] += M[leafBody];
        T.body[c] = leafBody;
      } else {
        insert(T, childOf(T, t, quadOf(T, t, X[leafBody], Y[leafBody])), leafBody, X, Y, M, depth + 1);
      }
    }
    t = childOf(T, t, quadOf(T, t, X[i], Y[i]));
    depth++;
    if (depth > 60) { T.cx[t] += X[i] * M[i]; T.cy[t] += Y[i] * M[i]; T.m[t] += M[i]; return; }
  }
}
function childOf(T, t, q) {
  let c = T.ch[t * 4 + q];
  if (c >= 0) return c;
  const hw = T.hw[t] * 0.5;
  const x = T.hx[t] + (q & 1 ? hw : -hw);
  const y = T.hy[t] + (q & 2 ? hw : -hw);
  c = alloc(T, x, y, hw);
  T.ch[t * 4 + q] = c;
  return c;
}

/* ------------------------------------------------------------------ */
/* 5. ForceAtlas2 力导向（每个分量单独跑）                                */
/* ------------------------------------------------------------------ */
const X = new Float64Array(cn), Y = new Float64Array(cn);
const DX = new Float64Array(cn), DY = new Float64Array(cn);

function layoutComponent(members, iters, kr, kg, strongG) {
  const cnt = members.length;
  if (cnt === 1) { X[members[0]] = 0; Y[members[0]] = 0; return 1; }

  // 确定性初始化：环形 + 伪随机抖动
  let seed = 20241101;
  const rnd = () => { seed = (seed * 1664525 + 1013904223) >>> 0; return seed / 4294967296; };
  const R0 = Math.sqrt(cnt) * 12;
  members.forEach((v, i) => {
    const a = (i / cnt) * Math.PI * 2;
    const r = R0 * (0.35 + 0.65 * Math.sqrt(rnd()));
    X[v] = Math.cos(a) * r + (rnd() - 0.5) * 4;
    Y[v] = Math.sin(a) * r + (rnd() - 0.5) * 4;
  });

  // 该分量内部的边
  const es = [], et = [];
  for (let i = 0; i < CS.length; i++) {
    if (comp[CS[i]] === comp[members[0]]) { es.push(CS[i]); et.push(CT[i]); }
  }
  const ES = Int32Array.from(es), ET = Int32Array.from(et);

  const T = makeTree(Math.max(1024, cnt * 4));
  const THETA2 = 1.2 * 1.2;
  let speed = 1.0;

  for (let it = 0; it < iters; it++) {
    DX.fill(0, 0, 0); // no-op, cleared below per member
    for (const v of members) { DX[v] = 0; DY[v] = 0; }

    // --- 斥力 (Barnes-Hut) ---
    const root = bhBuild(T, members, X, Y, mass);
    const stack = new Int32Array(4096);
    for (const v of members) {
      let sp = 0; stack[sp++] = root;
      const vx = X[v], vy = Y[v], vm = mass[v];
      let fx = 0, fy = 0;
      while (sp > 0) {
        const t = stack[--sp];
        if (T.m[t] === 0) continue;
        const tcx = T.cx[t] / T.m[t], tcy = T.cy[t] / T.m[t];
        let dx = vx - tcx, dy = vy - tcy;
        let d2 = dx * dx + dy * dy;
        const bodyIdx = T.body[t];
        const wide = (2 * T.hw[t]) * (2 * T.hw[t]);
        if (bodyIdx >= 0 || wide < THETA2 * d2) {
          if (bodyIdx === v) continue;
          if (d2 < 0.01) { dx = (v % 7) * 0.03 + 0.01; dy = (v % 11) * 0.03 + 0.01; d2 = dx * dx + dy * dy; }
          const f = kr * vm * T.m[t] / d2;      // FA2: /d 后再乘 d/|d| => /d2 * dx
          fx += dx * f; fy += dy * f;
        } else {
          for (let q = 0; q < 4; q++) { const c = T.ch[t * 4 + q]; if (c >= 0 && T.m[c] > 0) stack[sp++] = c; }
        }
      }
      DX[v] += fx; DY[v] += fy;
    }

    // --- 引力（沿边，线性） ---
    for (let i = 0; i < ES.length; i++) {
      const a = ES[i], b = ET[i];
      const dx = X[b] - X[a], dy = Y[b] - Y[a];
      DX[a] += dx; DY[a] += dy; DX[b] -= dx; DY[b] -= dy;
    }

    // --- 重力（拉回中心，防止分量飘散/长出"触须"） ---
    // strongGravity: 力随距离线性增长，能有效收住长链条形成的放射状尖刺
    for (const v of members) {
      const d = Math.hypot(X[v], Y[v]) || 1e-6;
      const g = kg * mass[v] * (strongG ? d / (R0 * 1.6) : 1);
      DX[v] -= X[v] / d * g; DY[v] -= Y[v] / d * g;
    }

    // --- 自适应步长 + 位移限幅 ---
    let swing = 0, trac = 0;
    for (const v of members) {
      const s = Math.hypot(DX[v], DY[v]);
      swing += mass[v] * s; trac += mass[v] * s;
    }
    const jitter = 0.05 * Math.sqrt(cnt);
    const targetSpeed = jitter * trac / (swing + 1e-9);
    speed = Math.min(speed * 1.5, Math.max(speed * 0.5, targetSpeed));
    const cool = 1 - it / iters * 0.75;
    const maxStep = 10 + 90 * cool;
    for (const v of members) {
      let dx = DX[v], dy = DY[v];
      const s = Math.hypot(dx, dy);
      const f = Math.min(speed * cool / (1 + Math.sqrt(speed * s)), maxStep / (s + 1e-9));
      X[v] += dx * f; Y[v] += dy * f;
    }
  }

  // 归心
  let mx = 0, my = 0;
  for (const v of members) { mx += X[v]; my += Y[v]; }
  mx /= cnt; my /= cnt;
  let rad = 1;
  for (const v of members) { X[v] -= mx; Y[v] -= my; rad = Math.max(rad, Math.hypot(X[v], Y[v])); }
  return rad;
}

comps.forEach((members, id) => {
  const c = members.length;
  const iters = c > 5000 ? 1200 : c > 500 ? 500 : c > 30 ? 260 : 120;
  // 主分量用 strongGravity 收住放射状长链；小分量用常规重力保持形态
  layoutComponent(members, iters, 1.0, c > 2000 ? 14.0 : c > 200 ? 3.0 : 1.4, c > 2000);
  if (id < 4) log(`  component #${id} (${c}) laid out`);
});
log('force layout done');

/* 主分量径向压缩：力导向后总有少量长链条甩得很远，把 92 分位以外的
   部分做幂次压缩，核心密集区完全不动，只把"触须"收回来。            */
{
  const mem = comps[0];
  const rs = mem.map(v => Math.hypot(X[v], Y[v])).sort((a, b) => a - b);
  const p = (q) => rs[Math.min(rs.length - 1, Math.floor(rs.length * q))];
  log(`  main radius pct: p50=${p(.5).toFixed(0)} p90=${p(.9).toFixed(0)} p98=${p(.98).toFixed(0)} max=${rs[rs.length - 1].toFixed(0)}`);
  const R0 = p(0.92), EXP = 0.45;
  for (const v of mem) {
    const r = Math.hypot(X[v], Y[v]);
    if (r <= R0 || r < 1e-6) continue;
    const rr = R0 * Math.pow(r / R0, EXP);
    X[v] *= rr / r; Y[v] *= rr / r;
  }
  const rs2 = mem.map(v => Math.hypot(X[v], Y[v]));
  log(`  after squeeze max=${Math.max(...rs2).toFixed(0)}`);
}

/* ------------------------------------------------------------------ */
/* 6. 叶节点回挂：围绕锚点成"花瓣"                                       */
/* ------------------------------------------------------------------ */
const gx = new Float64Array(n), gy = new Float64Array(n);
for (let k = 0; k < cn; k++) { gx[core[k]] = X[k]; gy[core[k]] = Y[k]; }

const leavesOf = new Map();
for (let i = 0; i < n; i++) {
  if (!isLeaf[i]) continue;
  const a = anchor[i];
  let arr = leavesOf.get(a); if (!arr) { arr = []; leavesOf.set(a, arr); }
  arr.push(i);
}
for (const [a, arr] of leavesOf) {
  // 锚点朝向：背离其核心邻居的质心
  let ax = 0, ay = 0, c = 0;
  for (const w of nbrs(a)) { if (!isLeaf[w]) { ax += gx[w] - gx[a]; ay += gy[w] - gy[a]; c++; } }
  let base = c > 0 ? Math.atan2(-ay, -ax) : 0;
  const k = arr.length;
  // 叶子多时铺满整圈，少时只开一个扇面
  const span = k <= 3 ? 1.5 : k <= 10 ? Math.PI * 1.1 : Math.PI * 2;
  const rings = Math.max(1, Math.ceil(k / 26));
  arr.sort((p, q) => (N[p].t < N[q].t ? -1 : N[p].t > N[q].t ? 1 : p - q));
  arr.forEach((leaf, i) => {
    const ring = i % rings;
    const inRing = Math.ceil((k - ring) / rings);
    const pos = Math.floor(i / rings);
    const step = span / Math.max(1, inRing - (span >= Math.PI * 2 ? 0 : 1));
    const th = base + (span >= Math.PI * 2 ? pos * step : -span / 2 + pos * step);
    const r = 16 + ring * 13 + Math.min(k, 60) * 0.28;
    gx[leaf] = gx[a] + Math.cos(th) * r;
    gy[leaf] = gy[a] + Math.sin(th) * r;
  });
}
log('leaves attached');

/* ------------------------------------------------------------------ */
/* 7. 分量装箱：主图居中，其余按同心环紧密排布                            */
/*    半径按"核心+叶子"的实际包围圆计算，避免小分量互相压叠               */
/* ------------------------------------------------------------------ */
{
  // 每个核心节点归属的全部成员（核心 + 其叶子）
  const members = comps.map(() => []);
  for (let k = 0; k < cn; k++) members[comp[k]].push(core[k]);
  for (let i = 0; i < n; i++) if (isLeaf[i]) members[comp[coreIdx[anchor[i]]]].push(i);

  const info = members.map((mem, id) => {
    let mx = 0, my = 0;
    for (const v of mem) { mx += gx[v]; my += gy[v]; }
    mx /= mem.length; my /= mem.length;
    let r = 1;
    for (const v of mem) r = Math.max(r, Math.hypot(gx[v] - mx, gy[v] - my));
    return { id, mem, mx, my, r };
  });

  // 主分量居中
  const main = info[0];
  for (const v of main.mem) { gx[v] -= main.mx; gy[v] -= main.my; }
  const mainR = main.r;

  // 其余按半径降序，填同心环
  const rest = info.slice(1).sort((a, b) => b.r - a.r);
  const GAP = 18;
  let ring = mainR + GAP * 2;
  let i = 0;
  while (i < rest.length) {
    let ang = (i % 2) * 0.5;          // 相邻环错开，观感更自然
    let ringMax = 0;
    const placedThisRing = [];
    while (i < rest.length) {
      const c = rest[i];
      const rr = c.r + GAP;
      const rho = ring + rr;
      const dAng = 2 * Math.asin(Math.min(1, rr / rho));
      if (ang + dAng > Math.PI * 2) break;  // 本环已满
      const th = ang + dAng / 2;
      placedThisRing.push({ c, x: Math.cos(th) * rho, y: Math.sin(th) * rho });
      ringMax = Math.max(ringMax, rr);
      ang += dAng;
      i++;
    }
    if (placedThisRing.length === 0) {     // 该分量太大，单独占一环
      const c = rest[i]; const rr = c.r + GAP;
      placedThisRing.push({ c, x: ring + rr, y: 0 });
      ringMax = rr; i++;
    }
    for (const p of placedThisRing) {
      for (const v of p.c.mem) { gx[v] += p.x - p.c.mx; gy[v] += p.y - p.c.my; }
    }
    ring += ringMax * 2 + GAP;
  }
  log(`packed ${info.length} components, main r=${mainR.toFixed(0)}, outer ring=${ring.toFixed(0)}`);
}

/* ------------------------------------------------------------------ */
/* 8. 归一化 + 写出                                                     */
/* ------------------------------------------------------------------ */
let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity;
for (let i = 0; i < n; i++) {
  if (gx[i] < minX) minX = gx[i]; if (gx[i] > maxX) maxX = gx[i];
  if (gy[i] < minY) minY = gy[i]; if (gy[i] > maxY) maxY = gy[i];
}
const cxAll = (minX + maxX) / 2, cyAll = (minY + maxY) / 2;
const half = Math.max(maxX - minX, maxY - minY) / 2 || 1;
const SCALE = 1400 / half;   // 归一到 ±1400 的世界坐标
for (let i = 0; i < n; i++) {
  gx[i] = (gx[i] - cxAll) * SCALE;
  gy[i] = (gy[i] - cyAll) * SCALE;
}
log(`extent ±${(half * SCALE).toFixed(0)}`);

const r1 = (v) => Math.round(v * 10) / 10;
const outNodes = N.map((nd, i) => ({
  i: nd.i, l: nd.l, e: nd.e, t: nd.t, r: nd.r, d: nd.d, a: nd.a,
  x: r1(gx[i]), y: r1(gy[i]), g: deg[i],
}));
const outEdges = E.map(e => ({ s: e.s, t: e.t, y: e.y, r: e.r, q: e.q || '', d: e.d || '', c: e.c || '', Q: e.Q || 0 }));

fs.mkdirSync(path.dirname(OUT), { recursive: true });
fs.writeFileSync(OUT, JSON.stringify({
  meta: { ...D.meta, layout: 'fa2-barneshut+leafpetal', extent: 1400 },
  types: D.types, rels: D.rels, roles: D.roles, docs: D.docs,
  nodes: outNodes, edges: outEdges,
}));
log(`wrote ${OUT} (${(fs.statSync(OUT).size / 1048576).toFixed(2)} MB)`);

// 供人工检查的 SVG 缩略图
const prev = [];
prev.push(`<svg xmlns="http://www.w3.org/2000/svg" viewBox="-1500 -1500 3000 3000" width="1000" height="1000"><rect x="-1500" y="-1500" width="3000" height="3000" fill="#12151a"/>`);
prev.push(`<g stroke="#7d8794" stroke-opacity="0.18" stroke-width="0.5">`);
for (let i = 0; i < outEdges.length; i += 1) {
  const a = outNodes[outEdges[i].s], b = outNodes[outEdges[i].t];
  prev.push(`<line x1="${a.x}" y1="${a.y}" x2="${b.x}" y2="${b.y}"/>`);
}
prev.push(`</g>`);
const RC = { sun_original: '#d4526e', sun_compiled: '#E08D3C', classical_source: '#5b9bd5', third_party_clinical: '#6B9E78', general_tcm: '#8b95a3' };
for (const nd of outNodes) {
  prev.push(`<circle cx="${nd.x}" cy="${nd.y}" r="${(1.2 + Math.min(Math.sqrt(nd.g) * 0.9, 7)).toFixed(1)}" fill="${RC[nd.r] || '#888'}"/>`);
}
prev.push(`</svg>`);
fs.writeFileSync(path.join(ROOT, 'tools/build/preview.svg'), prev.join(''));
log('preview written');
