#!/usr/bin/env python3
"""Real loopback HTTP service/agent smoke. Uses synthetic files, not a Bedrock server."""
from __future__ import annotations
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time
import httpx
from oniprofiler_control.config import Settings
from oniprofiler_control.store import Store
from oniprofiler_control.agent import Agent,AgentSettings
from oniprofiler_control.security import now_ms


def main():
    checks=0
    with tempfile.TemporaryDirectory(prefix='oni-http-') as folder:
        root=Path(folder)
        with socket.socket() as sock:
            sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
        origin=f'http://127.0.0.1:{port}'
        store=Store(Settings(root/'data',origin,True));store.create_user('SmokeOwner','synthetic-password-for-smoke',True)
        server=store.create_server('Synthetic HTTP test','local-smoke')
        plugin=root/'plugin';(plugin/'reports').mkdir(parents=True)
        payload={'schema_version':1,'product':'OniProfiler powered by spark','version':'1.0.0','kind':'health','instance_id':'b'*32,'generated_ms':now_ms(),
            'health':{'tps':19.5,'mspt_mean':25,'tick_samples':200,'players':2},'capabilities':{'remote_controls':True,'remote_management':False},
            'session':{'running':False,'background':False,'started_ms':0,'owner':''},'findings':[{'level':'ok','evidence':'measured','title':'Synthetic HTTP fixture','detail':'Not a live server'}]}
        (plugin/'reports/dashboard.json').write_text(json.dumps(payload))
        (plugin/'reports/report-1000-health.json').write_text(json.dumps(payload))
        tokenfile=root/'agent.token';tokenfile.write_text(server['agent_token']);tokenfile.chmod(0o600)
        settings=AgentSettings(origin,plugin,root/'agent-state',token_file=tokenfile,allow_http_loopback=True)
        env={**os.environ,'ONI_DATA_DIR':str(root/'data'),'ONI_PUBLIC_ORIGIN':origin,'ONI_ALLOW_HTTP_LOOPBACK':'1'}
        with (root/'server.log').open('w') as log:
            process=subprocess.Popen([sys.executable,'-m','oniprofiler_control.server','--host','127.0.0.1','--port',str(port),'--allow-http-loopback'],env=env,stdout=log,stderr=log)
            try:
                with httpx.Client(base_url=origin,timeout=5,trust_env=False) as client:
                    for _ in range(80):
                        if process.poll() is not None:raise RuntimeError((root/'server.log').read_text())
                        try:
                            response=client.get('/healthz')
                            if response.status_code==200:break
                        except httpx.ConnectError:pass
                        time.sleep(.1)
                    else:raise RuntimeError('HTTP service did not become ready')
                    assert response.json()['version']=='1.0.0';checks+=1
                    assert client.get('/api/me').status_code==401;checks+=1
                    page=client.get('/');assert 'OniProfiler' in page.text and "script-src 'self'" in page.headers['content-security-policy'];checks+=1
                    assert client.get('/static/app.js').status_code==200;checks+=1
                    login=client.post('/api/login',json={'username':'SmokeOwner','password':'synthetic-password-for-smoke'},headers={'Origin':origin})
                    assert login.status_code==200 and 'HttpOnly' in login.headers['set-cookie'];checks+=1
                    headers={'Origin':origin,'X-Oni-CSRF':login.json()['csrf']}
                    agent=Agent(settings)
                    try:
                        agent.cycle();checks+=1
                        listing=client.get('/api/servers').json();assert listing[0]['snapshot_fresh'];checks+=1
                        command=client.post(f'/api/servers/{server["id"]}/commands',json={'action':'health'},headers=headers)
                        assert command.status_code==202;identity=command.json()['id'];checks+=1
                        agent.cycle();wire=plugin/'bridge/inbox'/(identity+'.cmd');assert wire.is_file() and 'action=health' in wire.read_text();checks+=1
                        # A synthetic plugin receipt tests the transport only; no native action is claimed.
                        out=plugin/'bridge/outbox';out.mkdir(parents=True,exist_ok=True)
                        (out/(identity+'.json')).write_text(json.dumps({'id':identity,'status':'applied','message':'Synthetic transport acknowledgement only','session':0,'time_ms':now_ms()}))
                        agent.cycle()
                        receipts=client.get(f'/api/servers/{server["id"]}/commands').json();assert receipts[0]['status']=='applied';checks+=1
                        reports=client.get(f'/api/servers/{server["id"]}/reports').json();assert len(reports)==1;checks+=1
                        share=client.post('/api/reports/'+reports[0]['id']+'/share',json={'hours':1,'include_locations':False},headers=headers)
                        assert share.status_code==200;checks+=1
                        path=share.json()['url'].removeprefix(origin)
                        assert client.get(path).status_code==200;checks+=1
                        assert client.post('/api/logout',json={},headers=headers).status_code==200;checks+=1
                        assert client.get('/api/me').status_code==401;checks+=1
                    finally:agent.close()
            finally:
                process.terminate()
                try:process.wait(timeout=10)
                except subprocess.TimeoutExpired:process.kill();process.wait()
    print(f'Passed {checks} real loopback HTTP checks using the service, outbound agent and synthetic plugin files. No BDS process was used.')
if __name__=='__main__':main()
