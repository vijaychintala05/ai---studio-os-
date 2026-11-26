// A screenshot-mouse-keyboard driver. No navigation, no script execution, no page inspection.
const {chromium}=require('playwright'),http=require('http'),fs=require('fs'),path=require('path');
const [port,startUrl,dir]=[+process.argv[2],process.argv[3],process.argv[4]];
fs.mkdirSync(dir+'/downloads',{recursive:true});
const actions=fs.createWriteStream(dir+'/actions.jsonl',{flags:'a'});
(async()=>{
 const b=await chromium.launch(); const ctx=await b.newContext({viewport:{width:1366,height:768},acceptDownloads:true});
 const p=await ctx.newPage(); let chooser=null,shots=0,n=0; const errors=[];
 p.on('filechooser',c=>{chooser=c}); p.on('dialog',d=>d.accept());
 p.on('download',async d=>{await d.saveAs(dir+'/downloads/'+d.suggestedFilename())});
 p.on('pageerror',e=>errors.push(String(e).slice(0,200)));
 await p.goto(startUrl);
 const OK=/^\/tmp\/aud\/assets\//;
 http.createServer(async(req,res)=>{
  const u=new URL(req.url,'http://x'),q=u.searchParams,cmd=u.pathname.slice(1);let out={ok:true};
  try{
   if(cmd==='shot'){shots++;const f=`${dir}/shot-${String(shots).padStart(3,'0')}.png`;await p.screenshot({path:f});out={ok:true,file:f}}
   else if(cmd==='click'){await p.mouse.click(+q.get('x'),+q.get('y'))}
   else if(cmd==='dblclick'){await p.mouse.dblclick(+q.get('x'),+q.get('y'))}
   else if(cmd==='rightclick'){await p.mouse.click(+q.get('x'),+q.get('y'),{button:'right'})}
   else if(cmd==='move'){await p.mouse.move(+q.get('x'),+q.get('y'))}
   else if(cmd==='type'){await p.keyboard.type(q.get('text')||'',{delay:15})}
   else if(cmd==='press'){await p.keyboard.press(q.get('key'))}
   else if(cmd==='scroll'){await p.mouse.move(+(q.get('x')||683),+(q.get('y')||400));await p.mouse.wheel(0,+q.get('dy')||400)}
   else if(cmd==='wait'){await p.waitForTimeout(Math.min(+q.get('ms')||500,5000))}
   else if(cmd==='back'){await p.goBack()}
   else if(cmd==='upload'){const f=q.get('path')||'';if(!OK.test(f)||f.includes('..'))throw new Error('only files in /tmp/aud/assets can be uploaded');if(!chooser)throw new Error('no file dialog is open; click an upload control first');await chooser.setFiles(f);chooser=null}
   else if(cmd==='downloads'){out={ok:true,files:fs.readdirSync(dir+'/downloads').map(x=>dir+'/downloads/'+x)}}
   else if(cmd==='finish'){out={ok:true,errors,shots,actions:n};res.end(JSON.stringify(out));actions.end();await b.close();process.exit(0)}
   else throw new Error('unknown command');
   if(cmd!=='shot'&&cmd!=='downloads'){n++;actions.write(JSON.stringify({t:Date.now(),cmd,args:Object.fromEntries(q)})+'\n')}
   await p.waitForTimeout(250);
  }catch(e){out={ok:false,error:String(e.message).slice(0,200)}}
  res.setHeader('content-type','application/json');res.end(JSON.stringify(out));
 }).listen(port,'127.0.0.1');
})();
