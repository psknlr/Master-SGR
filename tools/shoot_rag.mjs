import { chromium } from '/opt/node22/lib/node_modules/playwright/index.mjs';
import fs from 'fs';
const OUT='tools/build/shots'; fs.mkdirSync(OUT,{recursive:true});
const b = await chromium.launch({executablePath:'/opt/pw-browsers/chromium-1194/chrome-linux/chrome',args:['--no-sandbox']});
const errs=[];

async function drive(port, tag, expectSettings){
  const p = await b.newPage({viewport:{width:1500,height:1060},deviceScaleFactor:1.4});
  p.on('pageerror',e=>errs.push(`[${tag}] PAGEERROR `+e.message));
  p.on('console',m=>{if(m.type()==='error')errs.push(`[${tag}] CONSOLE `+m.text().slice(0,160));});
  await p.goto(`http://127.0.0.1:${port}/`,{waitUntil:'domcontentloaded',timeout:60000});
  await p.waitForSelector('textarea',{timeout:60000}); await p.waitForTimeout(2500);

  const hasSettings = await p.getByText('模型与检索设置').isVisible().catch(()=>false);
  console.log(`[${tag}] 设置面板可见 = ${hasSettings} (期望 ${expectSettings})`);

  const ta = p.locator('textarea').first();
  await ta.click(); await ta.fill('什么是中和思想？中和组方的基本原则是什么？');
  await p.getByRole('button',{name:/问\s*道/}).click();
  await p.waitForTimeout(9000);
  await p.screenshot({path:`${OUT}/rag-${tag}-1-graph.png`});
  const stat = await p.locator('text=/本轮检索/').first().textContent().catch(()=>null);
  console.log(`[${tag}] ${stat}`);
  const err = await p.locator('text=/未配置|API Key/').first().textContent().catch(()=>null);
  console.log(`[${tag}] 生成提示: ${(err||'').slice(0,60)}`);
  for (const [name,file] of [['三元组与佐证',`rag-${tag}-2-triples`],['送入模型的上下文',`rag-${tag}-3-ctx`]]) {
    try{ await p.getByRole('tab',{name}).click(); await p.waitForTimeout(800);
         await p.screenshot({path:`${OUT}/${file}.png`}); }catch(e){ errs.push(`[${tag}] tab ${name}: `+e.message); }
  }
  await p.close();
}
await drive(7862,'hidden',false);
await drive(7863,'shown',true);
console.log(errs.length? 'ERRORS:\n'+errs.join('\n') : 'no page errors');
await b.close();
