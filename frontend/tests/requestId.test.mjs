import test from 'node:test';
import assert from 'node:assert/strict';
import { webcrypto } from 'node:crypto';
import { requestId } from '../src/requestId.ts';
test('uses the native UUID in a secure context',()=>assert.equal(requestId({randomUUID:()=> 'native-id',getRandomValues:()=>{throw Error('unexpected');}}),'native-id'));
test('LAN fallback generates independent request IDs without randomUUID',()=>{
  const insecure={getRandomValues:webcrypto.getRandomValues.bind(webcrypto)};
  const keys=Array.from({length:100},()=>requestId(insecure));
  assert.equal(new Set(keys).size,100);
  assert.ok(keys.every(k=>/^[a-f0-9]{32}$/.test(k)));
});
