import { chromium } from '/opt/node22/lib/node_modules/playwright/index.mjs';
import fs from 'fs';
const OUT='tools/build/shots'; fs.mkdirSync(OUT,{recursive:true});
const b = await chromium.launch({executablePath:'/opt/pw-browsers/chromium-1194/chrome-linux/chrome',args:['--no-sandbox']});
const p = await b.newPage({viewport:{width:1440,height:1000},deviceScaleFactor:1.5});
const errs=[]; p.on('pageerror',e=>errs.push('PAGEERROR '+e.message));
p.on('console',m=>{if(m.type()==='error')errs.push('CONSOLE '+m.text().slice(0,200));});
await p.goto('http://127.0.0.1:7861/',{waitUntil:'domcontentloaded',timeout:60000});
await p.waitForSelector('textarea',{timeout:60000}); await p.waitForTimeout(3000);
await p.screenshot({path:OUT+'/rag-1-initial.png'});
// 提问（无 API Key，应看到检索面板照常填充 + 明确的报错提示）
const ta = p.locator('textarea').first();
await ta.click(); await ta.fill('什么是中和思想？中和组方的基本原则是什么？');
await p.getByRole('button',{name:/问\s*道/}).click();
await p.waitForTimeout(6000);
await p.screenshot({path:OUT+'/rag-2-answer.png'});
// 切到三元组/实体/上下文标签
for (const [name,file] of [['实体','rag-3-entities'],['送入模型的上下文','rag-4-context']]) {
  try { await p.getByRole('tab',{name}).click(); await p.waitForTimeout(900);
        await p.screenshot({path:`${OUT}/${file}.png`}); } catch(e){ errs.push('tab '+name+': '+e.message); }
}
try { await p.getByText('模型与检索设置').click(); await p.waitForTimeout(700);
      await p.screenshot({path:OUT+'/rag-5-settings.png',fullPage:true}); } catch(e){ errs.push('settings: '+e.message); }
const stat = await p.locator('text=/本轮检索/').first().textContent().catch(()=>null);
console.log('status line:', stat);
console.log(errs.length? 'ERRORS:\n'+errs.join('\n') : 'no page errors');
await b.close();
