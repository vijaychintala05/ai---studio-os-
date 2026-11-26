const http=require('http'),fs=require('fs');
const log=fs.createWriteStream('/tmp/aud/proxy.log',{flags:'a'});
http.createServer((req,res)=>{
  log.write(JSON.stringify({t:Date.now(),m:req.method,p:req.url.split('?')[0],ua:req.headers['user-agent']||''})+'\n');
  const up=http.request({host:'127.0.0.1',port:8770,path:req.url,method:req.method,headers:req.headers},r=>{res.writeHead(r.statusCode,r.headers);r.pipe(res)});
  up.on('error',e=>{res.writeHead(502);res.end('bad gateway')});req.pipe(up);
}).listen(8780,'127.0.0.1');
