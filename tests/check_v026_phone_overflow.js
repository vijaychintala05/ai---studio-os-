// Run against a running test copy: NODE_PATH=$(npm root -g) node tests/check_v026_phone_overflow.js
// Opens every screen at phone width (390px) and reports any that make the page scroll sideways. Fictional login only.
const {chromium}=require('playwright');
(async()=>{
 const b=await chromium.launch(); const p=await b.newPage({viewport:{width:390,height:844}});
 const errs=[]; p.on('pageerror',e=>errs.push(e.message));
 await p.goto('http://127.0.0.1:8765/');
 await p.fill('#loginUsername','admin'); await p.fill('#loginPassword','stage1-test-password-very-long');
 await p.click('#loginLayer button[type=submit]'); await p.waitForSelector('#sidebar',{state:'attached'}); await p.waitForTimeout(1500);
 const views=await p.$$eval('[data-view]',els=>[...new Set(els.map(e=>e.dataset.view))]);
 const bad=[];
 for(const v of views){
   await p.evaluate(v=>{try{switchView(v)}catch(e){}},v); await p.waitForTimeout(500);
   const r=await p.evaluate(()=>{const w=window.innerWidth;const over=document.documentElement.scrollWidth-w;const wide=[...document.querySelectorAll('#mainContent *')].filter(e=>{const r=e.getBoundingClientRect();return r.width>0&&r.right>w+1&&!e.closest('.table-wrap')&&getComputedStyle(e).position!=='fixed'}).slice(0,3).map(e=>e.tagName+'.'+e.className);return {over,wide}});
   if(r.over>1||r.wide.length)bad.push(v+' over='+r.over+' '+r.wide.join(','));
 }
 console.log('views',views.length,'overflowing:',JSON.stringify(bad,null,1)); console.log('errs',JSON.stringify(errs));
 await b.close();
})().catch(e=>{console.log('FAIL',e.message.slice(0,300));process.exit(1)});
