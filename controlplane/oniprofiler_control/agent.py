"""Outbound-only bridge between a local OniProfiler plugin and its private dashboard."""
from __future__ import annotations
from dataclasses import dataclass
import argparse
import hashlib
import json
import logging
import os
from pathlib import Path
import random
import re
import signal
import sqlite3
import ssl
import threading
import time
import tomllib
from typing import Any
from urllib.parse import urlsplit
import httpx
from .protocol import encode_command, validate_snapshot, bounded_json
from .security import now_ms, REPORT_KEY, valid_id, valid_name
from .profile import profile_filename, analyze_file

LOG=logging.getLogger("oniprofiler.agent")
PROFILE=re.compile(r"^profile-[0-9]+(?:-[0-9]+)?\.sparkprofile$")

def validate_origin(value: str, allow_http: bool=False) -> str:
    u=urlsplit(value)
    if not u.hostname or u.username or u.password or u.query or u.fragment or u.path not in ("", "/"):
        raise ValueError("Dashboard URL must be an origin without credentials, a path, query, or fragment")
    if u.scheme!="https" and not (allow_http and u.scheme=="http" and u.hostname in {"127.0.0.1","localhost","::1"}):
        raise ValueError("HTTPS with certificate verification is required; HTTP is permitted only for explicit loopback development")
    return value.rstrip("/")

@dataclass(frozen=True)
class AgentSettings:
    dashboard_url: str
    plugin_dir: Path
    state_dir: Path
    token_env: str="ONI_AGENT_TOKEN"
    token_file: Path | None=None
    poll_seconds: int=5
    sync_reports: bool=True
    sync_native_profiles: bool=False
    analyze_native_profiles: bool=True
    allow_http_loopback: bool=False
    ca_bundle: str=""
    cgroup_path: str=""
    panel_url: str=""
    panel_server: str=""
    panel_token_env: str="ONI_PANEL_TOKEN"

    def __post_init__(self):
        validate_origin(self.dashboard_url,self.allow_http_loopback)
        if not 5<=self.poll_seconds<=60:
            raise ValueError("poll_seconds must be between 5 and 60")
        if self.panel_url:
            validate_origin(self.panel_url)
            if not re.fullmatch(r"[A-Za-z0-9-]{8,64}",self.panel_server):
                raise ValueError("Invalid Pterodactyl server identifier")

    @classmethod
    def load(cls,path: Path) -> "AgentSettings":
        raw=tomllib.loads(path.read_text(encoding="utf-8"))
        allowed=set(cls.__dataclass_fields__)
        unknown=set(raw)-allowed
        if unknown:
            raise ValueError("Unknown agent settings: "+", ".join(sorted(unknown)))
        for name in ("plugin_dir","state_dir","token_file"):
            if raw.get(name):
                p=Path(raw[name]).expanduser()
                raw[name]=(path.parent/p).resolve() if not p.is_absolute() else p
        for name in ("sync_reports","sync_native_profiles","analyze_native_profiles","allow_http_loopback"):
            if name in raw and type(raw[name]) is not bool:
                raise ValueError(name+" must be a boolean")
        return cls(**raw)

    def secret(self) -> str:
        if self.token_file:
            if self.token_file.is_symlink():
                raise ValueError("Token file must not be a symlink")
            if os.name!="nt" and self.token_file.stat().st_mode & 0o077:
                raise ValueError("Token file must have owner-only permissions (chmod 600)")
            value=self.token_file.read_text().strip()
        else:
            value=os.getenv(self.token_env,"").strip()
        if not re.fullmatch(r"[A-Za-z0-9_-]{20,128}",value):
            raise ValueError("A valid agent token is required through the configured environment variable or owner-only file")
        return value

def read_json(path: Path, limit: int=2*1024*1024) -> dict[str,Any]:
    if path.is_symlink() or not path.is_file():
        raise ValueError("Input is missing or is a symlink")
    with path.open("rb") as stream:
        raw=stream.read(limit+1)
    if len(raw)>limit:
        raise ValueError("Input file exceeds its size limit")
    value=json.loads(raw)
    bounded_json(value,limit)
    if not isinstance(value,dict):
        raise ValueError("Expected a JSON object")
    return value

