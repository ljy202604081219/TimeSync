import test from 'node:test';
import assert from 'node:assert/strict';
import {addDays,calendarBusy,calendarStart,layoutEvents,weekStart} from '../src/calendarData.ts';
const oldWindow='2026-11-02T08:00:00+08:00';
test('calendar opens the imported week independently of the planning window',()=>{
 const imports=[{id:1,week_start:'2026-12-07',course_count:12}];
 assert.equal(calendarStart(oldWindow,imports),'2026-12-07');
 assert.equal(calendarStart(oldWindow,[]),'2026-11-02');
});
test('December concrete and weekly classes render outside November solver window',()=>{
 const rows=[{title:'导入课',start:'2026-12-07T08:00:00+08:00',end:'2026-12-07T08:45:00+08:00',weekday:null,kind:'course'}, {title:'每周课',start:'2026-11-03T10:00:00+08:00',end:'2026-11-03T12:00:00+08:00',weekday:1,kind:'course'}];
 const december=calendarBusy(rows,'2026-12-07');
 assert.equal(december.length,2);
 assert.equal(december[1].start,'2026-12-08T10:00:00+08:00');
 assert.equal(calendarBusy(rows,'2026-11-02').length,1);
});
test('date navigation stays correct across month/year boundaries',()=>{
 assert.equal(addDays('2026-12-28',7),'2027-01-04');
 assert.equal(addDays('2026-12-07',-7),'2026-11-30');
});
test('overlapping imported and existing courses remain side by side',()=>{
 const rows=layoutEvents([{start:'2026-12-07T08:00:00+08:00',end:'2026-12-07T10:00:00+08:00'}, {start:'2026-12-07T08:00:00+08:00',end:'2026-12-07T08:45:00+08:00'}, {start:'2026-12-07T10:00:00+08:00',end:'2026-12-07T11:00:00+08:00'}]);
 assert.equal(rows[0].lanes,2);assert.notEqual(rows[0].lane,rows[1].lane);assert.equal(rows[2].lanes,1);
});

test("assistant event focus picks its own week across imported weeks and year boundary",()=>{
 assert.equal(weekStart("2026-11-04T09:00:00+08:00"),"2026-11-02");
 assert.equal(weekStart("2027-01-01T14:00:00+08:00"),"2026-12-28");
});
