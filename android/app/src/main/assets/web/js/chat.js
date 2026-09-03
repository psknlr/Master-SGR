/* =========================================================================
   国医大师孙光荣中医知识图谱 · 问道（端上 GraphRAG 问答）
   In-app Graph-RAG chat: retrieval runs on the device, only generation calls
   the user's chosen provider (MiniMax / Poe) through the native bridge.

   研发：孙光荣大师弟子田建辉团队 × 医哲未来人工智能研究院 (IMPF-AI Institute)

   与 Java 层的约定：
     JS → Java   NativeApp.llmStart(id, cfgJson) / llmCancel(id) / httpGet(id, url)
     Java → JS   window.__llmEvent(id, 'chunk'|'done'|'error'|'http', payload)
   浏览器里没有 NativeApp 时退化为 fetch（供桌面调试；需服务端允许跨域）。
   ========================================================================= */
'use strict';

const CHAT = (() => {
  const LS_SET = 'sgr-chat-settings', LS_CONV = 'sgr-chat-conv', LS_POE = 'sgr-poe-models';
  const DEF = {
    provider: 'minimax', mmModel: 'MiniMax-M3', mmSite: 'cn', mmGroup: '', keyMm: '',
    poeModel: 'claude-sonnet-5', keyPoe: '',
    temperature: 0.3, topSeeds: 35, maxEdges: 120, maxChars: 9900, showEvidence: true,
  };
  const SITE = { cn: 'https://api.minimax.chat/v1', intl: 'https://api.minimaxi.chat/v1' };
  const SYSTEM = `你是「国医大师孙光荣中医知识图谱」的学术问答助手，由孙光荣大师弟子田建辉团队与医哲未来人工智能研究院（IMPF-AI Institute）联合研制。

作答规则：
1. 只依据【图谱证据】作答。证据里没有的内容，明确说「图谱中未见记载」，不得凭常识补充或杜撰。
2. 引用证据时标注编号，如「据 [R3]」；涉及原文时一并给出出处编号（如 D3#c0037）。
3. 区分知识来源：「孙光荣原创」是孙老本人的论断，「孙光荣编纂」是他选编他人内容，「经典引文」出自古籍，「他人临床报道」是其他医家的工作。凡属孙老本人观点，请明确说明；不要把他人观点说成孙老的。
4. 标注「⚑ 未通过本体校验」的关系，若要引用须注明其为待审信息。
5. 用中文作答，条理清晰；涉及辨证论治时按「病因病机 — 治则治法 — 方药」的顺序展开。
6. 结尾附一句提醒：本回答仅供学术研究与教学参考，不能替代执业医师的诊断与处方。

【图谱证据】之外的闲聊或与中医无关的问题，可以简短回应并引导回图谱主题。`;
  const EXAMPLES = [
    '什么是「中和思想」？中和组方的基本原则是什么？',
    '孙光荣治疗脾胃病的学术观点有哪些？',
    'H7N9 禽流感在中医里属于什么范畴，分几个阶段辨证？',
    '带下病的外治法，图谱里有哪些记载？',
    '「三联药组」是什么？举几个孙老常用的药组。',
    '肿瘤的中医治疗思路，孙老怎么讲？',
  ];

  let set = Object.assign({}, DEF);
  let conv = [];                // {role, content, ev?:{seeds,nodes,edges}, pending?, err?, svg?}
  let idx = null, buildTimer = 0, building = false;
  let busy = false, curReq = null, focusEnt = [];
  let seq = 0; const pending = {};
  let el = {};

  /* ---------------- 持久化 ---------------- */
  const load = () => {
    try { Object.assign(set, JSON.parse(localStorage.getItem(LS_SET) || '{}')); } catch (e) {}
    try {
      const c = JSON.parse(localStorage.getItem(LS_CONV) || '[]');
      if (Array.isArray(c)) conv = c.filter(m => m && m.role && typeof m.content === 'string').slice(-40).map(m => ({ role: m.role, content: m.content, ev: m.ev || null, err: !!m.err }));
    } catch (e) {}
  };
  const saveSet = () => { try { localStorage.setItem(LS_SET, JSON.stringify(set)); } catch (e) {} };
  const persist = () => {
    try {
      localStorage.setItem(LS_CONV, JSON.stringify(conv.slice(-40).map(m => ({
        role: m.role, content: m.content, err: m.err || false,
        ev: m.ev ? { seeds: m.ev.seeds, nodes: m.ev.nodes, edges: m.ev.edges } : null,
      }))));
    } catch (e) {}
  };

  /* ---------------- 索引（分片构建，不卡 UI） ---------------- */
  function ensureIndex(cb) {
    if (idx && idx.ready) { cb && cb(); return; }
    if (!idx) idx = new KGRAG.KGIndex(S.D, { start: S.adjStart, list: S.adjList });
    if (cb) waiters.push(cb);
    if (building) return;
    building = true;
    const tick = () => {
      const t0 = performance.now();
      let done, total;
      do { [done, total] = idx.step(600); } while (!idx.ready && performance.now() - t0 < 24);
      if (el.idx) {
        el.idx.textContent = idx.ready ? '' : '正在结网 ' + Math.round(done / total * 100) + '%';
        el.idx.hidden = idx.ready;
      }
      if (idx.ready) { building = false; const w = waiters.splice(0); w.forEach(f => f()); return; }
      buildTimer = setTimeout(tick, 0);
    };
    tick();
  }
  const waiters = [];
  /** 数据装载完成后由 app.js 调用：趁空闲先把索引建好 */
  function warm() {
    const start = () => ensureIndex(null);
    if (window.requestIdleCallback) requestIdleCallback(start, { timeout: 4000 }); else setTimeout(start, 1200);
  }

  /* ---------------- LLM 桥 ---------------- */
  const LLM = {
    start(cfg, h) {
      const id = String(++seq); pending[id] = h;
      if (window.NativeApp && NativeApp.llmStart) {
        try { NativeApp.llmStart(id, JSON.stringify(cfg)); } catch (e) { h.error('调用原生接口失败：' + e); delete pending[id]; }
        return id;
      }
      // 浏览器调试：直接 fetch（需要对端允许 CORS）
      const isPoe = cfg.provider === 'poe';
      const url = isPoe ? (cfg.baseUrl || 'https://api.poe.com/v1') + '/chat/completions'
        : (cfg.baseUrl || SITE.cn) + '/text/chatcompletion_v2' + (cfg.groupId ? '?GroupId=' + encodeURIComponent(cfg.groupId) : '');
      if (!cfg.apiKey) { setTimeout(() => { h.error(isPoe ? '未配置 Poe API Key' : '未配置 MiniMax API Key'); delete pending[id]; }, 0); return id; }
      const ctrl = new AbortController(); pending[id].ctrl = ctrl;
      fetch(url, { method: 'POST', signal: ctrl.signal,
        headers: { 'Authorization': 'Bearer ' + cfg.apiKey, 'Content-Type': 'application/json' },
        body: JSON.stringify({ model: cfg.model, messages: cfg.messages, stream: true, temperature: isPoe ? cfg.temperature : Math.max(0.01, cfg.temperature), max_tokens: cfg.maxTokens }) })
        .then(async res => {
          if (res.status >= 400) throw new Error((isPoe ? 'Poe' : 'MiniMax') + ' 返回 ' + res.status + '：' + (await res.text()).slice(0, 300));
          const rd = res.body.getReader(), dec = new TextDecoder(); let buf = '', streamed = false, raw = '';
          for (;;) {
            const { value, done } = await rd.read(); if (done) break;
            buf += dec.decode(value, { stream: true });
            let nl; while ((nl = buf.indexOf('\n')) >= 0) {
              const line = buf.slice(0, nl).trim(); buf = buf.slice(nl + 1);
              if (!line) continue;
              if (!line.startsWith('data:')) { raw += line; continue; }
              const p = line.slice(5).trim(); if (!p || p === '[DONE]') continue;
              const piece = extractDelta(cfg.provider, p, streamed); if (piece) { streamed = true; h.chunk(piece); }
            }
          }
          if (!streamed && raw) { const piece = extractDelta(cfg.provider, raw, false); if (piece) { streamed = true; h.chunk(piece); } }
          if (!streamed) throw new Error('模型未返回内容');
          h.done();
        }).catch(e => { if (e.name !== 'AbortError') h.error(String(e.message || e)); })
        .finally(() => delete pending[id]);
      return id;
    },
    cancel(id) {
      if (!id || !pending[id]) return;
      if (window.NativeApp && NativeApp.llmCancel) { try { NativeApp.llmCancel(id); } catch (e) {} }
      if (pending[id].ctrl) pending[id].ctrl.abort();
      delete pending[id];
    },
    httpGet(url) {
      return new Promise(resolve => {
        if (window.NativeApp && NativeApp.httpGet) {
          const id = String(++seq);
          pending[id] = { http: (payload) => { try { resolve(JSON.parse(payload)); } catch (e) { resolve({ status: -1, body: String(payload) }); } } };
          try { NativeApp.httpGet(id, url); } catch (e) { delete pending[id]; resolve({ status: -1, body: String(e) }); }
        } else {
          fetch(url).then(async r => resolve({ status: r.status, body: await r.text() })).catch(e => resolve({ status: -1, body: String(e) }));
        }
      });
    },
  };
  function extractDelta(provider, payload, streamed) {
    let o; try { o = JSON.parse(payload); } catch (e) { return null; }
    if (provider !== 'poe') { const br = o.base_resp; if (br && br.status_code) throw new Error('MiniMax 错误 ' + br.status_code + '：' + br.status_msg); }
    else if (o.error) throw new Error('Poe 错误：' + (o.error.message || JSON.stringify(o.error)));
    let s = '';
    for (const ch of o.choices || []) { const d = ch.delta && ch.delta.content; if (d) s += d; else if (!streamed && ch.message && ch.message.content) s += ch.message.content; }
    return s || null;
  }
  window.__llmEvent = function (id, type, payload) {
    const h = pending[id]; if (!h) return;
    if (type === 'chunk') h.chunk && h.chunk(payload);
    else if (type === 'done') { delete pending[id]; h.done && h.done(); }
    else if (type === 'error') { delete pending[id]; h.error && h.error(payload); }
    else if (type === 'http') { delete pending[id]; h.http && h.http(payload); }
  };

  /* Poe 模型目录校验：claude-sonnet-5 未上架时自动退到同族最新版 */
  async function resolvePoeModel(desired) {
    let ids = null;
    try { const c = JSON.parse(localStorage.getItem(LS_POE) || 'null'); if (c && Date.now() - c.t < 3600e3) ids = c.ids; } catch (e) {}
    if (!ids) {
      const r = await LLM.httpGet('https://api.poe.com/v1/models');
      if (r.status === 200) { try { ids = (JSON.parse(r.body).data || []).map(m => m.id).filter(Boolean); localStorage.setItem(LS_POE, JSON.stringify({ t: Date.now(), ids })); } catch (e) {} }
    }
    if (!ids) return { model: desired, note: '' };
    if (ids.indexOf(desired) >= 0) return { model: desired, note: '' };
    const low = desired.toLowerCase(), parts = low.split('-');
    const fam = parts.length > 1 ? parts[0] + '-' + parts[1] : parts[0];
    let cands = ids.filter(i => i.toLowerCase().startsWith(fam));
    if (!cands.length) cands = ids.filter(i => i.toLowerCase().startsWith(parts[0]));
    if (!cands.length) return { model: desired, note: '⚠ Poe 目录中没有「' + desired + '」，请在设置中另选。' };
    const ver = m => { const t = m.split('-').pop(); const v = parseFloat(t); return isNaN(v) ? -1 : v; };
    cands.sort((a, b) => ver(b) - ver(a));
    return { model: cands[0], note: 'Poe 暂无「' + desired + '」，已改用同族最新的「' + cands[0] + '」' };
  }

  /* ---------------- Markdown-lite（先转义再加标记，安全） ---------------- */
  function md(src) {
    const lines = esc(src).split('\n'); const out = []; let list = null;
    const inline = s => s
      .replace(/\*\*([^*]+)\*\*/g, '<b>$1</b>')
      .replace(/`([^`]+)`/g, '<code>$1</code>')
      .replace(/\[R(\d+)\]/g, '<a class="cite" data-r="$1">R$1</a>')
      .replace(/（?据\s*R(\d+)）?/g, m => m.replace(/R(\d+)/, '<a class="cite" data-r="$1">R$1</a>'));
    const flush = () => { if (list) { out.push('</' + list + '>'); list = null; } };
    for (let raw of lines) {
      const t = raw.trim();
      if (!t) { flush(); continue; }
      let m;
      if ((m = t.match(/^(#{1,4})\s+(.*)/))) { flush(); out.push('<h4>' + inline(m[2]) + '</h4>'); continue; }
      if ((m = t.match(/^[-*•]\s+(.*)/))) { if (list !== 'ul') { flush(); list = 'ul'; out.push('<ul>'); } out.push('<li>' + inline(m[1]) + '</li>'); continue; }
      if ((m = t.match(/^(\d+)[.、．)]\s*(.*)/))) { if (list !== 'ol') { flush(); list = 'ol'; out.push('<ol>'); } out.push('<li>' + inline(m[2]) + '</li>'); continue; }
      if (/^[-—─]{3,}$/.test(t)) { flush(); out.push('<hr>'); continue; }
      flush(); out.push('<p>' + inline(t) + '</p>');
    }
    flush(); return out.join('');
  }

  /* ---------------- 渲染 ---------------- */
  function roleColor(r) { return CSSVAR[r] || CSSVAR.general_tcm || '#7E6F5C'; }

  function evidenceHtml(m, k) {
    const ev = m.ev; if (!ev || !ev.nodes || !ev.nodes.length) return '<div class="ev none">图谱中未检索到直接相关的实体</div>';
    const N = S.D.nodes, E = S.D.edges;
    const open = !!m.evOpen;
    const rels = ev.edges.map(([ei], i) => {
      const e = E[ei]; return { i: i + 1, e, s: N[e.s], t: N[e.t] };
    });
    const relItem = r => {
      const q = String(r.e.q || '').trim();
      return '<div class="rl" data-r="' + r.i + '"><span class="rn">R' + r.i + '</span>' +
        '<a class="ent" data-node="' + r.e.s + '">' + esc(r.s.l) + '</a>' +
        '<i class="rt">' + esc(S.relLbl[r.e.y] || r.e.y) + '</i>' +
        '<a class="ent" data-node="' + r.e.t + '">' + esc(r.t.l) + '</a>' +
        (r.e.Q ? '<span class="qflag">⚑ 待审</span>' : '') +
        (q ? '<div class="rq">「' + esc(q.slice(0, 160)) + (q.length > 160 ? '…' : '') + '」<small>' + esc((r.e.c || r.e.d || '')) + (r.e.d && S.D.docs[r.e.d] ? '《' + esc(S.D.docs[r.e.d]) + '》' : '') + ' · ' + esc(S.roleLbl[r.e.r] || r.e.r || '') + '</small></div>' : '') +
        '</div>';
    };
    const seedSet = new Set(ev.seeds.map(x => x[0]));
    const ents = ev.nodes.map(nid => { const nd = N[nid]; return '<a class="chip ent" data-node="' + nid + '" style="border-color:' + roleColor(nd.r) + '">' + (seedSet.has(nid) ? '★ ' : '') + esc(nd.l.length > 14 ? nd.l.slice(0, 13) + '…' : nd.l) + '</a>'; }).join('');
    const tab = m.evTab || 'rel';
    return '<div class="ev" data-k="' + k + '">' +
      '<button class="ev-h" data-act="toggle"><span class="seal sm">依据</span>' +
      '<b>' + ev.nodes.length + ' 实体 · ' + ev.edges.length + ' 关系</b><i class="arr">' + (open ? '▾' : '▸') + '</i></button>' +
      (open ? '' : '<div class="ev-peek">' + rels.slice(0, 2).map(relItem).join('') + (rels.length > 2 ? '<button class="more" data-act="toggle">展开全部 ' + rels.length + ' 条关系与子图 ▾</button>' : '') + '</div>') +
      (open ? '<div class="ev-b">' +
        '<div class="ev-tabs">' + [['rel', '关系与佐证'], ['sub', '子图'], ['ent', '实体']].map(([t, l]) => '<button class="chip' + (tab === t ? ' on' : '') + '" data-act="tab" data-tab="' + t + '">' + l + '</button>').join('') + '</div>' +
        (tab === 'rel' ? '<div class="ev-rel">' + rels.map(relItem).join('') + '</div>' : '') +
        (tab === 'sub' ? '<div class="ev-sub">' + (m.svg || '<div class="sgr-note">正在布局…</div>') + '<div class="sgr-note" style="margin-top:6px">点圆点或名称可查看实体详情；★ 描边者为检索种子</div></div>' : '') +
        (tab === 'ent' ? '<div class="ev-ent">' + ents + '</div>' : '') +
        '</div>' : '') +
      '</div>';
  }

  function render(onlyLast) {
    if (!el.list) return;
    const items = conv.map((m, k) => {
      if (m.role === 'user') return '<div class="msg me" data-k="' + k + '"><div class="bub">' + esc(m.content) + '</div></div>';
      const body = m.pending && !m.content ? '<div class="ink"><i></i><i></i><i></i> 研墨中</div>' : md(m.content);
      return '<div class="msg ai' + (m.err ? ' err' : '') + '" data-k="' + k + '">' +
        '<div class="ai-h"><span class="seal sm">中和</span><span>依图谱证据作答</span>' + (m.note ? '<em>' + esc(m.note) + '</em>' : '') + '</div>' +
        '<div class="ai-body" data-k="' + k + '">' + body + '</div>' +
        (set.showEvidence ? evidenceHtml(m, k) : '') +
        '</div>';
    });
    if (!items.length) {
      el.list.innerHTML = '<div class="chat-empty">' +
        '<div class="hero-rule"><i></i><b>问 道</b><i></i></div>' +
        '<p>就孙光荣学术思想、辨证、方药、医案提问。<br>回答只依据图谱证据，每条都可点回图谱核验。</p>' +
        '<div class="ex">' + EXAMPLES.map(q => '<button class="exq" data-q="' + esc(q) + '">' + esc(q) + '</button>').join('') + '</div>' +
        '<div class="sgr-note" style="margin-top:14px">生成模型：' + esc(providerLabel()) + '　<a data-act="settings">设置 ›</a></div>' +
        '</div>';
      return;
    }
    if (onlyLast) {
      const k = conv.length - 1; const m = conv[k];
      const body = el.list.querySelector('.ai-body[data-k="' + k + '"]');
      if (body && m.role === 'assistant') { body.innerHTML = m.pending && !m.content ? '<div class="ink"><i></i><i></i><i></i> 研墨中</div>' : md(m.content); return; }
    }
    el.list.innerHTML = items.join('');
    scrollEnd();
  }
  function scrollEnd() { requestAnimationFrame(() => { el.list.scrollTop = el.list.scrollHeight; }); }
  function providerLabel() { return set.provider === 'poe' ? 'Poe · ' + set.poeModel : 'MiniMax · ' + set.mmModel + (set.mmSite === 'cn' ? '（国内站）' : '（国际站）'); }

  /* ---------------- 发送 ---------------- */
  function send(text) {
    text = (text || '').trim(); if (!text || busy) return;
    el.input.value = ''; autoGrow();
    conv.push({ role: 'user', content: text });
    const ai = { role: 'assistant', content: '', pending: true, ev: null };
    conv.push(ai); busy = true; setBusy(true); render(); persist();
    ensureIndex(() => {
      const r = idx.retrieve(text, { topSeeds: +set.topSeeds, maxEdges: +set.maxEdges, focus: focusEnt });
      ai.ev = { seeds: r.seeds, nodes: r.nodes, edges: r.edges };
      focusEnt = idx.entityNames(r, 3);
      const ctx = idx.context(r, +set.maxChars);
      render(); persist();

      const hist = conv.slice(0, -2).filter(m => !m.err && m.content).slice(-8).map(m => ({ role: m.role, content: m.content }));
      const messages = [{ role: 'system', content: SYSTEM }].concat(hist, [{ role: 'user', content: ctx + '\n\n———\n用户问题：' + text }]);
      const isPoe = set.provider === 'poe';
      const cfg = { provider: isPoe ? 'poe' : 'minimax', baseUrl: isPoe ? 'https://api.poe.com/v1' : SITE[set.mmSite] || SITE.cn,
        groupId: isPoe ? '' : set.mmGroup, apiKey: isPoe ? set.keyPoe : set.keyMm, model: isPoe ? set.poeModel : set.mmModel,
        temperature: +set.temperature, maxTokens: 2048, messages };

      const go = () => {
        let acc = '', tick = 0;
        curReq = LLM.start(cfg, {
          chunk(p) { acc += p; ai.content = acc; if (!(tick++ % 2)) render(true); },
          done() { ai.content = acc; ai.pending = false; busy = false; curReq = null; setBusy(false); render(); persist(); },
          error(msg) { ai.pending = false; ai.err = true; ai.content = '⚠ ' + msg + (msg.indexOf('Key') >= 0 || msg.indexOf('密钥') >= 0 ? '\n\n请在右上角「设置」中填入密钥。下方「依据」里的图谱证据仍可直接查阅。' : '\n\n下方「依据」里的图谱证据仍可直接查阅。'); busy = false; curReq = null; setBusy(false); render(); persist(); },
        });
      };
      if (isPoe) resolvePoeModel(cfg.model).then(({ model, note }) => { cfg.model = model; if (note) ai.note = note; go(); }).catch(go);
      else go();
    });
  }
  function stop() { if (curReq) { LLM.cancel(curReq); curReq = null; } const m = conv[conv.length - 1]; if (m && m.pending) { m.pending = false; if (!m.content) m.content = '（已停止）'; } busy = false; setBusy(false); render(); persist(); }
  function setBusy(b) { if (!el.send) return; el.send.textContent = b ? '停 止' : '送 出'; el.send.classList.toggle('stop', b); }
  function clearConv() { if (busy) stop(); conv = []; focusEnt = []; persist(); render(); toast('已清空对话'); }

  /* ---------------- 设置面板 ---------------- */
  function openSettings() { fillSettings(); $('#ov-chat').classList.add('on'); }
  function fillSettings() {
    const f = el.form;
    f.provider.value = set.provider; f.mmModel.value = set.mmModel; f.mmSite.value = set.mmSite; f.mmGroup.value = set.mmGroup; f.keyMm.value = set.keyMm;
    f.poeModel.value = set.poeModel; f.keyPoe.value = set.keyPoe;
    f.temperature.value = set.temperature; f.topSeeds.value = set.topSeeds; f.maxEdges.value = set.maxEdges; f.maxChars.value = set.maxChars;
    f.showEvidence.checked = !!set.showEvidence;
    syncProviderUI(); syncSliderLabels();
  }
  function syncProviderUI() {
    const p = el.form.provider.value;
    $('#cs-mm').hidden = p !== 'minimax'; $('#cs-poe').hidden = p !== 'poe';
    $$('#cs-prov .chip').forEach(c => c.classList.toggle('on', c.dataset.v === p));
    $$('#cs-site .chip').forEach(c => c.classList.toggle('on', c.dataset.v === el.form.mmSite.value));
  }
  function syncSliderLabels() {
    const f = el.form;
    $('#cs-temp-v').textContent = (+f.temperature.value).toFixed(2);
    $('#cs-seeds-v').textContent = f.topSeeds.value; $('#cs-edges-v').textContent = f.maxEdges.value; $('#cs-chars-v').textContent = f.maxChars.value;
  }
  function saveSettings() {
    const f = el.form;
    Object.assign(set, { provider: f.provider.value, mmModel: f.mmModel.value.trim() || DEF.mmModel, mmSite: f.mmSite.value, mmGroup: f.mmGroup.value.trim(), keyMm: f.keyMm.value.trim(),
      poeModel: f.poeModel.value.trim() || DEF.poeModel, keyPoe: f.keyPoe.value.trim(), temperature: +f.temperature.value, topSeeds: +f.topSeeds.value, maxEdges: +f.maxEdges.value, maxChars: +f.maxChars.value, showEvidence: f.showEvidence.checked });
    saveSet(); $('#ov-chat').classList.remove('on'); render(); toast('设置已保存');
  }
  async function selftest() {
    const out = $('#cs-test-out'); out.textContent = '正在连接…';
    const f = el.form; const isPoe = f.provider.value === 'poe';
    let model = isPoe ? f.poeModel.value.trim() : f.mmModel.value.trim(), note = '';
    if (isPoe) { const r = await resolvePoeModel(model); model = r.model; note = r.note; }
    const cfg = { provider: isPoe ? 'poe' : 'minimax', baseUrl: isPoe ? 'https://api.poe.com/v1' : SITE[f.mmSite.value], groupId: isPoe ? '' : f.mmGroup.value.trim(),
      apiKey: isPoe ? f.keyPoe.value.trim() : f.keyMm.value.trim(), model, temperature: 0.2, maxTokens: 40,
      messages: [{ role: 'user', content: '请只回复两个字：收到' }] };
    let acc = ''; const t0 = performance.now();
    LLM.start(cfg, {
      chunk(p) { acc += p; out.textContent = '接收中… ' + acc; },
      done() { out.textContent = '✔ ' + (isPoe ? 'Poe' : 'MiniMax') + ' / ' + model + ' 连通（' + ((performance.now() - t0) / 1000).toFixed(1) + 's）：' + acc.trim().slice(0, 60) + (note ? '\n' + note : ''); },
      error(m) { out.textContent = '✘ ' + m; },
    });
  }

  /* ---------------- 事件 ---------------- */
  function autoGrow() { const t = el.input; t.style.height = 'auto'; t.style.height = Math.min(t.scrollHeight, 132) + 'px'; }
  function bind() {
    el.send.onclick = () => busy ? stop() : send(el.input.value);
    el.input.addEventListener('input', autoGrow);
    el.input.addEventListener('keydown', e => { if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) { e.preventDefault(); send(el.input.value); } });
    $('#chat-settings').onclick = openSettings;
    $('#chat-clear').onclick = clearConv;

    el.list.addEventListener('click', e => {
      const a = e.target.closest('[data-act="settings"]'); if (a) { openSettings(); return; }
      const q = e.target.closest('.exq'); if (q) { send(q.dataset.q); return; }
      const ent = e.target.closest('[data-node]'); if (ent) { const nid = +ent.dataset.node; if (nid >= 0) { S.hist = []; openSheet(nid); } return; }
      const cite = e.target.closest('.cite'); if (cite) { jumpCite(cite); return; }
      const act = e.target.closest('[data-act]'); if (!act) return;
      const box = act.closest('.msg'); const k = +box.dataset.k; const m = conv[k]; if (!m) return;
      if (act.dataset.act === 'toggle') { m.evOpen = !m.evOpen; if (m.evOpen && !m.evTab) m.evTab = 'rel'; render(); box.scrollIntoView({ block: 'nearest' }); }
      if (act.dataset.act === 'tab') { m.evTab = act.dataset.tab; if (m.evTab === 'sub' && !m.svg) drawSub(m, k); render(); }
    });

    // 设置面板
    const f = el.form;
    $$('#cs-prov .chip').forEach(c => c.onclick = () => { f.provider.value = c.dataset.v; syncProviderUI(); });
    $$('#cs-site .chip').forEach(c => c.onclick = () => { f.mmSite.value = c.dataset.v; syncProviderUI(); });
    ['temperature', 'topSeeds', 'maxEdges', 'maxChars'].forEach(n => f[n].addEventListener('input', syncSliderLabels));
    $('#cs-save').onclick = saveSettings;
    $('#cs-test').onclick = selftest;
    $('#cs-check').onclick = async () => { const o = $('#cs-check-out'); o.textContent = '查询 Poe 目录…'; const r = await resolvePoeModel(f.poeModel.value.trim() || DEF.poeModel); o.textContent = r.note || ('✔ Poe 目录中有「' + r.model + '」'); };
    $$('#ov-chat .pw-eye').forEach(b => b.onclick = () => { const inp = b.previousElementSibling; inp.type = inp.type === 'password' ? 'text' : 'password'; });
  }
  function drawSub(m, k) {
    ensureIndex(() => {
      const w = Math.max(300, Math.min(el.list.clientWidth - 40, 720));
      const r = { seeds: m.ev.seeds, nodes: m.ev.nodes, edges: m.ev.edges };
      m.svg = idx.svg(r, { width: w, maxNodes: 60, maxLabels: 22, theme: document.documentElement.getAttribute('data-theme') === 'night' ? 'night' : 'paper' });
      render();
    });
  }
  function jumpCite(a) {
    const box = a.closest('.msg'); const k = +box.dataset.k; const m = conv[k]; if (!m || !m.ev) return;
    m.evOpen = true; m.evTab = 'rel'; render();
    const tgt = el.list.querySelector('.msg[data-k="' + k + '"] .rl[data-r="' + a.dataset.r + '"]');
    if (tgt) { tgt.scrollIntoView({ block: 'center', behavior: 'smooth' }); tgt.classList.add('flash'); setTimeout(() => tgt.classList.remove('flash'), 1600); }
  }

  /* ---------------- 对外 ---------------- */
  function init() {
    load();
    el = { list: $('#chat-list'), input: $('#chat-input'), send: $('#chat-send'), idx: $('#chat-idx'), form: $('#chat-form') };
    bind(); render();
  }
  function onEnter() { ensureIndex(null); render(); scrollEnd(); }
  /** 从实体详情跳来提问 */
  function ask(text) { go('chat'); el.input.value = text; autoGrow(); send(text); }
  function back() { const ov = $('#ov-chat'); if (ov.classList.contains('on')) { ov.classList.remove('on'); return true; } return false; }
  function onTheme() { conv.forEach(m => { m.svg = null; }); if (S.view === 'chat') render(); }

  return { init, onEnter, ask, back, warm, onTheme, get settings() { return set; } };
})();

window.CHAT = CHAT;
