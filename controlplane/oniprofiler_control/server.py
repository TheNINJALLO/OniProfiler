"""Authenticated private dashboard API. Run behind HTTPS with a trusted proxy."""
from __future__ import annotations
from contextlib import asynccontextmanager
import argparse
import hashlib
import hmac
import json
import logging
from pathlib import Path
import queue
import secrets
import threading
from typing import Any
from urllib.parse import urlsplit

import httpx
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field
from starlette.middleware.trustedhost import TrustedHostMiddleware

from . import __version__
from .config import Settings,canonical_origin
from .protocol import compare_reports,encode_command
from .security import now_ms, valid_id
from .store import Store

LOG = logging.getLogger("oniprofiler")
STATIC = Path(__file__).parent / "static"

class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")

class Login(Strict):
    username: str = Field(min_length=1,max_length=80)
    password: str = Field(min_length=1,max_length=256)

class NewUser(Login):
    is_admin: bool = False

class NewServer(Strict):
    name: str = Field(min_length=1,max_length=100)

class Access(Strict):
    user_id: str
    role: str

class Command(Strict):
    action: str
    preset: str = "-"
    expected_session: int = Field(default=0,ge=0)

class Heartbeat(Strict):
    snapshot: dict[str, Any]

class IncomingReport(Strict):
    source_key: str = Field(max_length=120)
    report: dict[str, Any]

class Annotation(Strict):
    notes: str = Field(max_length=10000)
    tags: list[str] = Field(default_factory=list,max_length=16)

class Share(Strict):
    hours: int = Field(default=24,ge=1,le=168)
    include_locations: bool = False

class RuntimeKey(Strict):
    source: str = Field(min_length=1,max_length=80)

class RuntimeReport(Strict):
    source: str = Field(min_length=1,max_length=80)
    report: dict[str,Any]

class NoticeWorker:
    """Optional, bounded webhook worker. Profiling never waits for Discord."""
    def __init__(self, webhook: str):
        self.webhook=webhook
        self.queue: queue.Queue[dict[str,Any] | None]=queue.Queue(maxsize=32)
        self.thread: threading.Thread | None=None

    def start(self) -> None:
        if self.webhook:
            self.thread=threading.Thread(target=self.run,name="oni-notices",daemon=True)
            self.thread.start()

    def incident(self, server: str, report: dict[str,Any]) -> None:
        if not self.webhook:
            return
        h=report.get("health",{})
        # No coordinates, players' names, local paths, tokens, raw profiles or @mentions.
        content=(f"OniProfiler incident on {server[:100]}\n"
                 f"TPS: {h.get('tps', 'unavailable')} | mean tick: {h.get('mspt_mean', 'unavailable')} ms\n"
                 "This is a slow-tick observation, not a confirmed cause. Open your private dashboard.")
        try:
            self.queue.put_nowait({"content":content,"allowed_mentions":{"parse":[]}})
        except queue.Full:
            LOG.warning("Discord notice dropped: outbound queue is full")

    def run(self) -> None:
        with httpx.Client(timeout=5,follow_redirects=False,trust_env=False) as client:
            while True:
                payload=self.queue.get()
                if payload is None:
                    return
                try:
                    response=client.post(self.webhook,json=payload)
                    if response.status_code>=300:
                        LOG.warning("Discord notification returned status %s",response.status_code)
                except httpx.HTTPError:
                    LOG.warning("Discord notification failed; endpoint and credentials are not logged")

    def stop(self) -> None:
        if self.thread:
            try:
                self.queue.put_nowait(None)
            except queue.Full:
                self.queue.get_nowait();self.queue.put_nowait(None)
            self.thread.join(timeout=6)

