/* 问道页面的浏览器验证：用 NativeApp 桩模拟 Java 流式桥，检查渲染、依据面板、设置与报错 */
import { chromium } from '/opt/node22/lib/node_modules/playwright/index.mjs';
import http from 'http'; import fs from 'fs'; import path from 'path';
const ROOT = path.resolve(path.dirname(new URL(import.meta.url).pathname), '..');
const WEB = path.join(ROOT, 'android/app/src/main/assets/web'), OUT = path.join(ROOT, 'tools/build/shots');
const MIME = { '.html': 'text/html', '.js': 'application/javascript', '.css': 'text/css', '.json': 'application/json' };
const srv = http.createServer((req, res) => { let p = decodeURIComponent(req.url.split('?')[0]); if (p === '/') p = '/index.html';
  const f = path.join(WEB, p); if (!f.startsWith(WEB) || !fs.existsSync(f)) { res.writeHead(404); return res.end(); }
  res.writeHead(200, { 'Content-Type': MIME[path.extname(f)] || 'application/octet-stream' }); fs.createReadStream(f).pipe(res); });
await new Promise(r => srv.listen(8812, r));

const SHIM = `
window.NativeApp = {
  setTheme(){}, ready(){}, share(){},
  _timers: {},
  llmStart(id, cfgJson) {
    const cfg = JSON.parse(cfgJson); window.__lastCfg = cfg;
    if (!cfg.apiKey) { setTimeout(()=>__llmEvent(id,'error','未配置 MiniMax API Key（在 MiniMax 开放平台「账户管理 - 接口密钥」获取）'),80); return; }
    const answer = '## 中和思想概要\\n\\n「中和思想」是孙光荣学术体系的核心，据 [R1]，"中和组方"是在中和思想指导下、根据中和辨证的结果采用的不偏不倚、调平燮和的组方用药方法（D1#c0072）。\\n\\n**基本原则**（据 [R4]）：\\n1. 遵经方之旨，不泥经方用药\\n2. 中病即止，不滥伐无过\\n3. 用药配伍讲求阴阳结合、动静结合、升降相应\\n\\n- 以上均属**孙光荣原创**论断。\\n\\n本回答仅供学术研究与教学参考，不能替代执业医师的诊断与处方。';
    let i = 0; const step = () => { if (i >= answer.length) { __llmEvent(id,'done',''); return; }
      const n = 6 + Math.floor(Math.random()*8); __llmEvent(id,'chunk',answer.slice(i,i+n)); i += n; this._timers[id] = setTimeout(step, 18); };
    setTimeout(step, 120);
  },
  llmCancel(id){ clearTimeout(this._timers[id]); },
  httpGet(id, url){ setTimeout(()=>__llmEvent(id,'http',JSON.stringify({status:200, body: JSON.stringify({data:[{id:'claude-sonnet-4.6'},{id:'claude-opus-4.8'},{id:'minimax-m3'}]})})),60); },
};`;

const b = await chromium.launch({ executablePath: '/opt/pw-browsers/chromium-1194/chrome-linux/chrome', args: ['--no-sandbox'] });
const ctx = await b.newContext({ viewport: { width: 393, height: 830 }, deviceScaleFactor: 2, isMobile: true, hasTouch: true });
await ctx.addInitScript(SHIM);
await ctx.addInitScript(() => { localStorage.setItem('sgr-chat-settings', JSON.stringify({ keyMm: 'test-key' })); });
const p = await ctx.newPage(); const errs = [];
p.on('pageerror', e => errs.push('PAGEERROR ' + e.message)); p.on('console', m => { if (m.type() === 'error' && !/favicon/.test(m.text())) errs.push('CONSOLE ' + m.text().slice(0, 200)); });
await p.goto('http://127.0.0.1:8812/', { waitUntil: 'load' });
await p.waitForFunction(() => document.querySelector('#loading').style.display === 'none', null, { timeout: 90000 });
const shot = n => p.screenshot({ path: path.join(OUT, n + '.png') });

