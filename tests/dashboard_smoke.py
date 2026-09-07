#!/usr/bin/env python3
"""Actual dashboard DOM tests with explicitly synthetic API responses.
These are not end-to-end TLS/browser-network tests. API security uses TestClient tests separately.
"""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import shutil
from playwright.sync_api import sync_playwright

ROOT=Path(__file__).resolve().parents[1]
STATIC=ROOT/'controlplane/oniprofiler_control/static'
FIXTURE=r'''
window.__calls=[];window.__auth=false;window.__role='manager';window.__remote=true;window.__commands=[];
const stamp=Date.now();
const user={id:'11111111111111111111111111111111',username:'demo-owner',is_admin:true,csrf:'synthetic-csrf'};
const health={tps:19.83,tps_span_ms:10000,mspt_mean:28.5,mspt_p95:51.2,mspt_max:84.7,rss_bytes:3221225472,players:12,entities:864,chunks:176,tick_samples:200};
const areas=[{dimension:'overworld',chunk_x:-12,chunk_z:8,entities:164,types:{'minecraft:villager':64,'minecraft:cow':100}},{dimension:'nether',chunk_x:4,chunk_z:-7,entities:82,types:{'minecraft:piglin':82}}];
const base={schema_version:1,product:'OniProfiler powered by spark',version:'1.0.0-rc.1',kind:'health',instance_id:'bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb',generated_ms:stamp,health,
 session:{running:false,background:false,exporting:false,started_ms:0,owner:''},
 findings:[{level:'warning',evidence:'measured',title:'SYNTHETIC DEMO DATA',detail:'Interface-test values only. This is not connected to a Minecraft server.'}],
 loaded_areas:{snapshot_ms:stamp,areas}};
const reports=[{id:'cccccccccccccccccccccccccccccccc',kind:'health',created_ms:stamp,source_key:'report-1-health.json',notes:'Baseline synthetic investigation',tags:['baseline'],profile_hash:null,payload:base},
{id:'dddddddddddddddddddddddddddddddd',kind:'incident',created_ms:stamp-900000,source_key:'report-2-incident.json',notes:'Prior synthetic incident',tags:['incident'],profile_hash:null,payload:{...base,health:{...health,mspt_mean:36}}}];
const frame={symbol:'<img src=x onerror="window.injected=true">',self_weight:7,self_percent:70};
reports[0].payload={...base,native_analysis:{mode:'Execution',unit:'milliseconds',limitations:['Keyword categories are indicated, not proof of a cause.'],threads:[{name:'Server thread',categories:[{label:'Entities',weight:3,percent:30}],top_frames:[frame]}]}};
window.fetch=async function(path,options={}){
 const method=options.method||'GET',data=options.body?JSON.parse(options.body):null;window.__calls.push({path:String(path),method,data,headers:options.headers||{}});
 const reply=(data,status=200)=>Promise.resolve(new Response(JSON.stringify(data),{status,headers:{'Content-Type':'application/json'}}));
 if(path==='/api/me')return window.__auth?reply(user):reply({detail:'Sign in'},401);
 if(path==='/api/login'){window.__auth=true;return reply(user);}
 if(path==='/api/logout'){window.__auth=false;return reply({ok:true});}
 if(!window.__auth)return reply({detail:'Sign in'},401);
 if(path==='/api/servers'&&method==='GET')return reply([{id:'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa',name:'DEMO / Kingdom staging',role:window.__role,agent_online:true,snapshot_fresh:true,health},
 {id:'eeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee',name:'DEMO / Second server',role:window.__role,agent_online:false,snapshot_fresh:false,health:{tps:null}}]);
 if(path==='/api/users')return reply([{...user,active:true},{id:'22222222222222222222222222222222',username:'observer',active:true,is_admin:false}]);
 if(path.includes('/snapshot'))return reply({snapshot:{...base,capabilities:{remote_controls:window.__remote,remote_management:window.__remote},health:path.includes('eeeeeeee')?{...health,tps:null}:health}});
 if(path.includes('/history'))return reply(Array.from({length:20},(_,i)=>({received_ms:stamp-(19-i)*15000,health:{...health,mspt_mean:24+(i%6)*3}})));
 if(path.endsWith('/commands')){if(method==='POST'){const c={id:'ffffffffffffffffffffffffffffffff',action:data.action,preset:data.preset,actor:user.username,created_ms:stamp,status:'queued',result:null};window.__commands.unshift(c);return reply(c,202);}return reply(window.__commands);}
 if(path.endsWith('/reports'))return reply(reports);
 if(path.endsWith('/runtime'))return reply([{source:'DEMO-ShopPlugin',received_ms:stamp,stale:false,payload:{runtime:'python',window_ms:15000,coverage:'Explicitly instrumented callbacks only.',callbacks:[{name:'shop.interact',count:82,total_ms:144.3,max_ms:8.9,errors:0}]}}]);
 if(path.endsWith('/access'))return reply([{username:'observer',role:'viewer'}]);
 if(path.endsWith('/runtime-keys'))return reply([]);
 if(path.startsWith('/api/audit'))return reply([{time_ms:stamp,actor:'demo-owner',event:'record.requested',detail:'Synthetic test event'}]);
 if(path.startsWith('/api/compare'))return reply({warnings:['Synthetic comparison: player workload is not controlled.'],metrics:[{metric:'mspt_mean',before:36,after:28.5,delta:-7.5,percent_change:-20.8}]});
 if(path.endsWith('/share'))return reply({url:'https://profiler.example.invalid/shared/synthetic-example-only',expires_ms:stamp+86400000});
 if(path.startsWith('/api/reports/')){const item=reports.find(r=>path.includes(r.id));if(method==='PATCH'){item.notes=data.notes;item.tags=data.tags;return reply(item);}return reply(item);}
 return reply({detail:'Unhandled test fixture route '+path},404);
};
'''

