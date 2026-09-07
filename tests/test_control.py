# SPDX-License-Identifier: GPL-3.0-only
"""Real SQLite and ASGI tests; external agents/panels are isolated test transports."""
import copy
import gzip
import json
import os
from pathlib import Path
import struct
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'controlplane'))
from fastapi.testclient import TestClient
from oniprofiler_control.config import Settings
from oniprofiler_control.security import now_ms,password_hash,password_matches,valid_id,valid_name
from oniprofiler_control.protocol import bounded_json,encode_command,validate_snapshot,compare_reports,redact_for_share
from oniprofiler_control.server import create_app
from oniprofiler_control.store import Store
from oniprofiler_control.agent import Agent,AgentSettings,atomic_private,read_json,validate_origin,ProcessLock
from oniprofiler_control.sdk import Instrumentor
from oniprofiler_control.profile import analyze_bytes,profile_filename,varint

PASSWORD='a-long-test-password-not-for-production'
ORIGIN='http://127.0.0.1:8080'

def snapshot(**overrides):
    result={'schema_version':1,'product':'OniProfiler powered by spark','version':'1.0.0','kind':'health',
        'instance_id':'b'*32,'generated_ms':now_ms(),'health':{'tps':19.8,'mspt_mean':24.1,'mspt_p95':48.2,'mspt_max':67,'rss_bytes':2048,'players':4,'entities':20,'chunks':4,'tick_samples':200},
        'capabilities':{'remote_controls':True,'remote_management':True},'session':{'running':False,'background':False,'started_ms':0,'owner':''},
        'loaded_areas':{'snapshot_ms':now_ms(),'areas':[{'dimension':'overworld','chunk_x':-4,'chunk_z':2,'entities':20,'types':{'minecraft:cow':20}}]},
        'findings':[{'level':'ok','evidence':'measured','title':'Synthetic test finding','detail':'Not a real server reading'}],
        'native_reports':[{'result':'/secret/local/path'}],'recording':None}
    result.update(overrides);return result

def command(**overrides):
    result={'id':'a'*32,'instance':'b'*32,'action':'record','preset':'lag','actor':'Owner','role':'operator','issued_ms':now_ms(),'expires_ms':now_ms()+120000,'expected_session':0}
    result.update(overrides);return result

def vint(v):
    b=bytearray()
    while v>127:b.append((v&127)|128);v>>=7
    b.append(v);return bytes(b)
def field(n,data):return vint(n*8+2)+vint(len(data))+data
def integer(n,v):return vint(n*8)+vint(v)
def native_fixture(mode=0):
    # Postorder: child (self 3), parent (inclusive 10, self 7).
    child=field(3,b'Mob')+field(4,b'tick')+field(8,struct.pack('<d',3.0))
    parent=field(3,b'Server')+field(4,b'run')+field(8,struct.pack('<d',10.0))+field(9,vint(0))
    thread=field(1,b'Server thread')+field(3,child)+field(3,parent)+field(4,struct.pack('<d',10.0))+field(5,vint(1))
    meta=integer(2,1000)+integer(3,4000)+integer(11,2000)+integer(15,mode)
    return field(1,meta)+field(2,thread)

