import { createHash } from 'node:crypto';
import { readFile, writeFile, readdir } from 'node:fs/promises';
export default function pwaBuild() {
  return { name: 'timesync-app-shell', async closeBundle() {
    const assets=(await readdir('dist/assets')).filter(n=>/\.(js|css)$/.test(n)).sort();
    const shell=['/index.html','/manifest.webmanifest','/icons/icon-192.png','/icons/icon-512.png','/icons/apple-touch-icon.png',...assets.map(n=>'/assets/'+n)];
    const inputs=await Promise.all(shell.map(n=>readFile('dist'+n)));
    const template=await readFile('sw-template.js','utf8');
    const version=createHash('sha256').update(Buffer.concat(inputs)).update(template).digest('hex').slice(0,16);
    await writeFile('dist/sw.js',template.replace('__VERSION__',version).replace('__SHELL__',JSON.stringify(shell)));
  }};
}