await p.evaluate(() => go('home')); await p.waitForTimeout(300); await shot('c1-home');
await p.evaluate(() => go('chat')); await p.waitForTimeout(400); await shot('c2-chat-empty');
// 等索引就绪
await p.waitForFunction(() => !document.querySelector('#chat-idx') || document.querySelector('#chat-idx').hidden, null, { timeout: 60000 });
const idxMs = await p.evaluate(() => performance.now());
await p.click('.exq'); await p.waitForTimeout(600); await shot('c3-chat-streaming');
await p.waitForFunction(() => !document.querySelector('.ink'), null, { timeout: 30000 }); await p.waitForTimeout(300);
await shot('c4-chat-answer');
const cfg = await p.evaluate(() => window.__lastCfg);
console.log('sent cfg: provider=%s model=%s baseUrl=%s msgs=%d ctxChars=%d', cfg.provider, cfg.model, cfg.baseUrl, cfg.messages.length, cfg.messages[cfg.messages.length-1].content.length);
console.log('system prompt present:', cfg.messages[0].role === 'system' && cfg.messages[0].content.includes('图谱证据'));
// 引文跳转
await p.click('.cite'); await p.waitForTimeout(700); await shot('c5-evidence-rel');
// 子图
await p.click('[data-act="tab"][data-tab="sub"]'); await p.waitForTimeout(1200); await shot('c6-evidence-sub');
const svgOk = await p.evaluate(() => !!document.querySelector('.ev-sub svg'));
// 实体 → 详情抽屉
await p.click('[data-act="tab"][data-tab="ent"]'); await p.waitForTimeout(300); await p.click('.ev-ent .chip'); await p.waitForTimeout(600); await shot('c7-entity-sheet');
const sheetOpen = await p.evaluate(() => document.querySelector('#sheet').classList.contains('on'));
// 抽屉「问 AI」
await p.click('#sh-ask'); await p.waitForTimeout(500);
await p.waitForFunction(() => !document.querySelector('.ink'), null, { timeout: 30000 }); await p.waitForTimeout(200); await shot('c8-ask-from-sheet');
const turns = await p.evaluate(() => document.querySelectorAll('.msg').length);
// 设置
await p.click('#chat-settings'); await p.waitForTimeout(400); await shot('c9-settings');
await p.click('#cs-prov .chip[data-v="poe"]'); await p.waitForTimeout(200); await p.click('#cs-check'); await p.waitForTimeout(500);
const chk = await p.textContent('#cs-check-out'); await shot('c10-settings-poe');
// 返回键链：先关设置
const back1 = await p.evaluate(() => window.__appBack()); const ovClosed = await p.evaluate(() => !document.querySelector('#ov-chat').classList.contains('on'));
// 无密钥报错路径
await p.reload({ waitUntil: 'load' }); await p.waitForFunction(() => document.querySelector('#loading').style.display === 'none', null, { timeout: 90000 });
await p.evaluate(() => go('chat')); await p.waitForFunction(() => document.querySelector('#chat-idx').hidden, null, { timeout: 60000 });
const persisted = await p.evaluate(() => document.querySelectorAll('.msg').length);
await p.evaluate(() => { CHAT.settings.keyMm = ''; });   // 直接清空密钥，走无密钥报错路径
await p.fill('#chat-input', '失眠该用什么方'); await p.click('#chat-send'); await p.waitForTimeout(1500); await shot('c11-nokey-error');
const errShown = await p.evaluate(() => (document.querySelector('.msg.err') || {}).textContent || '');
// 夜读
await p.evaluate(() => setTheme('night')); await p.waitForTimeout(500); await shot('c12-night');

console.log(JSON.stringify({ idxReadyAt_ms: Math.round(idxMs), svgOk, sheetOpen, turnsAfterAsk: turns, poeCheck: chk, backClosedSettings: back1 && ovClosed, persistedMsgs: persisted, noKeyErr: errShown.slice(0, 40) }, null, 1));
console.log(errs.length ? 'ERRORS:\n' + errs.join('\n') : 'no page errors');
await b.close(); srv.close();