def atomic_private(path: Path, data: bytes) -> None:
    for parent in (path.parent,path.parent.parent):
        if parent.is_symlink():
            raise ValueError("Mailbox directory must not be a symlink")
    path.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
    temporary=path.with_name(path.name+".agent-tmp")
    if path.is_symlink() or temporary.is_symlink():
        raise ValueError("Mailbox file must not be a symlink")
    descriptor=os.open(temporary,os.O_WRONLY|os.O_CREAT|os.O_TRUNC,0o600)
    with os.fdopen(descriptor,"wb") as out:
        out.write(data);out.flush();os.fsync(out.fileno())
    os.replace(temporary,path)

class Agent:
    def __init__(self,settings: AgentSettings,client: Any=None):
        self.settings=settings
        settings.state_dir.mkdir(parents=True,exist_ok=True,mode=0o700)
        if settings.state_dir.is_symlink():
            raise ValueError("Agent state directory must not be a symlink")
        self.state=sqlite3.connect(settings.state_dir/"agent.sqlite3")
        self.state.executescript("""
          CREATE TABLE IF NOT EXISTS sent_reports(key TEXT PRIMARY KEY,report_id TEXT NOT NULL,profile_sent INTEGER NOT NULL DEFAULT 0);
          CREATE TABLE IF NOT EXISTS sent_acks(id TEXT PRIMARY KEY,time_ms INTEGER NOT NULL);
          CREATE TABLE IF NOT EXISTS runtime_sent(source TEXT PRIMARY KEY,hash TEXT NOT NULL);
        """)
        if "next_profile_ms" not in {row[1] for row in self.state.execute("PRAGMA table_info(sent_reports)")}:
            self.state.execute("ALTER TABLE sent_reports ADD COLUMN next_profile_ms INTEGER NOT NULL DEFAULT 0")
            self.state.commit()
        self.client=client or httpx.Client(base_url=validate_origin(settings.dashboard_url,settings.allow_http_loopback),
            headers={"Authorization":"Bearer "+settings.secret()},
            verify=ssl.create_default_context(cafile=settings.ca_bundle or None),timeout=15,
            follow_redirects=False,trust_env=False)
        self.owns_client=client is None
        self.panel_cache: dict[str,Any]={}
        self.next_panel=0.0

    def close(self):
        self.state.close()
        if self.owns_client:
            self.client.close()

    def post(self,path: str,**kwargs):
        response=self.client.post(path,**kwargs)
        if response.status_code not in (200,201,202):
            # Deliberately do not log body, request headers or credential-bearing URLs.
            raise RuntimeError(f"Dashboard rejected {path}: HTTP {response.status_code}")
        return response.json()

    def deliver(self,command: dict[str,Any]) -> None:
        payload=encode_command(command)
        identity=command["id"]
        root=self.settings.plugin_dir/"bridge"
        if command["expires_ms"]<=now_ms():
            self.post("/api/agent/ack",json={"id":identity,"status":"expired","message":"Agent received an expired request; it was not delivered"});return
        if (root/"claimed"/(identity+".cmd")).exists() or (root/"outbox"/(identity+".json")).exists():
            return
        destination=root/"inbox"/(identity+".cmd")
        if not destination.exists():
            atomic_private(destination,payload)

    def acknowledge(self) -> None:
        root=self.settings.plugin_dir/"bridge"/"outbox"
        if not root.is_dir() or root.is_symlink():
            return
        count=0
        for path in sorted(root.glob("*.json")):
            try:
                valid_id(path.stem)
            except ValueError:
                continue
            if self.state.execute("SELECT 1 FROM sent_acks WHERE id=?",(path.stem,)).fetchone():
                continue
            receipt=read_json(path,16384)
            if receipt.get("id")!=path.stem:
                raise ValueError("Receipt identity does not match its filename")
            response=self.client.post("/api/agent/ack",json=receipt)
            # A report already retired by the service is not an endless retry target.
            if response.status_code not in (200,404):
                raise RuntimeError(f"Acknowledgement failed: HTTP {response.status_code}")
            with self.state:
                self.state.execute("INSERT OR IGNORE INTO sent_acks VALUES(?,?)",(path.stem,now_ms()))
            count+=1
            if count>=16:
                break
        with self.state:
            self.state.execute("DELETE FROM sent_acks WHERE time_ms<?",(now_ms()-7*86400000,))

    def sync_reports(self) -> None:
        if not self.settings.sync_reports:
            return
        root=self.settings.plugin_dir/"reports"
        if not root.is_dir() or root.is_symlink():
            return
        sent=0
        for path in sorted(root.glob("report-*.json"),reverse=True):
            if not REPORT_KEY.fullmatch(path.name) or path.is_symlink():
                continue
            record=self.state.execute("SELECT report_id,profile_sent,next_profile_ms FROM sent_reports WHERE key=?",(path.name,)).fetchone()
            if record and (record[1] or not self.settings.sync_native_profiles or record[2]>now_ms()):
                continue
            report=validate_snapshot(read_json(path))
            recording=report.get("recording") or {}
            native_name=profile_filename(str(recording.get("native_result","")))
            if not record and self.settings.analyze_native_profiles and native_name and recording.get("native_outcome")=="saved":
                try:
                    report["native_analysis"]=analyze_file(self.settings.plugin_dir/"profiles"/native_name)
                except (OSError,ValueError) as error:
                    report["native_analysis"]={"available":False,"error":str(error)[:300]}
            # Native analysis uses only local immutable files, not game-server API calls.
            if not record:
                result=self.post("/api/agent/report",json={"source_key":path.name,"report":report})
                identity=result["id"]
                with self.state:
                    self.state.execute("INSERT OR IGNORE INTO sent_reports(key,report_id) VALUES(?,?)",(path.name,identity))
            else:
                identity=record[0]
            uploaded=False
            if self.settings.sync_native_profiles:
                recording=report.get("recording") or {}
                value=native_name or ""
                if recording.get("native_outcome")=="saved" and PROFILE.fullmatch(value):
                    profile=self.settings.plugin_dir/"profiles"/value
                    if profile.is_file() and not profile.is_symlink() and not profile.parent.is_symlink() and profile.stat().st_size<=64*1024*1024:
                        with profile.open("rb") as stream:
                            self.post("/api/agent/profile",params={"report_id":identity},content=stream,headers={"Content-Type":"application/octet-stream"})
                        uploaded=True
                else:
                    uploaded=True  # This report has no native payload to synchronize.
            if uploaded:
                with self.state:
                    self.state.execute("UPDATE sent_reports SET profile_sent=1 WHERE key=?",(path.name,))
            elif self.settings.sync_native_profiles:
                with self.state:
                    self.state.execute("UPDATE sent_reports SET next_profile_ms=? WHERE key=?",(now_ms()+300000,path.name))
            sent+=1
            if sent>=4:
                break
        # Forget keys only after their local files are gone; bounded by plugin retention plus a small slack.
        present={p.name for p in root.glob("report-*.json") if not p.is_symlink()}
        with self.state:
            for row in self.state.execute("SELECT key FROM sent_reports").fetchall():
                if row[0] not in present:
                    self.state.execute("DELETE FROM sent_reports WHERE key=?",row)

    def runtime(self) -> None:
        root=self.settings.plugin_dir/"runtime"
        if not root.is_dir() or root.is_symlink():
            return
        for path in sorted(root.glob("*.json"))[:100]:
            if path.is_symlink():
                continue
            try:
                valid_name(path.stem)
            except ValueError:
                continue
            data=read_json(path,128*1024)
            fingerprint=hashlib.sha256(bounded_json(data).encode()).hexdigest()
            previous=self.state.execute("SELECT hash FROM runtime_sent WHERE source=?",(path.stem,)).fetchone()
            if previous and previous[0]==fingerprint:
                continue
            self.post("/api/agent/runtime",json={"source":path.stem,"report":data})
            with self.state:
                self.state.execute("INSERT INTO runtime_sent VALUES(?,?) ON CONFLICT(source) DO UPDATE SET hash=excluded.hash",(path.stem,fingerprint))

    def host(self) -> dict[str,Any]:
        result: dict[str,Any]={}
        if self.settings.cgroup_path:
            base=Path(self.settings.cgroup_path)
            result["cgroup"]={"source":"explicitly configured cgroup v2 path","collected_ms":now_ms(),"memory_bytes":None,"memory_limit_bytes":None,"cpu_quota_cores":None}
            item=result["cgroup"]
            for file,key in (("memory.current","memory_bytes"),("memory.max","memory_limit_bytes")):
                try:
                    value=(base/file).read_text().strip()
                    item[key]=None if value=="max" else max(0,int(value))
                except (OSError,ValueError):
                    pass
            try:
                quota,period=(base/"cpu.max").read_text().split()
                if quota!="max" and int(period)>0:
                    item["cpu_quota_cores"]=int(quota)/int(period)
            except (OSError,ValueError):
                pass
        if self.settings.panel_url and time.monotonic()>=self.next_panel:
            self.next_panel=time.monotonic()+60
            key=os.getenv(self.settings.panel_token_env,"")
            if key:
                try:
                    with httpx.Client(timeout=8,follow_redirects=False,trust_env=False,headers={"Authorization":"Bearer "+key,"Accept":"application/json"}) as client:
                        response=client.get(self.settings.panel_url.rstrip("/")+"/api/client/servers/"+self.settings.panel_server+"/resources")
                        response.raise_for_status()
                        data=response.json()["attributes"]
                        self.panel_cache={"collected_ms":now_ms(),"source":"Pterodactyl Client API","current_state":data.get("current_state"),"resources":data.get("resources",{})}
                except (httpx.HTTPError,KeyError,ValueError):
                    LOG.warning("Pterodactyl resource refresh failed; previous reading remains timestamped")
        if self.panel_cache:
            result["pterodactyl"]=self.panel_cache
        return result

    def cycle(self) -> None:
        self.acknowledge()
        snapshot=validate_snapshot(read_json(self.settings.plugin_dir/"reports"/"dashboard.json"))
        host=self.host()
        if host:
            snapshot["host"]=host
        response=self.post("/api/agent/heartbeat",json={"snapshot":snapshot})
        for command in response.get("commands",[]):
            self.deliver(command)
        self.sync_reports()
        self.runtime()

