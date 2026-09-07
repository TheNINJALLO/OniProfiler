/* SPDX-License-Identifier: GPL-3.0-only */
"use strict";
const $ = id => document.getElementById(id);
const documents = [];
let current = null;
const fmt = (v, digits=1) => OniData.finite(v) ? v.toLocaleString(undefined, {maximumFractionDigits:digits}) : "Unavailable";
const date = v => OniData.finite(v) ? new Date(v).toLocaleString() : "Unavailable";
function element(tag, text, className) { const n=document.createElement(tag); if (text !== undefined) n.textContent=text; if (className) n.className=className; return n; }
function metric(parent, label, value, note) { const box=element("div",undefined,"metric"); box.append(element("div",label,"label"),element("div",value,"value"),element("div",note,"note")); parent.append(box); }
function detail(parent, label, value) { const n=element("div",undefined,"detail-row"); n.append(element("strong",label),element("span",value)); parent.append(n); }
function title(doc) { return (doc.demo?"DEMO · ":"") + (doc.recording?.title || doc.title || (doc.kind.charAt(0).toUpperCase()+doc.kind.slice(1))) + " · " + date(doc.generated_ms); }
function feedback(message) { $("feedback").textContent=message; }
async function importFiles(files) {
  let added=0; const errors=[];
  for (const file of Array.from(files).slice(0,20)) {
    try {
      if (documents.length>=20) throw new Error("Clear some reports before importing more than 20 files.");
      if (file.size>10*1024*1024) throw new Error("The file exceeds the 10 MiB import limit.");
      const report=OniData.validate(JSON.parse(await file.text()));
      documents.push(report); added++;
    } catch (error) { errors.push(file.name+": "+error.message); }
  }
  updateSelectors();
  if (added) selectReport(documents.length-1);
  feedback(added+" report(s) opened locally. "+errors.join(" "));
  $("files").value="";
}
$("files").addEventListener("change",event=>importFiles(event.target.files));
$("dropzone").addEventListener("dragover",event=>{ event.preventDefault(); $("dropzone").classList.add("dragging"); });
$("dropzone").addEventListener("dragleave",()=>$("dropzone").classList.remove("dragging"));
$("dropzone").addEventListener("drop",event=>{event.preventDefault();$("dropzone").classList.remove("dragging");importFiles(event.dataTransfer.files);});
$("clear").addEventListener("click",()=>{documents.length=0;current=null;for(const id of ["metrics","findings","recording-details","area-rows","native-reports","compare-results","compare-warnings","active-report","compare-a","compare-b","limitations","snapshot-age","chart-description","area-age","area-count","dimension"]){const n=$(id);if(n)n.replaceChildren();}$("area-search").value="";$("recording-title").textContent="Snapshot";const c=$("history-chart");c.getContext("2d")?.clearRect(0,0,c.width,c.height);$("workspace").hidden=true;feedback("Imported data cleared from this page.");});
function updateSelectors() {
  for (const id of ["active-report","compare-a","compare-b"]) { const select=$(id); const old=select.value; select.replaceChildren(); documents.forEach((doc,index)=>{const o=element("option",title(doc));o.value=String(index);select.append(o);}); if(old && Number(old)<documents.length)select.value=old; }
  if(documents.length>1)$("compare-b").value=String(documents.length-1);
}
$("active-report").addEventListener("change",event=>selectReport(Number(event.target.value)));
function selectReport(index) {
  current=documents[index];if(!current)return;
  $("active-report").value=String(index);$("workspace").hidden=false;$("demo-warning").hidden=!current.demo;
  const age=Math.round((Date.now()-current.generated_ms)/1000);
  $("snapshot-age").textContent="Snapshot generated "+date(current.generated_ms)+". "+(age<0?"Timestamp is ahead of this device's clock.":"Age: "+fmt(age,0)+" seconds.");
  const h=current.health,m=$("metrics");m.replaceChildren();
  metric(m,"TPS",fmt(h.tps,2),"Target: 20 · "+fmt(OniData.finite(h.tps_span_ms)?h.tps_span_ms/1000:null,1)+"s window");
  metric(m,"Mean tick",fmt(h.mspt_mean)+" ms","50 ms target budget · "+fmt(h.tick_samples,0)+" samples");
  metric(m,"95th-percentile tick",fmt(h.mspt_p95)+" ms","Longest observed: "+fmt(h.mspt_max)+" ms");
  metric(m,"Resident memory",OniData.finite(h.rss_bytes)?fmt(h.rss_bytes/1048576,0)+" MiB":"Unavailable","No container memory limit inferred");
  const findings=$("findings");findings.replaceChildren();
  for(const f of current.findings){const box=element("div",undefined,"finding "+f.level);box.append(element("span",f.evidence,"evidence"),element("h3",f.title),element("p",f.detail));findings.append(box);}
  if(!current.findings.length)findings.append(element("p","No explanatory findings were included.","muted"));
  const r=current.recording,d=$("recording-details");d.replaceChildren();$("recording-title").textContent=r?.title||"Snapshot details";
  detail(d,"Session at export",current.session.description||"Not included");
  detail(d,"Players / loaded entities / chunks",fmt(h.players,0)+" / "+fmt(h.entities,0)+" / "+fmt(h.chunks,0));
  detail(d,"Process CPU",fmt(h.cpu_percent)+"% of total host capacity");
  if(r){detail(d,"Native outcome",r.native_outcome||"Unknown");detail(d,"Sample coverage",fmt(r.samples,0)+" samples · "+fmt(r.dropped_samples,0)+" dropped");detail(d,"Sampling",r.mode+" · interval "+fmt(r.interval,0)+(r.mode==="allocation"?" bytes":" ms"));detail(d,"Started by",r.owner||"Unknown");detail(d,"Native result",r.native_result||"No native artifact recorded");}
  $("limitations").replaceChildren(...current.limitations.map(s=>element("p",s)));
  const dims=$("dimension");dims.replaceChildren(element("option","All dimensions"));dims.firstChild.value="";
  [...new Set(current.loaded_areas.areas.map(a=>a.dimension))].sort().forEach(s=>{const o=element("option",s);o.value=s;dims.append(o);});
  renderAreas();renderNative();renderCompare();drawHistory();
}
function renderAreas(){if(!current)return;const source=current.loaded_areas;$("area-age").textContent=source.snapshot_ms?"Area snapshot: "+date(source.snapshot_ms):"No loaded-area scan was included. Request one in-game when appropriate.";const dim=$("dimension").value,query=$("area-search").value.toLowerCase();const filtered=source.areas.filter(a=>(!dim||a.dimension===dim)&&(!query||(a.dimension+" "+a.chunk_x+" "+a.chunk_z+" "+a.types.map(t=>t.name).join(" ")).toLowerCase().includes(query))).sort((a,b)=>(b.entities??-1)-(a.entities??-1));const rows=$("area-rows");rows.replaceChildren();for(const a of filtered){const row=element("tr");const range=(v)=>OniData.finite(v)?fmt(v*16,0)+" to "+fmt(v*16+15,0):"Unavailable";[a.dimension,fmt(a.chunk_x,0)+" / "+fmt(a.chunk_z,0),range(a.chunk_x)+" / "+range(a.chunk_z),fmt(a.entities,0),a.types.sort((x,y)=>y.count-x.count).map(t=>t.name+": "+t.count).join(", ")].forEach(s=>row.append(element("td",s)));rows.append(row);}$("area-count").textContent=filtered.length+" area(s) shown out of "+source.areas.length+" retained in this snapshot.";}
$("dimension").addEventListener("change",renderAreas);$("area-search").addEventListener("input",renderAreas);
function renderNative(){const out=$("native-reports");out.replaceChildren();for(const r of [...current.native_reports].sort((a,b)=>(b.time_ms??0)-(a.time_ms??0))){const n=element("article",undefined,"native-entry");n.append(element("small",r.storage==="url"?"EXTERNAL REFERENCE":"LOCAL FILE REFERENCE"),element("h3",r.type+" · "+r.owner),element("p",date(r.time_ms),"muted"),element("code",r.result));out.append(n);}if(!current.native_reports.length)out.append(element("p","No native report history was included in this snapshot.","empty"));}
function renderCompare(){const out=$("compare-results"),warnings=$("compare-warnings");out.replaceChildren();warnings.replaceChildren();if(documents.length<2){warnings.append(element("p","Open two or more reports to compare their measurements.","empty"));return;}const a=documents[Number($("compare-a").value)],b=documents[Number($("compare-b").value)];if(!a||!b)return;for(const warning of OniData.compatibility(a,b))warnings.append(element("p",warning,"notice"));for(const [key,label,unit]of [["mspt_mean","Mean tick change"," ms"],["mspt_p95","95th-percentile change"," ms"],["tps","TPS change",""],["rss_bytes","Resident memory change"," MiB"]]){const divisor=key==="rss_bytes"?1048576:1;const delta=OniData.delta(a.health[key],b.health[key]);const value=delta?(delta.absolute>0?"+":"")+fmt(delta.absolute/divisor)+unit:"Unavailable";metric(out,label,value,delta&&delta.percent!==null?fmt(delta.percent)+"% relative to A. Not a causal conclusion.":"Percentage unavailable when the baseline is zero or missing.");}}
$("compare-a").addEventListener("change",renderCompare);$("compare-b").addEventListener("change",renderCompare);
function drawHistory(){if(!current)return;const canvas=$("history-chart"),ctx=canvas.getContext("2d");if(!ctx)return;const values=current.history.filter(h=>OniData.finite(h.timestamp_ms)&&OniData.finite(h.mspt_mean));const rect=canvas.getBoundingClientRect();if(rect.width<1)return;const ratio=Math.min(2,Math.max(1,window.devicePixelRatio||1));const w=Math.round(rect.width),h=Math.round(rect.height),pad=35;canvas.width=Math.round(w*ratio);canvas.height=Math.round(h*ratio);ctx.setTransform(ratio,0,0,ratio,0,0);ctx.clearRect(0,0,w,h);ctx.font="13px system-ui";ctx.fillStyle="#afc0d6";if(values.length<2){ctx.fillText("Not enough history points to draw a trend.",pad,60);$("chart-description").textContent="The report needs at least two valid mean-tick snapshots.";return;}values.sort((a,b)=>a.timestamp_ms-b.timestamp_ms);const max=Math.max(60,...values.map(v=>v.mspt_mean))*1.12,minTime=values[0].timestamp_ms,span=Math.max(1,values.at(-1).timestamp_ms-minTime);for(let i=0;i<=4;i++){const y=h-pad-(h-2*pad)*i/4;ctx.strokeStyle="#2d4059";ctx.beginPath();ctx.moveTo(pad,y);ctx.lineTo(w-pad,y);ctx.stroke();ctx.fillText(fmt(max*i/4,0),2,y+4);}const target=h-pad-50/max*(h-2*pad);ctx.setLineDash([5,5]);ctx.strokeStyle="#eac780";ctx.beginPath();ctx.moveTo(pad,target);ctx.lineTo(w-pad,target);ctx.stroke();ctx.setLineDash([]);ctx.strokeStyle="#81caff";ctx.lineWidth=2.5;ctx.beginPath();values.forEach((v,i)=>{const x=pad+(v.timestamp_ms-minTime)/span*(w-2*pad),y=h-pad-v.mspt_mean/max*(h-2*pad);i?ctx.lineTo(x,y):ctx.moveTo(x,y);});ctx.stroke();ctx.lineWidth=1;$("chart-description").textContent=values.length+" rolling mean snapshots from "+date(minTime)+" to "+date(values.at(-1).timestamp_ms)+". Dashed line: 50 ms target budget. Minimum / maximum plotted mean: "+fmt(Math.min(...values.map(v=>v.mspt_mean)))+" / "+fmt(Math.max(...values.map(v=>v.mspt_mean)))+" ms.";}
const tabs=Array.from(document.querySelectorAll("[role=tab]"));function activateTab(button){for(const b of tabs){const active=b===button;b.setAttribute("aria-selected",String(active));b.tabIndex=active?0:-1;$(b.dataset.tab).hidden=!active;}if(button.dataset.tab==="overview")drawHistory();}
for(const [index,b]of tabs.entries()){b.addEventListener("click",()=>activateTab(b));b.addEventListener("keydown",e=>{if(!["ArrowLeft","ArrowRight","Home","End"].includes(e.key))return;e.preventDefault();const next=e.key==="Home"?0:e.key==="End"?tabs.length-1:(index+(e.key==="ArrowRight"?1:-1)+tabs.length)%tabs.length;activateTab(tabs[next]);tabs[next].focus();});}
$("demo").addEventListener("click",()=>{if(documents.length>18){feedback("Clear imported files before loading the two demonstration reports.");return;}const now=Date.now();for(const [index,mean]of [67,33].entries()){const health={timestamp_ms:now-(1-index)*1000,history_ms:60000,tps_span_ms:10000,mspt_span_ms:10000,cpu_span_ms:10000,tick_samples:200,tps:index?20:14.9,mspt_mean:mean,mspt_p95:mean+22,mspt_max:mean+88,cpu_percent:19,rss_bytes:4294967296,players:12,entities:780,chunks:450};documents.push(OniData.validate({schema_version:1,product:"OniProfiler powered by spark",version:"demo",demo:true,kind:"health",generated_ms:now-(1-index)*1000,title:index?"Synthetic candidate B":"Synthetic baseline A",health,session:{description:"Demonstration only. No server is connected."},findings:[{level:index?"warning":"critical",evidence:"synthetic example",title:index?"Some example ticks exceed the budget":"Example simulation slowdown",detail:"This screen demonstrates the interface. It is not a diagnosis of your server."}],history:Array.from({length:18},(_,i)=>({...health,timestamp_ms:now-(17-i)*5000,mspt_mean:mean+Math.sin(i)*9})),loaded_areas:{snapshot_ms:now,areas:[{dimension:"Overworld (demo)",chunk_x:12,chunk_z:-4,entities:190,types:{"minecraft:villager":140,"minecraft:item":50}},{dimension:"Nether (demo)",chunk_x:-2,chunk_z:16,entities:85,types:{"minecraft:zombie_pigman":85}}]},native_reports:[],limitations:["All values in this demonstration are synthetic.","The production viewer reads user-selected JSON files without uploading them.","Entity concentrations do not establish per-chunk tick cost."]}));}updateSelectors();selectReport(documents.length-2);feedback("Loaded two clearly labeled demonstration reports. No server data was accessed.");});

window.addEventListener("resize",()=>window.requestAnimationFrame(drawHistory));
