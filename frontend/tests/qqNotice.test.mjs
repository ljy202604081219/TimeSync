import test from 'node:test';
import assert from 'node:assert/strict';
import {confirmationMode,notificationTime} from '../src/qqNotice.ts';

test('normal class and legacy timed notifications default to events',()=>{
  assert.equal(confirmationMode({category:'course'}),'event');
  assert.equal(confirmationMode({category:'report',extraction:{start:'2026-11-04T08:00:00+08:00'}}),'event');
  assert.equal(confirmationMode({category:'important',suggested_mode:'event'}),'event');
  assert.match(notificationTime({category:'course',extraction:{start:'2026-11-04T08:00:00+08:00'}}),/^上课时间：/);
  assert.doesNotMatch(notificationTime({category:'course'}),/截止/);
});

test('submissions keep DDL and uncertain notifications require a choice',()=>{
  assert.equal(confirmationMode({category:'assignment'}),'task');
  assert.equal(confirmationMode({category:'report',deadline:'2026-11-05T18:00:00+08:00'}),'task');
  assert.equal(confirmationMode({category:'important'}),'');
  assert.equal(confirmationMode({category:'report',suggested_mode:''}),'');
  assert.equal(confirmationMode({category:'course',operation:'cancel'}),'acknowledge');
  assert.equal(confirmationMode({category:'report',current_task:{id:1}}),'task');
});
