#!/usr/bin/env node
/* 用无头浏览器按手机视口截图，检查页面报错与视觉效果 */
import { chromium } from '/opt/node22/lib/node_modules/playwright/index.mjs';
import http from 'http';
import fs from 'fs';
import path from 'path';

const ROOT = path.resolve(path.dirname(new URL(import.meta.url).pathname), '..');
const WEB = path.join(ROOT, 'android/app/src/main/assets/web');
const OUT = path.join(ROOT, 'tools/build/shots');
fs.mkdirSync(OUT, { recursive: true });

const MIME = { '.html': 'text/html', '.js': 'application/javascript', '.css': 'text/css', '.json': 'application/json' };
const server = http.createServer((req, res) => {
  let p = decodeURIComponent(req.url.split('?')[0]);
  if (p === '/') p = '/index.html';
  const f = path.join(WEB, p);
  if (!f.startsWith(WEB) || !fs.existsSync(f)) { res.writeHead(404); return res.end('nf'); }
  res.writeHead(200, { 'Content-Type': MIME[path.extname(f)] || 'application/octet-stream' });
  fs.createReadStream(f).pipe(res);
});
await new Promise(r => server.listen(8811, r));

const browser = await chromium.launch({ executablePath: '/opt/pw-browsers/chromium-1194/chrome-linux/chrome', args: ['--no-sandbox'] });
const ctx = await browser.newContext({
  viewport: { width: 393, height: 830 }, deviceScaleFactor: 2, isMobile: true, hasTouch: true,
});
const page = await ctx.newPage();
const errs = [];
page.on('console', m => { if (m.type() === 'error') errs.push('CONSOLE ' + m.text()); });
page.on('pageerror', e => errs.push('PAGEERROR ' + e.message));

await page.goto('http://127.0.0.1:8811/', { waitUntil: 'load' });
await page.waitForFunction(() => document.querySelector('#loading') &&
  document.querySelector('#loading').style.display === 'none', null, { timeout: 60000 })
  .catch(() => errs.push('TIMEOUT waiting for data load'));
await page.waitForTimeout(700);

const shot = async (name) => { await page.screenshot({ path: path.join(OUT, name + '.png') }); };

await shot('1-home');
await page.evaluate(() => window.scrollTo && document.querySelector('#v-home').scrollTo(0, 900));
await page.waitForTimeout(250); await shot('2-home-team');

await page.evaluate(() => go('graph')); await page.waitForTimeout(900); await shot('3-graph');
await page.evaluate(() => { const i = S.D.nodes.findIndex(n => n.g > 80); GR.centerOn(i, 3.4); });
await page.waitForTimeout(900); await shot('3b-graph-zoom');
await page.evaluate(() => { const i = S.D.nodes.findIndex(n => n.g > 60); openSheet(i); });
await page.waitForTimeout(600); await shot('4-sheet');
await page.evaluate(() => { closeSheet(); const i = S.D.nodes.findIndex(n => n.g > 20 && n.g < 40); enterFocus(i); });
await page.waitForTimeout(600); await shot('5-focus');
await page.evaluate(() => { exitFocus(); document.querySelector('#ov-filter').classList.add('on'); });
await page.waitForTimeout(400); await shot('6-filter');
await page.evaluate(() => { closeOverlays(); go('search'); document.querySelector('#q').value = '中和'; runSearch(); });
await page.waitForTimeout(500); await shot('7-search');
await page.evaluate(() => go('lib')); await page.waitForTimeout(400); await shot('8-lib');
await page.evaluate(() => go('about')); await page.waitForTimeout(400); await shot('9-about');
await page.evaluate(() => { setTheme('night'); go('graph'); }); await page.waitForTimeout(900); await shot('10-night');

// 横屏（旋转后聚焦视图需重算）
await page.evaluate(() => { setTheme('paper'); go('graph'); const i = S.D.nodes.findIndex(n => n.g > 20 && n.g < 40); enterFocus(i); });
await page.setViewportSize({ width: 830, height: 393 });
await page.waitForTimeout(700); await shot('11-landscape-focus');
await page.setViewportSize({ width: 393, height: 830 });
await page.waitForTimeout(500);

const perf = await page.evaluate(() => {
  const t0 = performance.now(); GR.moving = false; GR.draw();
  const vec = performance.now() - t0;
  const t1 = performance.now(); GR.renderBase();
  return { vectorDrawMs: +vec.toFixed(1), baseRenderMs: +(performance.now() - t1).toFixed(1),
           scale: +GR.scale.toFixed(3), nodes: S.n, shown: S.shownN };
});
console.log('perf', JSON.stringify(perf));
console.log(errs.length ? 'ERRORS:\n' + errs.join('\n') : 'no console/page errors');

await browser.close();
server.close();