def document() -> str:
    html=(STATIC/'index.html').read_text()
    html=html.replace('<link rel="stylesheet" href="/static/styles.css">','<style>'+(STATIC/'styles.css').read_text()+'</style>')
    html=html.replace('<script src="/static/app.js" defer></script>','')
    return html.replace('</body>','<script>'+FIXTURE+'</script><script>'+(STATIC/'app.js').read_text()+'</script></body>')

def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--screenshots',type=Path);args=parser.parse_args()
    checks=0
    with sync_playwright() as runtime:
        browser=runtime.chromium.launch(executable_path=shutil.which('chromium') or shutil.which('chromium-browser'),headless=True,args=['--no-sandbox'])
        for width,height in [(1440,1050),(390,844)]:
            page=browser.new_page(viewport={'width':width,'height':height});errors=[];network=[]
            page.on('pageerror',lambda error:errors.append(str(error)))
            page.on('request',lambda req:network.append(req.url) if req.url.startswith(('http:','https:')) else None)
            page.on('dialog',lambda dialog:dialog.accept())
            page.set_content(document(),wait_until='load')
            assert page.locator('#login-view').is_visible();checks+=1
            page.locator('input[name=username]').fill('demo-owner');page.locator('input[name=password]').fill('synthetic-not-a-real-password')
            page.locator('#login-form button').click();page.locator('#application').wait_for(state='visible')
            page.get_by_text('SYNTHETIC DEMO DATA',exact=True).wait_for();checks+=1
            assert page.locator('.metrics .metric').count()==4;checks+=1
            assert page.locator('#content svg').count()==1;checks+=1
            assert page.locator('input[name=password]').input_value()=='';checks+=1
            assert page.evaluate('document.documentElement.scrollWidth<=innerWidth+1');checks+=1
            if args.screenshots:
                args.screenshots.mkdir(parents=True,exist_ok=True)
                page.screenshot(path=str(args.screenshots/f'dashboard-demo-{width}.png'),full_page=True)
            page.locator('[data-view=investigate]').click()
            assert page.get_by_role('button',name='Stop and save locally',exact=True).is_disabled();checks+=1
            page.get_by_role('button',name='Start recording',exact=True).first.click()
            page.get_by_text('queued',exact=True).wait_for();checks+=1
            assert 'not confirmed' in page.locator('#toast').inner_text();checks+=1
            command=page.evaluate('window.__calls.find(r=>r.method==="POST"&&r.path.endsWith("/commands"))')
            assert command['data']['preset']=='quick' and command['headers']['X-Oni-CSRF']=='synthetic-csrf';checks+=1
            page.locator('[data-view=areas]').click()
            assert page.locator('#content tbody tr').count()==2;checks+=1
            page.get_by_placeholder('Filter entity types or coordinates').fill('villager')
            assert page.locator('#content tbody tr').count()==1;checks+=1
            page.get_by_placeholder('Filter entity types or coordinates').fill('')
            page.get_by_label('Dimension',exact=True).select_option('nether')
            assert page.locator('#content tbody tr').count()==1 and 'piglin' in page.locator('#content').inner_text();checks+=1
            page.locator('[data-view=reports]').click()
            page.get_by_placeholder('Search type, filename, notes or tags').fill('baseline')
            assert page.get_by_role('button',name='Open report',exact=True).count()==1;checks+=1
            page.get_by_role('button',name='Open report',exact=True).click();page.locator('#detail-dialog').wait_for(state='visible')
            assert '<img' in page.locator('#dialog-body').inner_text() and page.locator('#dialog-body img').count()==0;checks+=1
            assert not page.evaluate('Boolean(window.injected)');checks+=1
            page.get_by_label('Notes',exact=True).fill('Recheck with the same player workload.')
            page.get_by_role('button',name='Save notes',exact=True).click()
            page.wait_for_function('window.__calls.some(r=>r.method==="PATCH")');checks+=1
            page.get_by_role('button',name='Create expiring share',exact=True).click()
            assert not page.get_by_label('Include loaded-area coordinates',exact=True).is_checked();checks+=1
            page.get_by_role('button',name='Create share link',exact=True).click()
            page.get_by_text('Read-only share created',exact=True).wait_for();checks+=1
            page.keyboard.press('Escape');page.wait_for_function('document.getElementById("dialog-body").textContent===""');checks+=1
            page.get_by_role('button',name='Compare reports',exact=True).click()
            page.get_by_text('Synthetic comparison: player workload is not controlled.',exact=True).wait_for();checks+=1
            page.locator('#dialog-close').click()
            page.locator('[data-view=runtime]').click()
            assert 'shop.interact' in page.locator('#content').inner_text() and 'not CPU percentages' in page.locator('#content').inner_text();checks+=1
            page.locator('[data-view=manage]').click();page.get_by_text('Audit trail',exact=True).wait_for();checks+=1
            assert page.get_by_role('button',name='Background on',exact=True).is_enabled();checks+=1
            page.evaluate('window.__role="viewer";window.__remote=false')
            page.locator('#refresh').click();page.wait_for_function('window.__calls.filter(r=>r.path==="/api/servers").length>=3')
            page.locator('[data-view=investigate]').click()
            assert all(page.get_by_role('button',name='Start recording',exact=True).nth(i).is_disabled() for i in range(4));checks+=1
            page.locator('#server-select').select_option('eeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee')
            page.locator('[data-view=overview]').click()
            page.get_by_text('Agent offline',exact=True).first.wait_for()
            assert 'Unavailable' in page.locator('.metrics').inner_text();checks+=1
            page.locator('#logout').click();page.locator('#login-view').wait_for(state='visible')
            assert page.locator('#content').inner_text()=='' and page.locator('#server-select option').count()==0;checks+=1
            assert not errors,errors;checks+=1
            assert not network,network;checks+=1
            page.close()
        browser.close()
    print(f'Passed {checks} live-dashboard DOM checks at desktop and mobile sizes with synthetic mocked API responses; no network requests. Real API behavior is tested separately.')
if __name__=='__main__':main()
