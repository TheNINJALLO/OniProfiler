// SPDX-License-Identifier: GPL-3.0-only
import test from 'node:test';
import assert from 'node:assert/strict';
import {mkdtemp,readFile,rm} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {createProfiler} from '../integrations/runtime-sdk.mjs';
import {exportSnapshot} from '../integrations/node-exporter.mjs';
test('wrap preserves this, arguments, return and elapsed time',()=>{let time=0;const p=createProfiler({source:'Test',clock:()=>time});const o={value:7,fn:p.wrap('sum',function(n){time+=2;return this.value+n;})};assert.equal(o.fn(3),10);const s=p.snapshot();assert.equal(s.callbacks[0].total_ms,2);assert.equal(s.callbacks[0].count,1);assert.match(s.coverage,/Not total CPU/);});
test('exceptions are counted and rethrown',()=>{const p=createProfiler({source:'Test'});assert.throws(p.wrap('bad',()=>{throw Error('preserved');}),/preserved/);assert.equal(p.snapshot().callbacks[0].errors,1);});
test('async callback keeps return and rejection behavior',async()=>{let time=0;const p=createProfiler({source:'Async',clock:()=>time});assert.equal(await p.wrapAsync('work',async()=>{time+=4;return 9;})(),9);await assert.rejects(p.wrapAsync('reject',async()=>{throw Error('reject');})());const rows=p.snapshot().callbacks;assert.equal(rows.find(r=>r.name==='work').total_ms,4);assert.equal(rows.find(r=>r.name==='reject').errors,1);});
test('snapshot copies data and resets only when requested',()=>{const p=createProfiler({source:'Test'});p.wrap('work',()=>{})();const a=p.snapshot(false);a.callbacks[0].count=100;assert.equal(p.snapshot().callbacks[0].count,1);assert.equal(p.snapshot().callbacks.length,0);});
test('callback cardinality is bounded',()=>{const p=createProfiler({source:'Test'});for(let i=0;i<300;i++)p.wrap(String(i),()=>{})();assert.ok(p.snapshot().callbacks.length<=200);});
test('invalid identity and callback labels rejected',()=>{assert.throws(()=>createProfiler({source:'../bad'}));const p=createProfiler({source:'Good'});assert.throws(()=>p.wrap('',()=>{}));assert.throws(()=>p.wrap('x'.repeat(201),()=>{}));});
test('clock regression does not create negative time',()=>{let time=10;const p=createProfiler({source:'Test',clock:()=>time});p.wrap('work',()=>{time=1;})();assert.equal(p.snapshot().callbacks[0].total_ms,0);});
test('Node exporter writes an actual bounded snapshot',async()=>{const folder=await mkdtemp(join(tmpdir(),'oni-sdk-'));try{const p=createProfiler({source:'Fixture'});p.wrap('run',()=>{})();await exportSnapshot(p,folder);const doc=JSON.parse(await readFile(join(folder,'Fixture.json'),'utf8'));assert.equal(doc.source,'Fixture');assert.equal(doc.callbacks[0].count,1);}finally{await rm(folder,{recursive:true,force:true});}});
