import test from 'node:test';
import assert from 'node:assert/strict';
import vm from 'node:vm';
import {readFile} from 'node:fs/promises';
const source=await readFile(new URL('../dist/sw.js',import.meta.url),'utf8');
const manifest=JSON.parse(await readFile(new URL('../public/manifest.webmanifest',import.meta.url),'utf8'));
function worker(offline=false){
  const handlers={},added=[],removed=[],fetches=[],skips=[];
  const shell=new Response('<div id="root"></div>',{headers:{'Content-Type':'text/html'}});
  const cache={addAll:async paths=>added.push(...paths),match:async path=>path==='/index.html'?shell.clone():undefined};
  const self={location:{origin:'https://timesync.test'},clients:{claim:async()=>{}},skipWaiting:()=>skips.push(true),addEventListener:(kind,fn)=>handlers[kind]=fn};
  vm.runInNewContext(source,{self,URL,Response,caches:{open:async()=>cache,keys:async()=>['other-app','timesync-shell-old'],delete:async k=>removed.push(k)},fetch:async(req,opts)=>{fetches.push({req,opts});if(offline)throw Error('offline');return new Response('network');}});
  async function dispatch(kind,event){let pending;handlers[kind]({...event,waitUntil:p=>pending=p,respondWith:p=>pending=p});return await pending;}
  return {dispatch,added,removed,fetches,skips};
}
test('manifest provides standalone, stable start, safe icons and iOS hook',async()=>{
  assert.equal(manifest.name,'TimeSync');assert.equal(manifest.display,'standalone');assert.equal(manifest.start_url,'/');
  assert.ok(manifest.icons.some(i=>i.sizes==='512x512'&&i.purpose.includes('maskable')));
  assert.match(await readFile(new URL('../index.html',import.meta.url),'utf8'),/apple-touch-icon/);
});
test('install precaches only public shell and waits for user-approved update',async()=>{
  const w=worker();await w.dispatch('install',{});
  assert.ok(w.added.includes('/index.html'));assert.ok(w.added.some(x=>x.startsWith('/assets/')));
  assert.ok(w.added.every(x=>!x.includes('/api/')&&!x.includes('token')));assert.equal(w.skips.length,0);
  await w.dispatch('message',{data:{type:'ACTIVATE_UPDATE'}});assert.equal(w.skips.length,1);
});
test('activation deletes only older TimeSync shell caches',async()=>{
  const w=worker();await w.dispatch('activate',{});assert.deepEqual(w.removed,['timesync-shell-old']);
});
test('private API GET uses network no-store and never cache lookup',async()=>{
  const w=worker();const r=await w.dispatch('fetch',{request:{url:'https://timesync.test/api/v1/agenda',method:'GET'}});
  assert.equal(await r.text(),'network');assert.equal(w.fetches[0].opts.cache,'no-store');assert.equal(w.added.length,0);
});
test('offline API mutation is rejected without queued success or cache',async()=>{
  const w=worker(true);const r=await w.dispatch('fetch',{request:{url:'https://timesync.test/api/tasks',method:'POST'}});
  assert.equal(r.status,503);assert.equal((await r.json()).code,'offline');assert.equal(w.added.length,0);
});
test('offline navigation returns the cached shell, not private state',async()=>{
  const w=worker(true);const r=await w.dispatch('fetch',{request:{url:'https://timesync.test/',method:'GET',mode:'navigate'}});
  assert.match(await r.text(),/id="root"/);assert.equal(w.fetches.length,0);
});
test('third-party and non-allowlisted assets are not cached',async()=>{
  const w=worker();assert.equal(await w.dispatch('fetch',{request:{url:'https://external.test/x',method:'GET'}}),undefined);
  assert.equal(await w.dispatch('fetch',{request:{url:'https://timesync.test/private-photo.png',method:'GET'}}),undefined);
});
