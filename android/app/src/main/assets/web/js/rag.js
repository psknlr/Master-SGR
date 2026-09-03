/* =========================================================================
   国医大师孙光荣中医知识图谱 · 端上检索增强引擎（GraphRAG）
   On-device Graph-RAG retrieval — JavaScript port of rag/kg_rag.py

   研发：孙光荣大师弟子田建辉团队 × 医哲未来人工智能研究院 (IMPF-AI Institute)

   与 Python 版算法一致：双路 BM25（实体 / 原文佐证）→ 实体名整串加权 →
   种子去重 → 一跳扩展（佐证质量 / 知识来源 / 类型配额）→ 关系类型轮转采样。
   索引分片构建，不卡 UI；单次检索在手机上约 10–30ms。
   ========================================================================= */
(function (root, factory) {
  if (typeof module === 'object' && module.exports) module.exports = factory();
  else root.KGRAG = factory();
})(typeof self !== 'undefined' ? self : this, function () {
  'use strict';

  const ROLE_COLOR = {
    sun_original: '#B03A30', sun_compiled: '#B5802C', classical_source: '#2E5C86',
    third_party_clinical: '#4A7A46', general_tcm: '#7E6F5C',
  };
  const ROLE_COLOR_NIGHT = {
    sun_original: '#E0685A', sun_compiled: '#DFA845', classical_source: '#6BA3D6',
    third_party_clinical: '#7EB771', general_tcm: '#A0917C',
  };
  const ROLE_WEIGHT = {
    sun_original: 1.0, sun_compiled: 0.72, classical_source: 0.6,
    third_party_clinical: 0.5, general_tcm: 0.42,
  };
  const DEFAULTS = { topSeeds: 35, maxEdges: 120, maxNodes: 140, maxChars: 9900 };

  const TOKEN_RE = /[一-鿿]+|[A-Za-z][A-Za-z0-9\-'.]*|\d+/g;
  function tokenize(text) {
    const out = [];
    const s = String(text || '');
    let m;
    TOKEN_RE.lastIndex = 0;
    while ((m = TOKEN_RE.exec(s))) {
      const w = m[0];
      const c = w.charCodeAt(0);
      if (c >= 0x4e00 && c <= 0x9fff) {
        if (w.length === 1) out.push(w);
        else {
          for (let i = 0; i < w.length - 1; i++) out.push(w.slice(i, i + 2));
          if (w.length <= 6) out.push(w);
        }
      } else out.push(w.toLowerCase());
    }
    return out;
  }
  const esc = (s) => String(s == null ? '' : s).replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));

  /* ---------------------------------------------------------------- BM25 */
  class BM25 {
    constructor(k1, b) { this.k1 = k1 || 1.5; this.b = b || 0.75; this.N = 0; this.post = new Map(); this.idf = new Map(); this._tmp = new Map(); this._len = []; }
    add(tokens) {                                   // 分片构建：逐条加入
      const i = this.N++;
      this._len.push(tokens.length);
      const tf = new Map();
      for (const t of tokens) tf.set(t, (tf.get(t) || 0) + 1);
      for (const [t, c] of tf) {
        let arr = this._tmp.get(t);
        if (!arr) { arr = []; this._tmp.set(t, arr); }
        arr.push(i, c);
      }
    }
    finalize() {
      this.docLen = Float32Array.from(this._len);
      let sum = 0; for (let i = 0; i < this.N; i++) sum += this.docLen[i];
      this.avgdl = this.N ? sum / this.N : 1;
      for (const [t, arr] of this._tmp) {
        const n = arr.length / 2;
        const ids = new Int32Array(n), tf = new Float32Array(n);
        for (let j = 0; j < n; j++) { ids[j] = arr[2 * j]; tf[j] = arr[2 * j + 1]; }
        this.post.set(t, { ids, tf });
        this.idf.set(t, Math.log(1 + (this.N - n + 0.5) / (n + 0.5)));
      }
      this._tmp = null; this._len = null;
    }
    score(qTokens, acc) {
      acc = acc || new Float32Array(this.N);
      const seen = new Set();
      const k1 = this.k1, b = this.b, avg = this.avgdl, dl = this.docLen;
      for (const t of qTokens) {
        if (seen.has(t)) continue; seen.add(t);
        const p = this.post.get(t); if (!p) continue;
        const idf = this.idf.get(t);
        const ids = p.ids, tf = p.tf;
        for (let j = 0; j < ids.length; j++) {
          const i = ids[j], f = tf[j];
          acc[i] += idf * (f * (k1 + 1) / (f + k1 * (1 - b + b * dl[i] / avg)));
        }
      }
      return acc;
    }
  }

  /* ---------------------------------------------------------------- 索引 */
  class KGIndex {
    /**
     * @param D  图谱 JSON（nodes / edges / types / rels / roles / docs）
     * @param adj 可选 {start:Int32Array(n+1), list:Int32Array} —— App 里已建好的 CSR 邻接（存边号）
     */
    constructor(D, adj) {
      this.D = D; this.nodes = D.nodes; this.edges = D.edges;
      this.typeZh = {}; for (const k in D.types) this.typeZh[k] = D.types[k].zh;
      this.relZh = {}; for (const k in D.rels) this.relZh[k] = D.rels[k].zh;
      this.roleZh = {}; for (const k in D.roles) this.roleZh[k] = D.roles[k].zh;
      this.docs = D.docs;
      const n = this.nodes.length, m = this.edges.length;
      this.degree = new Int32Array(n);
      for (let k = 0; k < m; k++) { this.degree[this.edges[k].s]++; this.degree[this.edges[k].t]++; }
      if (adj) { this.adjStart = adj.start; this.adjList = adj.list; }
      else {
        const start = new Int32Array(n + 1);
        for (let i = 0; i < n; i++) start[i + 1] = start[i] + this.degree[i];
        const list = new Int32Array(start[n]); const cur = start.slice(0, n);
        for (let k = 0; k < m; k++) { list[cur[this.edges[k].s]++] = k; list[cur[this.edges[k].t]++] = k; }
        this.adjStart = start; this.adjList = list;
      }
      this.nodeBM = new BM25(); this.quoteBM = new BM25();
      this.quoteEid = []; this.surface = new Map();
      this._ni = 0; this._ei = 0; this.ready = false;
      this.total = n + m;
    }
    /** 分片构建：每次处理 budget 条，返回 [已完成, 总数]；完成后 ready=true */
    step(budget) {
      budget = budget || 1500;
      const N = this.nodes, E = this.edges;
      while (budget > 0 && this._ni < N.length) {
        const nd = N[this._ni];
        const parts = [nd.l, nd.e || '', this.typeZh[nd.t] || ''].concat(nd.a || []);
        this.nodeBM.add(tokenize(parts.join(' ')));
        const surfs = [nd.l].concat(nd.a || []);
        for (const s0 of surfs) { const s = String(s0 || '').trim(); if (s.length >= 2 && !this.surface.has(s)) this.surface.set(s, this._ni); }
        this._ni++; budget--;
      }
      while (budget > 0 && this._ni >= N.length && this._ei < E.length) {
        const e = E[this._ei], q = String(e.q || '').trim();
        if (q) {
          this.quoteEid.push(this._ei);
          this.quoteBM.add(tokenize(q + ' ' + (this.relZh[e.y] || '') + ' ' + N[e.s].l + ' ' + N[e.t].l));
        }
        this._ei++; budget--;
      }
      if (this._ni >= N.length && this._ei >= E.length && !this.ready) {
        this.nodeBM.finalize(); this.quoteBM.finalize();
        this.quoteEid = Int32Array.from(this.quoteEid);
        this.ready = true;
      }
      return [this._ni + this._ei, this.total];
    }
    buildSync() { while (!this.ready) this.step(1e9); return this; }

    /* ------------------------------------------------------------ 检索 */
    retrieve(query, opts) {
      opts = opts || {};
      const topSeeds = opts.topSeeds || DEFAULTS.topSeeds, maxEdges = opts.maxEdges || DEFAULTS.maxEdges;
      const maxNodes = opts.maxNodes || DEFAULTS.maxNodes;
      const focus = opts.focus || [];
      const N = this.nodes, E = this.edges, n = N.length;
      const qText = focus.length ? query + ' ' + focus.join(' ') : query;
      const toks = tokenize(qText);
      const empty = { query, seeds: [], nodes: [], edges: [], kg: this };
      if (!this.ready) return empty;

      const score = this.nodeBM.score(toks, new Float32Array(n));

      // 佐证命中回流到两端，并记住直接命中的边
      const direct = new Map();
      if (this.quoteEid.length) {
        const qs = this.quoteBM.score(toks);
        const idx = []; for (let j = 0; j < qs.length; j++) if (qs[j] > 0) idx.push(j);
        if (idx.length) {
          idx.sort((a, b) => qs[b] - qs[a]);
          const top = idx.slice(0, 60), mx = qs[top[0]] || 1;
          for (const j of top) {
            const ei = this.quoteEid[j], e = E[ei], w = qs[j];
            score[e.s] += 0.55 * w; score[e.t] += 0.55 * w;
            direct.set(ei, 0.9 * w / mx);
          }
        }
      }
      // 实体名整串出现在问题里 → 强加权
      for (const [surf, nid] of this.surface) if (qText.indexOf(surf) >= 0) score[nid] += 4.0 + 0.9 * surf.length;

      // 候选 → 同名去重 → 种子
      const cand = []; for (let i = 0; i < n; i++) if (score[i] > 0) cand.push(i);
      if (!cand.length) return empty;
      cand.sort((a, b) => score[b] - score[a]);
      const seeds = [], seenLab = new Set();
      for (const i of cand) {
        const lab = N[i].l; if (seenLab.has(lab)) continue;
        seenLab.add(lab); seeds.push([i, score[i]]);
        if (seeds.length >= topSeeds) break;
      }
      const topScore = seeds[0][1] || 1;

      // 一跳扩展
      const edgeScore = new Map();
      const perSeedCap = Math.max(6, Math.floor(maxEdges / Math.max(1, seeds.length))), perTypeCap = 3;
      for (const [nid, sc] of seeds) {
        const picked = [];
        for (let p = this.adjStart[nid]; p < this.adjStart[nid + 1]; p++) {
          const ei = this.adjList[p], e = E[ei];
          const other = e.s === nid ? e.t : e.s;
          const q = String(e.q || '').trim();
          let s = sc / topScore;
          s += q.length >= 10 ? 0.5 : (q.length >= 4 ? 0.16 : 0);
          if (q.length < 8 && q && (N[other].l.indexOf(q) >= 0 || N[nid].l.indexOf(q) >= 0)) s -= 0.4;
          s += 0.55 * (ROLE_WEIGHT[e.r] || 0.4);
          s += 0.30 * Math.min(score[other] / topScore, 1);
          s -= 0.12 * Math.min(Math.log1p(this.degree[other]) / 6, 1);
          if (e.Q) s -= 0.25;
          picked.push([s, ei, e.y]);
        }
        picked.sort((a, b) => b[0] - a[0]);
        const typeUsed = new Map(); let taken = 0; const spill = [];
        for (const [s, ei, y] of picked) {
          if (taken >= perSeedCap) break;
          const u = typeUsed.get(y) || 0;
          if (u >= perTypeCap) { spill.push([s, ei]); continue; }
          typeUsed.set(y, u + 1); taken++;
          edgeScore.set(ei, Math.max(edgeScore.get(ei) || 0, s));
        }
        for (const [s, ei] of spill.slice(0, Math.max(0, perSeedCap - taken))) edgeScore.set(ei, Math.max(edgeScore.get(ei) || 0, s - 0.3));
      }
      for (const [ei, s] of direct) edgeScore.set(ei, Math.max(edgeScore.get(ei) || 0, s + 1.2));

      // 去重 + 关系类型轮转
      const ranked = Array.from(edgeScore.entries()).sort((a, b) => b[1] - a[1]);
      const buckets = new Map(), seenSig = new Set();
      for (const [ei, sc] of ranked) {
        const e = E[ei];
        const sig = e.y + '|' + N[e.s].l + '|' + N[e.t].l + '|' + String(e.q || '').slice(0, 24);
        if (seenSig.has(sig)) continue; seenSig.add(sig);
        let b = buckets.get(e.y); if (!b) { b = []; buckets.set(e.y, b); }
        b.push([ei, sc]);
      }
      const types = Array.from(buckets.keys()).sort((a, b) => buckets.get(b)[0][1] - buckets.get(a)[0][1]);
      const bucketCap = Math.max(3, Math.floor(maxEdges / 4));
      const chosen = []; let round = 0;
      while (chosen.length < maxEdges && round < bucketCap) {
        let progressed = false;
        for (const y of types) {
          const b = buckets.get(y);
          if (round < b.length) { chosen.push(b[round]); progressed = true; if (chosen.length >= maxEdges) break; }
        }
        if (!progressed) break;
        round++;
      }
      chosen.sort((a, b) => b[1] - a[1]);

      const order = [], seen = new Set();
      for (const [nid] of seeds) if (!seen.has(nid)) { seen.add(nid); order.push(nid); }
      for (const [ei] of chosen) for (const nid of [E[ei].s, E[ei].t]) if (!seen.has(nid)) { seen.add(nid); order.push(nid); }
      return { query, seeds, nodes: order.slice(0, maxNodes), edges: chosen, kg: this };
    }

    entityNames(r, k) { return r.seeds.slice(0, k || 3).map(([i]) => this.nodes[i].l); }

    /* ------------------------------------------------------------ 上下文 */
    context(r, maxChars) {
      maxChars = maxChars || DEFAULTS.maxChars;
      const N = this.nodes, E = this.edges;
      if (!r.nodes.length) return '（图谱中未检索到与该问题直接相关的实体。）';
      const entBudget = Math.floor(maxChars * 0.34);
      const buf = ['以下是从《国医大师孙光荣中医知识图谱》检索到的知识片段，共 ' + r.nodes.length + ' 个实体、' + r.edges.length + ' 条关系。\n', '〖实体〗'];
      const seedIds = new Set(r.seeds.map(x => x[0]));
      let used = 0, listed = 0;
      for (const nid of r.nodes) {
        const nd = N[nid];
        let line = (seedIds.has(nid) ? '★ ' : '· ') + nd.l + '（' + (this.typeZh[nd.t] || nd.t) + '；' + (this.roleZh[nd.r] || nd.r) + '）';
        if (nd.e) line += ' [' + String(nd.e).slice(0, 80) + ']';
        if (nd.d && nd.d.length) line += '；出处 ' + nd.d.slice(0, 3).map(d => d + '《' + (this.docs[d] || '') + '》').join('、');
        if (nd.a && nd.a.length) line += '；异名 ' + nd.a.slice(0, 4).join('、');
        buf.push(line); used += line.length; listed++;
        if (used > entBudget) { const rem = r.nodes.length - listed; if (rem > 0) buf.push('…（另有 ' + rem + ' 个相关实体见下方关系）'); break; }
      }
      buf.push('\n〖关系与原文佐证〗');
      used = buf.reduce((a, x) => a + x.length, 0) + buf.length;
      const TAIL = 40;
      for (let k = 0; k < r.edges.length; k++) {
        const ei = r.edges[k][0], e = E[ei];
        let seg = '[R' + (k + 1) + '] ' + N[e.s].l + ' —（' + (this.relZh[e.y] || e.y) + '）→ ' + N[e.t].l;
        const q = String(e.q || '').trim();
        if (q) seg += '\n      佐证：「' + q.slice(0, 220) + '」';
        const src = e.c || e.d;
        if (src) {
          seg += '\n      出处：' + src;
          if (e.d && this.docs[e.d]) seg += '《' + this.docs[e.d] + '》';
          seg += '（' + (this.roleZh[e.r] || e.r || '') + '）';
        }
        if (e.Q) seg += '  ⚑ 该关系未通过本体校验，仅供参考';
        if (used + seg.length + 1 + TAIL > maxChars && k > 0) { buf.push('…（其余 ' + (r.edges.length - k) + ' 条关系因篇幅省略）'); break; }
        buf.push(seg); used += seg.length + 1;
      }
      return buf.join('\n');
    }

    /* ------------------------------------------------------------ 子图 SVG */
    /**
     * 布局思路与 Python 版一致：把「圆点 + 标签」当矩形做 FR 力导向，再跑矩形去重叠松弛。
     * opts: {width, maxNodes, maxLabels, theme, interactive}
     */
    svg(r, opts) {
      opts = opts || {};
      const kg = this, N = this.nodes, E = this.edges;
      const ids = r.nodes.slice(0, opts.maxNodes || 60);
      if (!ids.length) return '';
      const idx = new Map(ids.map((v, i) => [v, i])), n = ids.length;
      const pairs = [];
      for (const [ei] of r.edges) {
        const e = E[ei], a = idx.get(e.s), b = idx.get(e.t);
        if (a != null && b != null && a !== b) pairs.push([a, b, this.relZh[e.y] || e.y]);
      }
      const night = opts.theme === 'night';
      const RC = night ? ROLE_COLOR_NIGHT : ROLE_COLOR;
      const bg = night ? '#131009' : '#F1E6D1', fg = night ? '#EDE3D0' : '#241C15', sub = night ? '#93866F' : '#7C6C58';
      const seedIds = new Set(r.seeds.map(x => x[0]));
      const maxLabels = opts.maxLabels || 24;

      const order = ids.map((_, i) => i).sort((a, b) => {
        const sa = seedIds.has(ids[a]) ? 0 : 1, sb = seedIds.has(ids[b]) ? 0 : 1;
        return sa !== sb ? sa - sb : kg.degree[ids[b]] - kg.degree[ids[a]];
      });
      const labeled = new Set(order.slice(0, maxLabels));
      const textW = (s, fs) => { let w = 0; for (const ch of s) w += ch > '⹿' ? fs : fs * 0.56; return w; };
      const maxChars = n <= 30 ? 10 : (n <= 60 ? 8 : 7);
      const radius = new Float64Array(n), hw = new Float64Array(n), hh = new Float64Array(n), fsz = new Float64Array(n);
      const labels = new Array(n);
      for (let i = 0; i < n; i++) {
        const nid = ids[i], isSeed = seedIds.has(nid), deg = kg.degree[nid];
        radius[i] = (isSeed ? 6.5 : 3.2) + Math.min(Math.pow(deg, 0.35), 3);
        if (labeled.has(i)) {
          const raw = N[nid].l, lab = raw.slice(0, maxChars) + (raw.length > maxChars ? '…' : '');
          const fs = isSeed ? 11 : 9.5;
          labels[i] = lab; fsz[i] = fs;
          hw[i] = Math.max(radius[i], textW(lab, fs) / 2) + 3; hh[i] = radius[i] + fs + 4;
        } else { labels[i] = ''; hw[i] = radius[i] + 2.5; hh[i] = radius[i] + 2.5; }
      }
      let boxArea = 0; for (let i = 0; i < n; i++) boxArea += 4 * hw[i] * hh[i];
      const canvas = boxArea / 0.20, estW = Math.sqrt(canvas * 1.35);

      // FR 力导向
      const X = new Float64Array(n), Y = new Float64Array(n), DX = new Float64Array(n), DY = new Float64Array(n);
      let seed = 11; const rnd = () => { seed = (seed * 1664525 + 1013904223) >>> 0; return seed / 4294967296 - 0.5; };
      for (let i = 0; i < n; i++) { const a = i * 2.399963, rad = Math.sqrt(i + 0.5) * (estW / (3.2 * Math.sqrt(n))); X[i] = Math.cos(a) * rad + rnd() * 3; Y[i] = Math.sin(a) * rad + rnd() * 3; }
      const k = Math.sqrt(canvas / Math.max(n, 1)) * 0.62; let temp = estW * 0.08; const IT = n > 80 ? 200 : 260;
      for (let it = 0; it < IT; it++) {
        DX.fill(0); DY.fill(0);
        for (let i = 0; i < n; i++) for (let j = i + 1; j < n; j++) {
          const dx = X[i] - X[j], dy = Y[i] - Y[j], d2 = dx * dx + dy * dy + 1e-3, c = k * k / d2;
          DX[i] += dx * c; DY[i] += dy * c; DX[j] -= dx * c; DY[j] -= dy * c;
        }
        for (const [a, b] of pairs) {
          const dx = X[b] - X[a], dy = Y[b] - Y[a], d = Math.hypot(dx, dy) + 1e-6, f = d / k;
          DX[a] += dx * f; DY[a] += dy * f; DX[b] -= dx * f; DY[b] -= dy * f;
        }
        const g = 0.035 * (1 + 2 * it / IT);
        for (let i = 0; i < n; i++) {
          DX[i] -= X[i] * g; DY[i] -= Y[i] * g;
          const len = Math.hypot(DX[i], DY[i]) + 1e-9, s = Math.min(len, temp) / len;
          X[i] += DX[i] * s; Y[i] += DY[i] * s;
        }
        temp *= 0.985;
      }
      // 画布：贴合版面长宽比；App 里可指定固定宽度（屏宽）
      const pad = 8, legendH = 22;
      let lox = 1e9, loy = 1e9, hix = -1e9, hiy = -1e9;
      for (let i = 0; i < n; i++) { lox = Math.min(lox, X[i] - hw[i]); hix = Math.max(hix, X[i] + hw[i]); loy = Math.min(loy, Y[i] - hh[i]); hiy = Math.max(hiy, Y[i] + hh[i]); }
      const spanX = Math.max(hix - lox, 1e-6), spanY = Math.max(hiy - loy, 1e-6);
      let width = opts.width, plotH, sx, sy;
      if (!width) {
        // 自适应画布：长宽比贴合版面，等比缩放并居中
        const ar = Math.min(2, Math.max(0.85, spanX / spanY));
        width = Math.round(Math.min(1380, Math.max(520, Math.sqrt(canvas * ar))));
        plotH = Math.round(Math.min(1100, Math.max(300, canvas / width)));
        sx = sy = Math.min((width - 2 * pad) / spanX, (plotH - 2 * pad) / spanY);
      } else {
        // 定宽（手机屏宽）：允许纵向拉伸填满所需面积，随后由去重叠松弛整理；
        // 拉伸比例限制在 2.2 倍内，避免版面走形
        plotH = Math.min(1600, Math.max(240, canvas / width));
        sx = (width - 2 * pad) / spanX; sy = Math.min((plotH - 2 * pad) / spanY, sx * 2.2);
        plotH = spanY * sy + 2 * pad;
      }
      for (let i = 0; i < n; i++) { X[i] = (X[i] - lox) * sx + (width - spanX * sx) / 2; Y[i] = (Y[i] - loy) * sy + (plotH - spanY * sy) / 2; }

      // 矩形去重叠松弛
      const clampAll = () => { for (let i = 0; i < n; i++) { X[i] = Math.min(Math.max(X[i], hw[i] + pad * 0.4), width - hw[i] - pad * 0.4); Y[i] = Math.min(Math.max(Y[i], hh[i] + pad * 0.4), plotH - hh[i] - pad * 0.4); } };
      for (let it = 0; it < 180; it++) {
        DX.fill(0); DY.fill(0); let hit = false;
        for (let i = 0; i < n; i++) for (let j = i + 1; j < n; j++) {
          const dx = X[i] - X[j], dy = Y[i] - Y[j];
          const ox = hw[i] + hw[j] - Math.abs(dx), oy = hh[i] + hh[j] - Math.abs(dy);
          if (ox <= 0 || oy <= 0) continue; hit = true;
          if (ox <= oy) { const px = (dx >= 0 ? 1 : -1) * ox * 0.5; DX[i] += px; DX[j] -= px; }
          else { const py = (dy >= 0 ? 1 : -1) * oy * 0.5; DY[i] += py; DY[j] -= py; }
        }
        if (!hit) break;
        for (let i = 0; i < n; i++) { X[i] += DX[i] * 0.55; Y[i] += DY[i] * 0.55; }
        clampAll();
      }
      clampAll();
      // 裁掉上下多余的空白：把内容贴到顶部，高度取实际占用
      let minY = 1e9, maxY = -1e9;
      for (let i = 0; i < n; i++) { minY = Math.min(minY, Y[i] - hh[i]); maxY = Math.max(maxY, Y[i] + hh[i]); }
      for (let i = 0; i < n; i++) Y[i] += pad - minY;
      plotH = Math.round(maxY - minY + 2 * pad);
      const height = plotH + legendH;

      // 出图
      const f1 = (v) => v.toFixed(1);
      const out = ['<svg xmlns="http://www.w3.org/2000/svg" width="' + width + '" height="' + height + '" viewBox="0 0 ' + width + ' ' + height + '" style="background:' + bg + ';border-radius:4px;display:block;max-width:100%">'];
      out.push('<g stroke="' + sub + '" stroke-opacity="0.34" stroke-width="1" fill="none">');
      for (const [a, b, rel] of pairs) out.push('<line x1="' + f1(X[a]) + '" y1="' + f1(Y[a]) + '" x2="' + f1(X[b]) + '" y2="' + f1(Y[b]) + '"><title>' + esc(rel) + '</title></line>');
      out.push('</g>');
      for (let i = 0; i < n; i++) {
        const nd = N[ids[i]], isSeed = seedIds.has(ids[i]);
        out.push('<circle class="kn" data-node="' + ids[i] + '" cx="' + f1(X[i]) + '" cy="' + f1(Y[i]) + '" r="' + f1(radius[i]) + '" fill="' + (RC[nd.r] || '#7E6F5C') + '"' + (isSeed ? ' stroke="' + bg + '" stroke-width="2"' : '') + '><title>' + esc(nd.l + '（' + (kg.typeZh[nd.t] || nd.t) + '）') + '</title></circle>');
      }
      for (let i = 0; i < n; i++) {
        if (!labels[i]) continue;
        out.push('<text class="kn" data-node="' + ids[i] + '" x="' + f1(X[i]) + '" y="' + f1(Y[i] + radius[i] + fsz[i] + 0.5) + '" font-size="' + fsz[i] + '" fill="' + fg + '" text-anchor="middle" stroke="' + bg + '" stroke-width="2.6" paint-order="stroke" stroke-linejoin="round" font-family="Noto Serif CJK SC,Songti SC,serif"' + (seedIds.has(ids[i]) ? ' font-weight="600"' : '') + '>' + esc(labels[i]) + '</text>');
      }
      const legend = [['sun_original', '原创'], ['sun_compiled', '编纂'], ['classical_source', '经典'], ['third_party_clinical', '他人临床'], ['general_tcm', '通识']];
      let cx = 10; out.push('<g font-size="9.5" font-family="Noto Sans CJK SC,sans-serif" fill="' + sub + '" opacity="0.9">');
      for (const [rk, zh] of legend) { out.push('<circle cx="' + cx + '" cy="' + (plotH + 12) + '" r="3.5" fill="' + RC[rk] + '"/><text x="' + (cx + 7) + '" y="' + (plotH + 15.5) + '">' + zh + '</text>'); cx += 7 + zh.length * 9.5 + 14; }
      out.push('<text x="' + (width - 8) + '" y="' + (plotH + 15.5) + '" text-anchor="end">' + n + ' 实体 · ' + pairs.length + ' 关系</text></g></svg>');
      return out.join('');
    }
  }

  return { KGIndex, BM25, tokenize, DEFAULTS, ROLE_COLOR, ROLE_COLOR_NIGHT };
});