class ProtocolTests(unittest.TestCase):
    def test_wire_is_fixed_ascii(self):
        result=encode_command(command());self.assertEqual(len(result.decode().strip().splitlines()),10);self.assertNotIn(b'console=',result)
    def test_command_allowlist(self):
        for changes in [{'action':'kill'},{'actor':'x\nrole=manager'},{'expires_ms':-1},{'role':'admin'},{'expected_session':True},{'preset':'../../secret'}]:
            with self.subTest(changes=changes),self.assertRaises(ValueError):encode_command(command(**changes))
    def test_bad_identifiers(self):
        for bad in (None,[],42,'../a','A'*32):
            with self.subTest(bad=bad),self.assertRaises(ValueError):valid_id(bad)
        with self.assertRaises(ValueError):valid_name(None)
    def test_native_wire_contract(self):
        exe=os.getenv('ONI_BRIDGE_TEST_EXE')
        if not exe:self.skipTest('Set ONI_BRIDGE_TEST_EXE to run compiled C++ contract check')
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'command.cmd';p.write_bytes(encode_command(command()))
            result=subprocess.run([exe,str(p)],capture_output=True,text=True,check=True)
            self.assertEqual(result.stdout,'record:Owner')
    def test_json_limits(self):
        for bad in ({'x':float('nan')},{'x':float('inf')},{'x':2**64},{'x':'x'*16385},{'x':[0]*4097}):
            with self.subTest(bad_type=type(bad)),self.assertRaises(ValueError):bounded_json(bad)
        with self.assertRaises(ValueError):bounded_json({'x':'abc'},max_bytes=5)
    def test_valid_missing_measurements(self):
        s=snapshot();s['health']['tps']=None;self.assertIsNone(validate_snapshot(s)['health']['tps'])
    def test_invalid_snapshot(self):
        for s in [snapshot(schema_version=True),snapshot(generated_ms=0),snapshot(health={'tps':True}),snapshot(instance_id=42),snapshot(loaded_areas={'areas':[{'dimension':'end','chunk_x':0,'chunk_z':0,'entities':-1}]}),[]]:
            with self.subTest(snapshot=s),self.assertRaises(ValueError):validate_snapshot(s)
    def test_comparison_zero_and_workload(self):
        a=snapshot();b=copy.deepcopy(a);a['health']['mspt_mean']=0;b['health']['players']=5
        result=compare_reports(a,b);metric=next(m for m in result['metrics'] if m['metric']=='mspt_mean')
        self.assertIsNone(metric['percent_change']);self.assertTrue(any('Player' in w for w in result['warnings']))
    def test_share_allowlist(self):
        s=snapshot();s['unknown_future_secret']='secret';s['notes']='private notes'
        result=redact_for_share(s);self.assertNotIn('native_reports',result);self.assertNotIn('instance_id',result);self.assertNotIn('unknown_future_secret',result);self.assertNotIn('notes',result);self.assertNotIn('loaded_areas',result)
        self.assertIn('loaded_areas',redact_for_share(s,True))
    def test_password_and_invalid_length(self):
        salt,h=password_hash('invalid-password-length');self.assertTrue(password_matches('invalid-password-length',salt,h));self.assertFalse(password_matches('',salt,h));self.assertFalse(password_matches('wrong-but-long-enough',salt,h))
    def test_https_and_origin_validation(self):
        for value in ('http://public.example','https://user:pass@example.com','https://example.com/path','https://example.com?q=1','ftp://localhost'):
            with self.subTest(value=value),self.assertRaises(ValueError):validate_origin(value,True)
        self.assertEqual(validate_origin(ORIGIN,True),ORIGIN)
        with tempfile.TemporaryDirectory() as d,self.assertRaises(ValueError):Settings(Path(d),ORIGIN)

class NativeAnalysisTests(unittest.TestCase):
    def test_self_weights_not_double_counted(self):
        result=analyze_bytes(native_fixture());thread=result['threads'][0]
        self.assertEqual(thread['total_weight'],10);self.assertEqual(sum(r['self_weight'] for r in thread['top_frames']),10)
        self.assertEqual(sum(r['percent'] for r in thread['categories']),100)
        self.assertEqual(thread['top_frames'][0]['self_weight'],7)
    def test_gzip_and_allocation_units(self):
        a=analyze_bytes(gzip.compress(native_fixture(1)));self.assertEqual(a['mode'],'allocation');self.assertIn('byte',a['unit'])
    def test_invalid_profiles(self):
        for raw in (b'',b'not protobuf',b'\x00',b'\x0a\xff\xff\xff\xff\xff\xff\xff\xff\xff\x02',gzip.compress(native_fixture())[:-4]):
            with self.subTest(raw=raw[:12]),self.assertRaises(ValueError):analyze_bytes(raw)
    def test_bounded_decompression(self):
        with patch('oniprofiler_control.profile.MAX_BYTES',1000),self.assertRaises(ValueError):analyze_bytes(gzip.compress(b'a'*1001))
    def test_cycle_rejected(self):
        raw=native_fixture().replace(field(9,vint(0)),field(9,vint(1)))
        with self.assertRaises(ValueError):analyze_bytes(raw)
    def test_bad_weights_rejected(self):
        raw=native_fixture().replace(struct.pack('<d',3.0),struct.pack('<d',float('nan')))
        with self.assertRaises(ValueError):analyze_bytes(raw)
    def test_human_receipt_basename(self):
        self.assertEqual(profile_filename('Saved to C:\\server\\plugins\\oniprofiler\\profiles\\profile-123-1.sparkprofile - open it at https://spark.lucko.me/'),'profile-123-1.sparkprofile')
        self.assertIsNone(profile_filename('../../secret.json'));self.assertIsNone(profile_filename('profile-1.sparkprofile profile-2.sparkprofile'))

class ApiTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        self.settings=Settings(self.root/'data',ORIGIN,True);self.app=create_app(self.settings);self.store=self.app.state.store
        self.owner=self.store.create_user('Owner',PASSWORD,True);self.viewer=self.store.create_user('Viewer',PASSWORD,False)
        self.server=self.store.create_server('Synthetic fixture server','Owner');self.sid=self.server['id']
        self.other=self.store.create_server('Other private server','Owner');self.store.grant(self.viewer['id'],self.sid,'viewer','Owner')
        self.client=TestClient(self.app,base_url=ORIGIN);self.client.__enter__()
        login=self.client.post('/api/login',json={'username':'Owner','password':PASSWORD},headers={'Origin':ORIGIN});self.assertEqual(login.status_code,200)
        self.headers={'Origin':ORIGIN,'X-Oni-CSRF':login.json()['csrf']}
        self.agent_headers={'Authorization':'Bearer '+self.server['agent_token']};self.store.heartbeat(self.sid,snapshot())
    def tearDown(self):
        self.client.__exit__(None,None,None);self.temp.cleanup()
    def write(self,path,body):return self.client.post(path,json=body,headers=self.headers)
    def viewer_client(self):
        c=TestClient(self.app,base_url=ORIGIN);login=c.post('/api/login',json={'username':'Viewer','password':PASSWORD},headers={'Origin':ORIGIN});return c,{'Origin':ORIGIN,'X-Oni-CSRF':login.json()['csrf']}
    def test_cookie_csp_and_static_assets(self):
        response=self.client.get('/');self.assertEqual(response.status_code,200);self.assertIn('frame-ancestors',response.headers['content-security-policy']);self.assertNotIn('unsafe-inline',response.headers['content-security-policy'])
        for path in ('app.js','styles.css','share.js'):self.assertEqual(self.client.get('/static/'+path).status_code,200)
        self.assertEqual(self.client.get('/api/me').json()['username'],'Owner')
    def test_secure_cookie_for_https(self):
        app=create_app(Settings(self.root/'secure','https://profiler.example'))
        app.state.store.create_user('Admin',PASSWORD,True)
        with TestClient(app,base_url='https://profiler.example') as client:
            r=client.post('/api/login',json={'username':'Admin','password':PASSWORD},headers={'Origin':'https://profiler.example'})
            self.assertIn('Secure',r.headers['set-cookie']);self.assertIn('HttpOnly',r.headers['set-cookie']);self.assertIn('samesite=strict',r.headers['set-cookie'].lower())
    def test_csrf_and_cross_origin(self):
        path=f'/api/servers/{self.sid}/commands';body={'action':'health'}
        self.assertEqual(self.client.post(path,json=body).status_code,403)
        self.assertEqual(self.client.post(path,json=body,headers={**self.headers,'Origin':'https://evil.example'}).status_code,403)
        self.assertEqual(self.client.get('/api/me',headers={'Host':'evil.example'}).status_code,400)
    def test_server_scoping(self):
        with self.viewer_client()[0] as c:
            listed=c.get('/api/servers').json();self.assertEqual([r['id'] for r in listed],[self.sid])
            self.assertEqual(c.get(f'/api/servers/{self.other["id"]}/snapshot').status_code,403)
            self.assertEqual(c.get('/api/users').status_code,403)
    def test_viewer_cannot_control(self):
        c,h=self.viewer_client()
        with c:self.assertEqual(c.post(f'/api/servers/{self.sid}/commands',json={'action':'record','preset':'lag'},headers=h).status_code,403)
    def test_operator_and_local_management_gate(self):
        self.store.grant(self.viewer['id'],self.sid,'operator','Owner');c,h=self.viewer_client()
        with c:
            self.assertEqual(c.post(f'/api/servers/{self.sid}/commands',json={'action':'record','preset':'lag'},headers=h).status_code,202)
            self.assertEqual(c.post(f'/api/servers/{self.sid}/commands',json={'action':'automatic-on'},headers=h).status_code,403)
        s=snapshot(capabilities={'remote_controls':True,'remote_management':False});self.store.heartbeat(self.sid,s)
        self.assertEqual(self.write(f'/api/servers/{self.sid}/commands',{'action':'automatic-on'}).status_code,403)
    def test_stale_telemetry_disables_actions(self):
        with self.store.db() as db:db.execute('UPDATE telemetry SET generated_ms=?,payload=? WHERE server_id=?',(now_ms()-60000,json.dumps(snapshot(generated_ms=now_ms()-60000)),self.sid))
        self.assertEqual(self.write(f'/api/servers/{self.sid}/commands',{'action':'health'}).status_code,422)
        fleet=self.client.get('/api/servers').json();item=next(s for s in fleet if s['id']==self.sid);self.assertTrue(item['agent_online']);self.assertFalse(item['snapshot_fresh'])
    def test_command_receipt_lifecycle(self):
        queued=self.write(f'/api/servers/{self.sid}/commands',{'action':'record','preset':'quick'});self.assertEqual(queued.status_code,202);qid=queued.json()['id']
        heartbeat=self.client.post('/api/agent/heartbeat',json={'snapshot':snapshot()},headers=self.agent_headers);self.assertEqual(heartbeat.status_code,200);self.assertEqual(heartbeat.json()['commands'][0]['id'],qid)
        self.assertEqual(self.store.commands(self.sid)[0]['status'],'dispatched')
        receipt={'id':qid,'status':'applied','message':'Started','session':123}
        self.assertEqual(self.client.post('/api/agent/ack',json=receipt,headers=self.agent_headers).status_code,200)
        receipt['status']='error';self.client.post('/api/agent/ack',json=receipt,headers=self.agent_headers)
        self.assertEqual(self.store.commands(self.sid)[0]['status'],'applied')
    def test_pending_limit(self):
        for _ in range(8):self.assertEqual(self.write(f'/api/servers/{self.sid}/commands',{'action':'health'}).status_code,202)
        self.assertEqual(self.write(f'/api/servers/{self.sid}/commands',{'action':'health'}).status_code,422)
    def test_stop_requires_exact_owned_session(self):
        self.store.grant(self.viewer['id'],self.sid,'operator','Owner');self.store.heartbeat(self.sid,snapshot(session={'running':True,'started_ms':123,'owner':'SomeoneElse'}))
        c,h=self.viewer_client()
        with c:
            self.assertEqual(c.post(f'/api/servers/{self.sid}/commands',json={'action':'stop','expected_session':122},headers=h).status_code,422)
            self.assertEqual(c.post(f'/api/servers/{self.sid}/commands',json={'action':'stop','expected_session':123},headers=h).status_code,403)
    def test_token_rotation_revokes_old_agent(self):
        r=self.write(f'/api/servers/{self.sid}/rotate-token',{});self.assertEqual(r.status_code,200);self.assertNotEqual(r.json()['agent_token'],self.server['agent_token'])
        self.assertEqual(self.client.post('/api/agent/heartbeat',json={'snapshot':snapshot()},headers=self.agent_headers).status_code,401)
    def test_reports_idempotence_notes_compare(self):
        body={'source_key':'report-100-1.json','report':snapshot()}
        a=self.client.post('/api/agent/report',json=body,headers=self.agent_headers);b=self.client.post('/api/agent/report',json=body,headers=self.agent_headers);self.assertEqual(a.json()['id'],b.json()['id']);self.assertFalse(b.json()['created'])
        rid=a.json()['id'];self.assertEqual(self.client.patch(f'/api/reports/{rid}',json={'notes':'Controlled change','tags':['baseline']},headers=self.headers).status_code,200)
        self.assertEqual(self.client.get(f'/api/reports/{rid}').json()['notes'],'Controlled change')
        self.assertEqual(self.client.get(f'/api/compare?before={rid}&after={rid}').status_code,200)
    def test_report_path_injection_and_other_agent(self):
        self.assertEqual(self.client.post('/api/agent/report',json={'source_key':'../../private.json','report':snapshot()},headers=self.agent_headers).status_code,422)
        rid,_=self.store.ingest_report(self.other['id'],'report-1.json',snapshot())
        self.assertEqual(self.client.post(f'/api/agent/profile?report_id={rid}',content=b'abc',headers=self.agent_headers).status_code,404)
    def test_redacted_share_expiry_and_revoke(self):
        rid,_=self.store.ingest_report(self.sid,'report-1.json',snapshot())
        shared=self.write(f'/api/reports/{rid}/share',{'hours':1}).json();secret=shared['url'].rsplit('/',1)[1]
        data=self.client.get('/api/shared/'+secret).json()['snapshot'];self.assertNotIn('native_reports',data);self.assertNotIn('loaded_areas',data)
        self.assertEqual(self.write(f'/api/reports/{rid}/revoke-shares',{}).status_code,200)
        self.assertEqual(self.client.get('/api/shared/'+secret).status_code,404)
    def test_profile_upload_and_download(self):
        rid,_=self.store.ingest_report(self.sid,'report-2.json',snapshot());raw=native_fixture()
        response=self.client.post('/api/agent/profile?report_id='+rid,content=raw,headers=self.agent_headers);self.assertEqual(response.status_code,200);self.assertEqual(response.json()['bytes'],len(raw))
        self.assertEqual(self.client.get(f'/api/reports/{rid}/profile').content,raw)
    def test_runtime_key_is_scoped_write_only(self):
        key=self.write(f'/api/servers/{self.sid}/runtime-keys',{'source':'MyAddon'}).json();h={'Authorization':'Bearer '+key['runtime_token']}
        with TestClient(self.app,base_url=ORIGIN) as fresh:
            payload={'runtime':'bedrock-script','window_ms':1000,'callbacks':[{'name':'tick','count':1,'total_ms':2,'max_ms':2,'errors':0}]}
            self.assertEqual(fresh.post('/api/runtime/report',json=payload,headers=h).status_code,200)
            self.assertEqual(fresh.post('/api/agent/heartbeat',json={'snapshot':snapshot()},headers=h).status_code,401)
            self.assertEqual(fresh.get('/api/servers',headers=h).status_code,401)
            self.assertEqual(self.store.runtime(self.sid)[0]['source'],'MyAddon')
            self.write(f'/api/servers/{self.sid}/runtime-keys/{key["id"]}/revoke',{})
            self.assertEqual(fresh.post('/api/runtime/report',json=payload,headers=h).status_code,401)
    def test_bad_runtime_statistics(self):
        with self.assertRaises(ValueError):self.store.put_runtime(self.sid,'Source',{'runtime':'python','window_ms':1000,'callbacks':[{'name':'tick','count':1,'errors':2,'max_ms':2,'total_ms':1}]})
    def test_disable_revokes_sessions_and_pending(self):
        self.store.grant(self.viewer['id'],self.sid,'operator','Owner');c,h=self.viewer_client()
        with c:
            q=c.post(f'/api/servers/{self.sid}/commands',json={'action':'health'},headers=h).json()
            self.write(f'/api/users/{self.viewer["id"]}/disable',{})
            self.assertEqual(c.get('/api/me').status_code,401)
            self.assertEqual(next(r['status'] for r in self.store.commands(self.sid) if r['id']==q['id']),'expired')
    def test_login_rate_limit(self):
        with TestClient(self.app,base_url=ORIGIN) as c:
            for _ in range(8):self.assertEqual(c.post('/api/login',json={'username':'Missing','password':PASSWORD},headers={'Origin':ORIGIN}).status_code,401)
            self.assertEqual(c.post('/api/login',json={'username':'Missing','password':PASSWORD},headers={'Origin':ORIGIN}).status_code,429)
    def test_api_body_size_limit(self):
        r=self.client.post('/api/login',content=b'x'*(2*1024*1024+1),headers={'Origin':ORIGIN,'Content-Type':'application/json'});self.assertEqual(r.status_code,413)
    def test_backup_and_retention(self):
        self.store.backup(self.root/'backup.sqlite3');self.assertTrue((self.root/'backup.sqlite3').is_file())
        with self.assertRaises(ValueError):self.store.backup(self.store.path)
    def test_agent_to_api_integration(self):
        plugin=self.root/'plugin';atomic_private(plugin/'reports'/'dashboard.json',json.dumps(snapshot()).encode());atomic_private(plugin/'reports'/'report-9.json',json.dumps(snapshot()).encode())
        queued=self.write(f'/api/servers/{self.sid}/commands',{'action':'record','preset':'lag'}).json()
        with TestClient(self.app,base_url=ORIGIN,headers=self.agent_headers) as connection:
            agent=Agent(AgentSettings(ORIGIN,plugin,self.root/'agent',allow_http_loopback=True),connection)
            try:
                agent.cycle();self.assertTrue((plugin/'bridge'/'inbox'/(queued['id']+'.cmd')).exists());self.assertEqual(len(self.store.reports(self.sid)),1)
                atomic_private(plugin/'bridge'/'outbox'/(queued['id']+'.json'),json.dumps({'id':queued['id'],'status':'applied','message':'Synthetic native receipt'}).encode())
                agent.cycle();self.assertEqual(self.store.commands(self.sid)[0]['status'],'applied');self.assertEqual(len(self.store.reports(self.sid)),1)
            finally:agent.close()

