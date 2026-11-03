/* Only versioned, public app-shell files enter Cache Storage. Never API data. */
const CACHE='timesync-shell-__VERSION__';
const SHELL=__SHELL__;
self.addEventListener('install',event=>event.waitUntil(caches.open(CACHE).then(cache=>cache.addAll(SHELL))));
self.addEventListener('activate',event=>event.waitUntil((async()=>{
  for(const key of await caches.keys()) if(key.startsWith('timesync-shell-')&&key!==CACHE) await caches.delete(key);
  await self.clients.claim();
})()));
self.addEventListener('message',event=>{if(event.data?.type==='ACTIVATE_UPDATE')self.skipWaiting();});
self.addEventListener('fetch',event=>{
  const request=event.request,url=new URL(request.url);
  if(url.origin!==self.location.origin)return;
  if(url.pathname.startsWith('/api/')){
    event.respondWith(fetch(request,{cache:'no-store'}).catch(()=>new Response(JSON.stringify({detail:'当前离线，没有提交或缓存此次请求',code:'offline'}),{status:503,headers:{'Content-Type':'application/json','Cache-Control':'no-store'}})));
    return;
  }
  if(request.method!=='GET')return;
  if(request.mode==='navigate'){
    event.respondWith(caches.open(CACHE).then(cache=>cache.match('/index.html')).then(hit=>hit||fetch(request)));
    return;
  }
  if(SHELL.includes(url.pathname)&&!url.search){
    event.respondWith(caches.open(CACHE).then(cache=>cache.match(url.pathname)).then(hit=>hit||fetch(request)));
  }
});
