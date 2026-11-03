import { useEffect, useState } from 'react';
type InstallEvent = Event & { prompt():Promise<void>; userChoice:Promise<{outcome:string}> };
export default function PWA(){
  const [online,setOnline]=useState(navigator.onLine),[notice,setNotice]=useState(''),[waiting,setWaiting]=useState<ServiceWorker|null>(null),[install,setInstall]=useState<InstallEvent|null>(null),[help,setHelp]=useState(false);
  useEffect(()=>{
    let alive=true,reg:ServiceWorkerRegistration|undefined;
    const net=()=>{setOnline(navigator.onLine);setNotice(navigator.onLine?'网络已恢复，正在重新读取数据。':'');};
    const offer=(e:Event)=>{e.preventDefault();setInstall(e as InstallEvent);};
    const installed=()=>setInstall(null);
    const refresh=()=>{if(navigator.onLine)reg?.update().catch(()=>{});};
    window.addEventListener('online',net);window.addEventListener('offline',net);
    window.addEventListener('beforeinstallprompt',offer);window.addEventListener('appinstalled',installed);window.addEventListener('focus',refresh);
    if(window.isSecureContext && 'serviceWorker' in navigator && import.meta.env.PROD){
      navigator.serviceWorker.register('/sw.js',{updateViaCache:'none'}).then(r=>{
        reg=r;if(!alive)return;
        if(r.waiting)setWaiting(r.waiting);
        r.addEventListener('updatefound',()=>{const sw=r.installing;sw?.addEventListener('statechange',()=>{if(sw.state==='installed'&&navigator.serviceWorker.controller&&alive)setWaiting(sw);});});
      }).catch(()=>setNotice('安装组件暂不可用，仍可在线使用。'));
    }
    const timer=window.setInterval(refresh,15*60*1000);
    return()=>{alive=false;clearInterval(timer);window.removeEventListener('online',net);window.removeEventListener('offline',net);window.removeEventListener('beforeinstallprompt',offer);window.removeEventListener('appinstalled',installed);window.removeEventListener('focus',refresh);};
  },[]);
  useEffect(()=>{if(!notice)return;const t=setTimeout(()=>setNotice(''),7000);return()=>clearTimeout(t);},[notice]);
  function update(){if(!waiting)return;if(!window.confirm('更新会重新加载页面。请先保存正在填写的表单，确认立即更新？'))return;navigator.serviceWorker.addEventListener('controllerchange',()=>location.reload(),{once:true});waiting.postMessage({type:'ACTIVATE_UPDATE'});}
  useEffect(()=>{const open=()=>setHelp(true);window.addEventListener("timesync-install",open);return()=>window.removeEventListener("timesync-install",open);},[]);
  return <><div className="pwa-status" role="status">
    {!online&&<span>当前离线 · 仅可打开应用外壳，不能读取或提交日程。</span>}
    {notice&&<span>{notice}</span>}
    {waiting&&<button onClick={update}>发现新版本 · 保存后更新</button>}
  </div><button className="pwa-install" onClick={async()=>{if(install){await install.prompt();await install.userChoice;setInstall(null);}else setHelp(!help);}}>安装到桌面</button>
    {help&&<aside className="install-help"><button onClick={()=>setHelp(false)} aria-label="关闭安装说明">×</button><b>安装 TimeSync</b><p>Android：浏览器菜单 → 安装应用 / 添加到主屏幕。</p><p>iPhone：Safari 分享 → 添加到主屏幕 → 以网页App打开。</p><p>需 HTTPS 或本机 localhost。安装后仍需联网登录和使用业务功能。</p></aside>}</>;
}