class BodyLimit:
    """Buffer only small JSON bodies; binary uploads enforce a separate streaming cap."""
    def __init__(self, app, limit: int):
        self.app,self.limit=app,limit

    async def __call__(self, scope, receive, send):
        if scope["type"]!="http" or scope["method"] not in {"POST","PUT","PATCH"} or scope["path"]=="/api/agent/profile":
            return await self.app(scope,receive,send)
        body=bytearray()
        while True:
            message=await receive()
            if message["type"]=="http.disconnect":
                return
            body.extend(message.get("body",b""))
            if len(body)>self.limit:
                return await JSONResponse({"detail":"Request body exceeds the size limit"},413)(scope,receive,send)
            if not message.get("more_body",False):
                break
        sent=False
        async def replay():
            nonlocal sent
            if not sent:
                sent=True;return {"type":"http.request","body":bytes(body),"more_body":False}
            return await receive()
        await self.app(scope,replay,send)

def create_app(settings: Settings | None = None) -> FastAPI:
    settings=settings or Settings.environment()
    store=Store(settings)
    notices=NoticeWorker(settings.discord_webhook)
    @asynccontextmanager
    async def lifespan(app):
        notices.start()
        yield
        notices.stop()
    app=FastAPI(title="OniProfiler powered by spark",version=__version__,docs_url=None,redoc_url=None,openapi_url=None,lifespan=lifespan)
    app.state.store=store
    app.state.settings=settings
    app.add_middleware(TrustedHostMiddleware,allowed_hosts=[urlsplit(settings.origin).hostname])
    app.add_middleware(BodyLimit,limit=settings.max_json_bytes)

    @app.exception_handler(ValueError)
    async def invalid(request, exc):
        return JSONResponse({"detail":str(exc)},422)

    @app.exception_handler(PermissionError)
    async def forbidden(request, exc):
        return JSONResponse({"detail":str(exc)},403)

    @app.exception_handler(LookupError)
    async def missing(request, exc):
        return JSONResponse({"detail":str(exc)},404)

    @app.middleware("http")
    async def headers(request: Request, call_next):
        response=await call_next(request)
        response.headers["Cache-Control"]="no-store"
        response.headers["X-Content-Type-Options"]="nosniff"
        response.headers["Referrer-Policy"]="no-referrer"
        response.headers["Permissions-Policy"]="camera=(), microphone=(), geolocation=()"
        response.headers["Content-Security-Policy"]="default-src 'none'; script-src 'self'; style-src 'self'; connect-src 'self'; img-src 'self' data:; base-uri 'none'; frame-ancestors 'none'; form-action 'self'"
        if settings.secure_cookie:
            response.headers["Strict-Transport-Security"]="max-age=31536000"
        return response

    def check_origin(request: Request) -> None:
        try:
            incoming=canonical_origin(request.headers.get("origin", ""))
        except ValueError:
            incoming=""
        if not hmac.compare_digest(incoming,settings.origin):
            raise HTTPException(403,"Request origin does not match this dashboard")

    def current_user(request: Request) -> dict[str,Any]:
        user=store.session(request.cookies.get("oni_session",""))
        if not user:
            raise HTTPException(401,"Sign in to continue")
        if request.method not in {"GET","HEAD","OPTIONS"}:
            check_origin(request)
            if not hmac.compare_digest(request.headers.get("x-oni-csrf",""),user["csrf"]):
                raise HTTPException(403,"CSRF token is missing or invalid")
        return user

    def admin(user: dict = Depends(current_user)) -> dict:
        if not user["is_admin"]:
            raise HTTPException(403,"Administrator access is required")
        return user

    def bearer(request: Request) -> str:
        header=request.headers.get("authorization","")
        if not header.startswith("Bearer ") or len(header)>160:
            raise HTTPException(401,"A valid bearer token is required")
        return header[7:]

    def current_agent(request: Request) -> dict:
        agent=store.agent(bearer(request))
        if not agent:
            raise HTTPException(401,"Agent token is invalid or revoked")
        return agent

    @app.get("/healthz")
    def healthz():
        return {"status":"ok","version":__version__}

    @app.get("/")
    def index():
        return FileResponse(STATIC/"index.html")

    @app.get("/share/{secret}")
    def shared_page(secret: str):
        if not 20<=len(secret)<=128:
            raise HTTPException(404,"Shared report not found")
        store.shared(secret)
        return FileResponse(STATIC/"share.html")

    @app.post("/api/login")
    def login(data: Login, request: Request, response: Response):
        check_origin(request)
        try:
            user=store.login(data.username,data.password,request.client.host if request.client else "unknown")
        except PermissionError as error:
            raise HTTPException(429,str(error)) from error
        if not user:
            raise HTTPException(401,"Username or password is incorrect")
        response.set_cookie("oni_session",user.pop("token"),httponly=True,secure=settings.secure_cookie,samesite="strict",max_age=settings.session_hours*3600,path="/")
        return user

    @app.get("/api/me")
    def me(user: dict = Depends(current_user)):
        return user

    @app.post("/api/logout")
    def logout(request: Request,response: Response,user: dict=Depends(current_user)):
        store.logout(request.cookies.get("oni_session",""));response.delete_cookie("oni_session",path="/")
        return {"ok":True}

    @app.get("/api/servers")
    def servers(user: dict=Depends(current_user)):
        return store.servers(user)

    @app.post("/api/servers",status_code=201)
    def new_server(data: NewServer,user: dict=Depends(admin)):
        return store.create_server(data.name,user["username"])

    @app.post("/api/servers/{identity}/rotate-token")
    def rotate(identity: str,user: dict=Depends(admin)):
        store.require(user,identity,"manager")
        return store.rotate_server(identity,user["username"])

    @app.get("/api/users")
    def users(user: dict=Depends(admin)):
        return store.users()

    @app.post("/api/users",status_code=201)
    def new_user(data: NewUser,user: dict=Depends(admin)):
        return store.create_user(data.username,data.password,data.is_admin,user["username"])

    @app.post("/api/users/{identity}/disable")
    def disable_user(identity: str,user: dict=Depends(admin)):
        valid_id(identity);store.disable_user(identity,user);return {"ok":True}

    @app.get("/api/servers/{identity}/access")
    def access(identity: str,user: dict=Depends(admin)):
        store.require(user,identity,"manager");return store.user_access(identity)

    @app.post("/api/servers/{identity}/access")
    def grant(identity: str,data: Access,user: dict=Depends(admin)):
        store.require(user,identity,"manager")
        store.grant(data.user_id,identity,data.role,user["username"]);return {"ok":True}

    @app.get("/api/servers/{identity}/snapshot")
    def latest(identity: str,user: dict=Depends(current_user)):
        store.require(user,identity)
        return store.latest(identity)

    @app.get("/api/servers/{identity}/history")
    def history(identity: str,limit: int=240,user: dict=Depends(current_user)):
        store.require(user,identity);return store.history(identity,limit)

    @app.get("/api/servers/{identity}/commands")
    def commands(identity: str,user: dict=Depends(current_user)):
        store.require(user,identity);return store.commands(identity)

    @app.post("/api/servers/{identity}/commands",status_code=202)
    def command(identity: str,data: Command,user: dict=Depends(current_user)):
        return store.queue_command(user,identity,data.action,data.preset,data.expected_session)

    @app.get("/api/servers/{identity}/reports")
    def reports(identity: str,q: str="",user: dict=Depends(current_user)):
        store.require(user,identity);return store.reports(identity,q[:200])

    @app.get("/api/reports/{identity}")
    def report(identity: str,user: dict=Depends(current_user)):
        result=store.report(identity);store.require(user,result["server_id"]);return result

    @app.patch("/api/reports/{identity}")
    def annotate(identity: str,data: Annotation,user: dict=Depends(current_user)):
        item=store.report(identity);store.require(user,item["server_id"],"operator")
        store.annotate(identity,data.notes,data.tags,user["username"]);return {"ok":True}

    @app.get("/api/compare")
    def compare(before: str,after: str,user: dict=Depends(current_user)):
        a,b=store.report(before),store.report(after)
        store.require(user,a["server_id"]);store.require(user,b["server_id"])
        result=compare_reports(a["payload"],b["payload"])
        if a["server_id"]!=b["server_id"]:
            result["warnings"].insert(0,"These reports are from different servers.")
        return result

    @app.post("/api/reports/{identity}/share")
    def share(identity: str,data: Share,user: dict=Depends(current_user)):
        return store.share(identity,user,data.hours,data.include_locations)

    @app.post("/api/reports/{identity}/revoke-shares")
    def revoke_shares(identity: str,user: dict=Depends(current_user)):
        item=store.report(identity);store.require(user,item["server_id"],"manager")
        store.revoke_shares(identity,user["username"]);return {"ok":True}

    @app.get("/api/shared/{secret}")
    def shared(secret: str):
        if not 20<=len(secret)<=128:
            raise HTTPException(404,"Shared report not found")
        return store.shared(secret)

    @app.get("/api/servers/{identity}/runtime")
    def runtime(identity: str,user: dict=Depends(current_user)):
        store.require(user,identity);return store.runtime(identity)

    @app.get("/api/servers/{identity}/runtime-keys")
    def runtime_keys(identity: str,user: dict=Depends(current_user)):
        store.require(user,identity,"manager");return store.runtime_keys(identity)

    @app.post("/api/servers/{identity}/runtime-keys")
    def runtime_key(identity: str,data: RuntimeKey,user: dict=Depends(current_user)):
        store.require(user,identity,"manager");return store.create_runtime_key(identity,data.source,user["username"])

    @app.post("/api/servers/{identity}/runtime-keys/{key_id}/revoke")
    def revoke_runtime(identity: str,key_id: str,user: dict=Depends(current_user)):
        store.require(user,identity,"manager");valid_id(key_id)
        store.revoke_runtime_key(identity,key_id,user["username"]);return {"ok":True}

    @app.get("/api/audit")
    def audit(server_id: str | None=None,user: dict=Depends(current_user)):
        if server_id:
            store.require(user,server_id,"manager")
        elif not user["is_admin"]:
            raise HTTPException(403,"Select a server you manage to view its audit trail")
        return store.audit(user,server_id)

    @app.post("/api/agent/heartbeat")
    def heartbeat(data: Heartbeat,agent: dict=Depends(current_agent)):
        return {"commands":store.heartbeat(agent["id"],data.snapshot),"server_time_ms":now_ms()}

    async def native_object(request: Request) -> dict[str,Any]:
        try:
            value=json.loads(await request.body())
        except (UnicodeDecodeError,json.JSONDecodeError) as error:
            raise ValueError("Expected a JSON object") from error
        if not isinstance(value,dict):
            raise ValueError("Expected a JSON object")
        return value

    @app.post("/api/native/heartbeat")
    async def native_heartbeat(request: Request,agent: dict=Depends(current_agent)):
        commands=store.heartbeat(agent["id"],await native_object(request))
        wire=b"\n--oniprofiler-command--\n".join(encode_command(command) for command in commands)
        return Response(content=wire,media_type="application/x-oniprofiler-commands")

    @app.post("/api/native/report/{source_key}")
    async def native_report(source_key: str,request: Request,agent: dict=Depends(current_agent)):
        report=await native_object(request)
        identity,created=store.ingest_report(agent["id"],source_key,report)
        if created and report.get("kind")=="incident":
            notices.incident(agent["name"],report)
        return {"id":identity,"created":created}

    @app.post("/api/agent/report")
    def ingest_report(data: IncomingReport,agent: dict=Depends(current_agent)):
        identity,created=store.ingest_report(agent["id"],data.source_key,data.report)
        if created and data.report.get("kind")=="incident":
            notices.incident(agent["name"],data.report)
        return {"id":identity,"created":created}

    @app.post("/api/agent/ack")
    def ack(receipt: dict[str,Any],agent: dict=Depends(current_agent)):
        store.acknowledge(agent["id"],receipt);return {"ok":True}

    @app.post("/api/agent/runtime")
    def agent_runtime(data: RuntimeReport,agent: dict=Depends(current_agent)):
        store.put_runtime(agent["id"],data.source,data.report);return {"ok":True}

    @app.post("/api/runtime/report")
    def direct_runtime(report: dict[str,Any],request: Request):
        key=store.runtime_key(bearer(request))
        if not key:
            raise HTTPException(401,"Runtime token is invalid or revoked")
        store.put_runtime(key["server_id"],key["source"],report);return {"ok":True}

    @app.post("/api/agent/profile")
    async def upload_profile(request: Request,report_id: str,agent: dict=Depends(current_agent)):
        item=store.report(report_id)
        if item["server_id"]!=agent["id"]:
            raise HTTPException(404,"Report not found for this agent")
        if item["profile_hash"]:
            return {"sha256":item["profile_hash"],"bytes":item["profile_bytes"]}
        folder=settings.data_dir/"profiles";folder.mkdir(exist_ok=True,mode=0o700)
        if folder.is_symlink():
            raise HTTPException(500,"Profile storage path is invalid")
        temporary=folder/(secrets.token_hex(16)+".upload")
        size=0;hasher=hashlib.sha256()
        try:
            with temporary.open("xb") as output:
                async for chunk in request.stream():
                    size+=len(chunk)
                    if size>settings.max_profile_bytes:
                        raise HTTPException(413,"Native profile exceeds the configured size cap")
                    output.write(chunk);hasher.update(chunk)
            if size<2:
                raise HTTPException(422,"Native profile is empty")
            file_hash=hasher.hexdigest()
            with store.db() as db:
                db.execute("BEGIN IMMEDIATE")
                existing=db.execute("SELECT profile_hash FROM reports WHERE id=? AND server_id=?",(report_id,agent["id"])).fetchone()
                if not existing:
                    raise HTTPException(404,"Report expired during upload")
                if existing["profile_hash"]:
                    return {"sha256":existing["profile_hash"],"already_present":True}
                total=db.execute("SELECT coalesce(sum(profile_bytes),0) FROM reports").fetchone()[0]
                if total+size>2*1024**3:
                    raise HTTPException(413,"The control service's 2 GiB native-profile storage budget is full")
                destination=folder/(file_hash+".sparkprofile")
                if destination.is_symlink():
                    raise HTTPException(500,"Profile destination is invalid")
                if not destination.exists():
                    temporary.replace(destination)
                db.execute("UPDATE reports SET profile_hash=?,profile_bytes=? WHERE id=?",(file_hash,size,report_id))
                store.event(db,"agent","profile.uploaded",report_id,agent["id"])
            return {"sha256":file_hash,"bytes":size}
        finally:
            temporary.unlink(missing_ok=True)

    @app.get("/api/reports/{identity}/profile")
    def download_profile(identity: str,user: dict=Depends(current_user)):
        item=store.report(identity);store.require(user,item["server_id"])
        value=item["profile_hash"]
        if not value:
            raise HTTPException(404,"Native profile synchronization is off or the file has not arrived")
        path=settings.data_dir/"profiles"/(value+".sparkprofile")
        if path.is_symlink() or not path.is_file():
            raise HTTPException(404,"Native profile file is unavailable")
        return FileResponse(path,media_type="application/octet-stream",filename="OniProfiler-"+identity+".sparkprofile")

    app.mount("/static",StaticFiles(directory=STATIC),name="static")
    return app

def main() -> None:
    import uvicorn
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host",default="127.0.0.1")
    parser.add_argument("--port",type=int,default=8080)
    parser.add_argument("--allow-http-loopback",action="store_true")
    args=parser.parse_args()
    if args.allow_http_loopback:
        import os
        settings=Settings(Path(os.getenv("ONI_DATA_DIR","./oni-data")).resolve(),os.getenv("ONI_PUBLIC_ORIGIN","http://127.0.0.1:8080"),True)
    else:
        settings=Settings.environment()
    if settings.allow_http_loopback and args.host not in {"127.0.0.1","::1","localhost"}:
        parser.error("Insecure development mode may only bind loopback")
    uvicorn.run(create_app(settings),host=args.host,port=args.port,workers=1,proxy_headers=True,
                forwarded_allow_ips="127.0.0.1,::1",access_log=False,limit_concurrency=100,timeout_keep_alive=5)

if __name__=="__main__":
    main()
