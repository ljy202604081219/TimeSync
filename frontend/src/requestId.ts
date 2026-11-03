// randomUUID is secure-context-only; getRandomValues also works on LAN HTTP.
export function requestId(source:Pick<Crypto,'getRandomValues'> & Partial<Pick<Crypto,'randomUUID'>>=globalThis.crypto):string {
  if(typeof source.randomUUID==='function')return source.randomUUID();
  const bytes=source.getRandomValues(new Uint8Array(16));
  return Array.from(bytes,b=>b.toString(16).padStart(2,'0')).join('');
}