class SdkTests(unittest.TestCase):
    def test_python_return_exception_and_elapsed(self):
        probe=Instrumentor('Example')
        @probe.callback('work')
        def work(x):return x+1
        self.assertEqual(work(2),3)
        with self.assertRaises(RuntimeError):
            with probe.measure('bad'):raise RuntimeError('expected')
        rows={r['name']:r for r in probe.snapshot()['callbacks']};self.assertEqual(rows['work']['count'],1);self.assertEqual(rows['bad']['errors'],1);self.assertGreaterEqual(rows['work']['total_ms'],0)
        self.assertEqual(probe.snapshot()['callbacks'],[])
    def test_async_preserves_return_and_errors(self):
        import asyncio
        p=Instrumentor('Async')
        @p.callback()
        async def operation():await asyncio.sleep(0);return 7
        self.assertEqual(asyncio.run(operation()),7);self.assertEqual(p.snapshot()['callbacks'][0]['count'],1)
    def test_callback_cardinality_bounded(self):
        p=Instrumentor('Bounded')
        for i in range(250):
            with p.measure(str(i)):pass
        self.assertLessEqual(len(p.snapshot()['callbacks']),200)
    def test_atomic_file_and_lock(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);p=Instrumentor('Export',root)
            with p.measure('tick'):pass
            p.flush();self.assertEqual(read_json(root/'Export.json')['source'],'Export')
            lock=ProcessLock(root/'agent.lock')
            try:
                with self.assertRaises(RuntimeError):ProcessLock(root/'agent.lock')
            finally:lock.close()
    def test_symlink_file_refused(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);target=root/'private';target.write_text('secret')
            try:(root/'alias.json').symlink_to(target)
            except OSError:self.skipTest('Symlinks require privileges on this platform')
            with self.assertRaises(ValueError):atomic_private(root/'alias.json',b'{}')
            self.assertEqual(target.read_text(),'secret')

if __name__=='__main__':unittest.main()
