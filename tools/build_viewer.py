#!/usr/bin/env python3
"""Build a single-file offline viewer, using exact CSP hashes rather than unsafe-inline."""
from __future__ import annotations
import argparse
import base64
import hashlib
from pathlib import Path
import re

ROOT=Path(__file__).resolve().parents[1]

def csp_hash(text: str) -> str:
    return "'sha256-"+base64.b64encode(hashlib.sha256(text.encode('utf-8')).digest()).decode('ascii')+"'"

def bundle(root: Path = ROOT) -> str:
    web=root/'web'
    html=(web/'index.html').read_text(encoding='utf-8')
    style=(web/'styles.css').read_text(encoding='utf-8')
    scripts=[(web/name).read_text(encoding='utf-8') for name in ['data.js','app.js']]
    if '</style' in style.lower() or any('</script' in script.lower() for script in scripts):
        raise ValueError('An asset contains an unsafe inline closing tag.')
    for name in ['data.js','app.js']:
        source='<script src="'+name+'" defer></script>'
        if html.count(source)!=1:raise ValueError('Expected exactly one script reference: '+name)
        html=html.replace(source,'')
    link='<link rel="stylesheet" href="styles.css">'
    if html.count(link)!=1:raise ValueError('Expected one stylesheet reference.')
    html=html.replace(link,'<style>'+style+'</style>')
    csp="default-src 'none'; script-src "+' '.join(csp_hash(script) for script in scripts)+"; style-src "+csp_hash(style)+"; img-src data:; connect-src 'none'; base-uri 'none'; form-action 'none'"
    html,count=re.subn(r'<meta http-equiv="Content-Security-Policy" content="[^"]*">',lambda _: '<meta http-equiv="Content-Security-Policy" content="'+csp+'">',html)
    if count!=1:raise ValueError('Expected one content security policy.')
    html=html.replace('</body>','\n'.join('<script>'+script+'</script>' for script in scripts)+'\n</body>')
    return html

def main() -> None:
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,default=ROOT/'dist'/'OniProfiler-Report-Viewer.html')
    args=parser.parse_args();args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(bundle(),encoding='utf-8')
    print(args.output)

if __name__=='__main__':main()
