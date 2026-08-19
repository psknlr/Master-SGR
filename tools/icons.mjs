#!/usr/bin/env node
/* 生成 API 26 以下所需的传统 PNG 启动图标（方形 + 圆形） */
import { chromium } from '/opt/node22/lib/node_modules/playwright/index.mjs';
import fs from 'fs';
import path from 'path';

const ROOT = path.resolve(path.dirname(new URL(import.meta.url).pathname), '..');
const RES = path.join(ROOT, 'android/app/src/main/res');

const SEAL = `
  <path fill="#A8322A" d="M32,22 L76,22 A10,10 0 0 1 86,32 L86,76 A10,10 0 0 1 76,86 L32,86 A10,10 0 0 1 22,76 L22,32 A10,10 0 0 1 32,22 Z"/>
  <path fill="#FBF3E4" d="M50.5,29 L57.5,29 L57.5,81 L50.5,81 Z"/>
  <path fill="#FBF3E4" fill-rule="evenodd" d="M37,40 L71,40 L71,72 L37,72 Z M43.5,46.5 L64.5,46.5 L64.5,65.5 L43.5,65.5 Z"/>`;

const CORNERS = `
  <g stroke="#A8322A" stroke-width="1.1" opacity=".2" fill="none">
    <path d="M14,14 L34,14 M14,14 L14,34 M94,94 L74,94 M94,94 L94,74"/>
  </g>`;

function svg(round) {
  const clip = round
    ? `<clipPath id="c"><circle cx="54" cy="54" r="54"/></clipPath>`
    : `<clipPath id="c"><rect x="4" y="4" width="100" height="100" rx="18"/></clipPath>`;
  return `<svg xmlns="http://www.w3.org/2000/svg" width="108" height="108" viewBox="0 0 108 108">
    <defs>${clip}</defs>
    <g clip-path="url(#c)">
      <rect width="108" height="108" fill="#F3E9D6"/>
      ${round ? '' : CORNERS}
      <g transform="translate(54,54) scale(0.88) translate(-54,-54)">${SEAL}</g>
    </g>
  </svg>`;
}

const SIZES = { mdpi: 48, hdpi: 72, xhdpi: 96, xxhdpi: 144, xxxhdpi: 192 };

const browser = await chromium.launch({ executablePath: '/opt/pw-browsers/chromium-1194/chrome-linux/chrome', args: ['--no-sandbox'] });
for (const [dpi, px] of Object.entries(SIZES)) {
  for (const [name, round] of [['ic_launcher', false], ['ic_launcher_round', true]]) {
    const page = await browser.newPage({ viewport: { width: px, height: px } });
    await page.setContent(`<style>html,body{margin:0;padding:0;background:transparent}svg{display:block;width:${px}px;height:${px}px}</style>${svg(round)}`);
    const dir = path.join(RES, 'mipmap-' + dpi);
    fs.mkdirSync(dir, { recursive: true });
    await page.screenshot({ path: path.join(dir, name + '.png'), omitBackground: true });
    await page.close();
  }
}
// 供 README / 商店用的大图
{
  const page = await browser.newPage({ viewport: { width: 512, height: 512 } });
  await page.setContent(`<style>html,body{margin:0;background:transparent}svg{display:block;width:512px;height:512px}</style>${svg(false)}`);
  fs.mkdirSync(path.join(ROOT, 'tools/build'), { recursive: true });
  await page.screenshot({ path: path.join(ROOT, 'tools/build/icon-512.png'), omitBackground: true });
  await page.close();
}
await browser.close();
console.log('icons generated');
