#!/usr/bin/env python3
"""Optional Chromium UI smoke test. Requires Playwright and a local Chromium binary.
Screenshots contain explicitly labeled synthetic data, never a connected server.
"""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import shutil
import sys
from playwright.sync_api import sync_playwright

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"tools"))
from build_viewer import bundle

def main() -> None:
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--screenshots',type=Path)
    args=parser.parse_args()
    checks=0
    # Render the actual distributable single-file HTML directly. This does
    # not require navigation or network permissions and preserves its CSP hashes.
    html=bundle(ROOT)
    with sync_playwright() as runtime:
        browser=runtime.chromium.launch(executable_path=shutil.which('chromium') or shutil.which('chromium-browser'),headless=True,args=['--no-sandbox'])
        for viewport in [{'width':1440,'height':1080},{'width':390,'height':844}]:
            page=browser.new_page(viewport=viewport,device_scale_factor=1)
            errors=[];network=[]
            page.on('pageerror',lambda error:errors.append(str(error)))
            page.on('request',lambda request:network.append(request.url) if request.url.startswith(('http:','https:')) else None)
            page.set_content(html,wait_until='load')
            assert not page.locator('#workspace').is_visible();checks+=1
            page.locator('#demo').click()
            assert page.locator('#workspace').is_visible();checks+=1
            assert page.locator('#demo-warning').is_visible();checks+=1
            assert page.locator('#metrics .metric').count()>=4;checks+=1
            assert 'DEMO' in page.locator('#active-report option').first.text_content();checks+=1
            if args.screenshots:
                args.screenshots.mkdir(parents=True,exist_ok=True)
                page.screenshot(path=str(args.screenshots/('viewer-demo-'+str(viewport['width'])+'.png')),full_page=True)
            page.locator('#tab-areas').click()
            assert page.locator('#area-rows tr').count()==2;checks+=1
            page.locator('#area-search').fill('villager')
            assert page.locator('#area-rows tr').count()==1;checks+=1
            page.locator('#tab-compare').click()
            assert 'demonstration' in page.locator('#compare-warnings').inner_text();checks+=1
            assert page.locator('#compare-results .metric').count()==4;checks+=1
            page.locator('#tab-compare').focus();page.keyboard.press('Home')
            assert page.locator('#tab-overview').get_attribute('aria-selected')=='true';checks+=1
            # Long paths must scroll inside their table rather than widen the page.
            assert page.evaluate('document.documentElement.scrollWidth <= innerWidth + 1');checks+=1
            page.locator('#clear').click()
            assert not page.locator('#workspace').is_visible();checks+=1
            assert page.locator('#active-report option').count()==0;checks+=1
            malicious={'schema_version':1,'product':'OniProfiler powered by spark','kind':'health','generated_ms':1000,
                'health':{'tps':None,'players':0},'findings':[{'level':'critical','title':'<img src=x onerror="window.injected=true">','detail':'Text only'}]}
            page.locator('#files').set_input_files({'name':'test.json','mimeType':'application/json','buffer':json.dumps(malicious).encode()})
            page.wait_for_function('document.querySelector("#findings").textContent.includes("<img")')
            assert page.locator('#findings img').count()==0 and not page.evaluate('Boolean(window.injected)');checks+=1
            assert 'Unavailable' in page.locator('#metrics').inner_text();checks+=1
            assert not errors,errors;checks+=1
            assert not network,network;checks+=1
            page.close()
        browser.close()
    print(f'Passed {checks} browser smoke checks across desktop and mobile viewports. No external requests observed.')

if __name__=='__main__':main()