class ProcessLock:
    def __init__(self,path: Path):
        path.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
        if path.is_symlink():
            raise ValueError("Agent lock must not be a symlink")
        self.file=path.open("a+b")
        self.file.seek(0);self.file.write(b"0");self.file.flush();self.file.seek(0)
        try:
            if os.name=="nt":
                import msvcrt
                msvcrt.locking(self.file.fileno(),msvcrt.LK_NBLCK,1)
            else:
                import fcntl
                fcntl.flock(self.file.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
        except OSError as error:
            self.file.close()
            raise RuntimeError("Another agent is using this state directory") from error
    def close(self):
        self.file.close()

def main() -> None:
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config",type=Path,required=True)
    parser.add_argument("--once",action="store_true")
    args=parser.parse_args()
    logging.basicConfig(level=logging.INFO,format="%(asctime)s %(levelname)s %(message)s")
    settings=AgentSettings.load(args.config.resolve())
    lock=ProcessLock(settings.state_dir/"agent.lock")
    agent=Agent(settings);stop=threading.Event()
    signals=(signal.SIGINT,signal.SIGTERM)+((signal.SIGBREAK,) if hasattr(signal,"SIGBREAK") else ())
    for sig in signals:
        signal.signal(sig,lambda *_:stop.set())
    failures=0
    try:
        while not stop.is_set():
            try:
                agent.cycle();failures=0
            except (OSError,ValueError,RuntimeError,httpx.HTTPError) as error:
                failures+=1
                LOG.warning("Agent cycle failed (%s). No command success is assumed.",type(error).__name__)
                if args.once:
                    raise
            if args.once:
                break
            delay=min(60,settings.poll_seconds*2**min(failures,4))
            stop.wait(delay+random.uniform(0,1))
    finally:
        agent.close();lock.close()

if __name__=="__main__":
    main()
