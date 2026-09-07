"""SQLite-backed users, scoped access, telemetry, reports and durable command receipts."""
from __future__ import annotations
from contextlib import contextmanager, closing
import json
from pathlib import Path
import secrets
import sqlite3
from typing import Any, Iterator
from .config import Settings
from .protocol import ACTIONS, PRESETS, TERMINAL, bounded_json, validate_snapshot, redact_for_share
from .security import digest, now_ms, password_hash, password_matches, token, valid_id, valid_name, REPORT_KEY

SCHEMA = """
CREATE TABLE IF NOT EXISTS users(id TEXT PRIMARY KEY, username TEXT NOT NULL UNIQUE,
 salt TEXT NOT NULL, password_hash TEXT NOT NULL, is_admin INTEGER NOT NULL DEFAULT 0,
 active INTEGER NOT NULL DEFAULT 1, created_ms INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS sessions(hash TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
 csrf TEXT NOT NULL, expires_ms INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS servers(id TEXT PRIMARY KEY, name TEXT NOT NULL, token_hash TEXT NOT NULL UNIQUE,
 active INTEGER NOT NULL DEFAULT 1, created_ms INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS grants(user_id TEXT REFERENCES users(id) ON DELETE CASCADE,
 server_id TEXT REFERENCES servers(id) ON DELETE CASCADE, role TEXT NOT NULL CHECK(role IN ('viewer','operator','manager')),
 PRIMARY KEY(user_id,server_id));
CREATE TABLE IF NOT EXISTS telemetry(server_id TEXT PRIMARY KEY REFERENCES servers(id) ON DELETE CASCADE,
 payload TEXT NOT NULL, received_ms INTEGER NOT NULL, generated_ms INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS history(id INTEGER PRIMARY KEY, server_id TEXT REFERENCES servers(id) ON DELETE CASCADE,
 received_ms INTEGER NOT NULL, payload TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS history_server_time ON history(server_id,received_ms);
CREATE TABLE IF NOT EXISTS reports(id TEXT PRIMARY KEY, server_id TEXT REFERENCES servers(id) ON DELETE CASCADE,
 source_key TEXT NOT NULL, kind TEXT NOT NULL, created_ms INTEGER NOT NULL, payload TEXT NOT NULL,
 notes TEXT NOT NULL DEFAULT '', tags TEXT NOT NULL DEFAULT '[]', profile_hash TEXT, profile_bytes INTEGER,
 UNIQUE(server_id,source_key));
CREATE INDEX IF NOT EXISTS reports_server_time ON reports(server_id,created_ms);
CREATE TABLE IF NOT EXISTS commands(id TEXT PRIMARY KEY, server_id TEXT REFERENCES servers(id) ON DELETE CASCADE,
 actor_id TEXT NOT NULL, actor TEXT NOT NULL, action TEXT NOT NULL, payload TEXT NOT NULL,
 status TEXT NOT NULL, created_ms INTEGER NOT NULL, expires_ms INTEGER NOT NULL,
 dispatched_ms INTEGER, result TEXT);
CREATE INDEX IF NOT EXISTS commands_server_state ON commands(server_id,status,created_ms);
CREATE TABLE IF NOT EXISTS shares(hash TEXT PRIMARY KEY, report_id TEXT REFERENCES reports(id) ON DELETE CASCADE,
 creator_id TEXT NOT NULL, expires_ms INTEGER NOT NULL, payload TEXT NOT NULL, revoked INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS runtime_keys(id TEXT PRIMARY KEY, server_id TEXT REFERENCES servers(id) ON DELETE CASCADE,
 source TEXT NOT NULL, hash TEXT NOT NULL UNIQUE, active INTEGER NOT NULL DEFAULT 1);
CREATE TABLE IF NOT EXISTS runtime(server_id TEXT REFERENCES servers(id) ON DELETE CASCADE,
 source TEXT NOT NULL, payload TEXT NOT NULL, received_ms INTEGER NOT NULL, PRIMARY KEY(server_id,source));
CREATE TABLE IF NOT EXISTS audit(id INTEGER PRIMARY KEY, time_ms INTEGER NOT NULL, actor TEXT NOT NULL,
 server_id TEXT, event TEXT NOT NULL, detail TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS login_attempts(key TEXT NOT NULL, time_ms INTEGER NOT NULL);
CREATE INDEX IF NOT EXISTS login_window ON login_attempts(key,time_ms);
PRAGMA user_version=1;
"""

class Store:
    def __init__(self, settings: Settings):
        self.settings = settings
        settings.data_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        if settings.data_dir.is_symlink():
            raise ValueError("Data directory must not be a symlink")
        self.path = settings.data_dir / "oniprofiler.sqlite3"
        if self.path.is_symlink():
            raise ValueError("Database must not be a symlink")
        with self.db() as db:
            db.execute("PRAGMA journal_mode=WAL")
            db.executescript(SCHEMA)
        try:
            self.path.chmod(0o600)
        except OSError:
            pass

    @contextmanager
    def db(self) -> Iterator[sqlite3.Connection]:
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        db.execute("PRAGMA busy_timeout=10000")
        try:
            with db:
                yield db
        finally:
            db.close()

    @staticmethod
    def event(db: sqlite3.Connection, actor: str, event: str, detail: str = "", server_id: str | None = None) -> None:
        db.execute("INSERT INTO audit(time_ms,actor,server_id,event,detail) VALUES(?,?,?,?,?)",
                   (now_ms(),actor,server_id,event,detail[:1000]))

    def create_user(self, username: str, password: str, admin: bool = False, actor: str = "local-admin") -> dict[str, Any]:
        valid_name(username)
        salt, hashed = password_hash(password)
        identity = secrets.token_hex(16)
        with self.db() as db:
            if db.execute("SELECT 1 FROM users WHERE username=?",(username,)).fetchone():
                raise ValueError("That username already exists")
            db.execute("INSERT INTO users(id,username,salt,password_hash,is_admin,created_ms) VALUES(?,?,?,?,?,?)",
                       (identity,username,salt,hashed,int(admin),now_ms()))
            self.event(db,actor,"user.created",username)
        return {"id":identity,"username":username,"is_admin":bool(admin),"active":True}

    def reset_password(self, username: str, password: str) -> None:
        salt, hashed = password_hash(password)
        with self.db() as db:
            user = db.execute("SELECT id FROM users WHERE username=?",(username,)).fetchone()
            if not user:
                raise LookupError("User not found")
            db.execute("UPDATE users SET salt=?,password_hash=? WHERE id=?",(salt,hashed,user["id"]))
            db.execute("DELETE FROM sessions WHERE user_id=?",(user["id"],))
            self.event(db,"local-admin","user.password_reset",username)

    def login(self, username: str, password: str, client: str) -> dict[str, Any] | None:
        # Both an address-wide and address+account window prevent unbounded scrypt work.
        now = now_ms()
        keys = (digest("address:"+client),digest(client+":"+username))
        with self.db() as db:
            db.execute("BEGIN IMMEDIATE")
            db.execute("DELETE FROM login_attempts WHERE time_ms<?",(now-300000,))
            for key, limit in zip(keys,(40,8)):
                count = db.execute("SELECT count(*) FROM login_attempts WHERE key=?",(key,)).fetchone()[0]
                if count >= limit:
                    raise PermissionError("Too many sign-in attempts. Try again after the five-minute window.")
            db.executemany("INSERT INTO login_attempts(key,time_ms) VALUES(?,?)",[(k,now) for k in keys])
            row = db.execute("SELECT * FROM users WHERE username=?",(username,)).fetchone()
        salt = row["salt"] if row else "00"*16
        expected = row["password_hash"] if row else "00"*64
        verified = password_matches(password,salt,expected)
        if not verified or not row or not row["active"]:
            return None
        secret, csrf = token(), token()
        with self.db() as db:
            db.execute("INSERT INTO sessions(hash,user_id,csrf,expires_ms) VALUES(?,?,?,?)",
                       (digest(secret),row["id"],csrf,now+self.settings.session_hours*3600000))
            db.execute("DELETE FROM sessions WHERE expires_ms<?",(now,))
            self.event(db,row["username"],"session.created")
        return {"token":secret,"csrf":csrf,"id":row["id"],"username":row["username"],"is_admin":bool(row["is_admin"])}

    def session(self, secret: str) -> dict[str, Any] | None:
        if not 20 <= len(secret) <= 128:
            return None
        with self.db() as db:
            row = db.execute("SELECT users.id,users.username,users.is_admin,sessions.csrf FROM sessions JOIN users ON users.id=sessions.user_id WHERE sessions.hash=? AND sessions.expires_ms>? AND users.active=1",
                             (digest(secret),now_ms())).fetchone()
            return dict(row) if row else None

    def logout(self, secret: str) -> None:
        with self.db() as db:
            db.execute("DELETE FROM sessions WHERE hash=?",(digest(secret),))

    def require(self, user: dict[str, Any], server_id: str, minimum: str = "viewer") -> str:
        valid_id(server_id)
        with self.db() as db:
            if not db.execute("SELECT 1 FROM servers WHERE id=? AND active=1",(server_id,)).fetchone():
                raise LookupError("Server not found")
            if user["is_admin"]:
                return "manager"
            row = db.execute("SELECT role FROM grants WHERE user_id=? AND server_id=?",(user["id"],server_id)).fetchone()
            levels = {"viewer":0,"operator":1,"manager":2}
            if not row or levels[row["role"]] < levels[minimum]:
                raise PermissionError("You do not have access to this server action")
            return row["role"]

    def create_server(self, name: str, actor: str) -> dict[str, Any]:
        if not name.strip() or len(name) > 100:
            raise ValueError("Server name must contain 1 to 100 characters")
        identity, secret = secrets.token_hex(16), token()
        with self.db() as db:
            db.execute("INSERT INTO servers(id,name,token_hash,created_ms) VALUES(?,?,?,?)",(identity,name,digest(secret),now_ms()))
            self.event(db,actor,"server.created",name,identity)
        return {"id":identity,"name":name,"agent_token":secret,"notice":"Save this token now. It will not be shown again."}

    def rotate_server(self, server_id: str, actor: str) -> dict[str, str]:
        secret=token()
        with self.db() as db:
            if not db.execute("UPDATE servers SET token_hash=? WHERE id=? AND active=1",(digest(secret),server_id)).rowcount:
                raise LookupError("Server not found")
            db.execute("UPDATE commands SET status='expired' WHERE server_id=? AND status IN ('queued','dispatched')",(server_id,))
            self.event(db,actor,"server.token_rotated","Old agent token revoked",server_id)
        return {"agent_token":secret}

    def grant(self, user_id: str, server_id: str, role: str, actor: str) -> None:
        valid_id(user_id);valid_id(server_id)
        if role not in ("viewer","operator","manager","none"):
            raise ValueError("Invalid access role")
        with self.db() as db:
            if not db.execute("SELECT 1 FROM users WHERE id=?",(user_id,)).fetchone() or not db.execute("SELECT 1 FROM servers WHERE id=?",(server_id,)).fetchone():
                raise LookupError("User or server not found")
            if role == "none":
                db.execute("DELETE FROM grants WHERE user_id=? AND server_id=?",(user_id,server_id))
            else:
                db.execute("INSERT INTO grants VALUES(?,?,?) ON CONFLICT(user_id,server_id) DO UPDATE SET role=excluded.role",(user_id,server_id,role))
            db.execute("UPDATE commands SET status='expired' WHERE actor_id=? AND server_id=? AND status IN ('queued','dispatched')",(user_id,server_id))
            self.event(db,actor,"access.changed",f"user={user_id}; role={role}",server_id)

    def users(self) -> list[dict[str, Any]]:
        with self.db() as db:
            return [dict(row) for row in db.execute("SELECT id,username,is_admin,active FROM users ORDER BY username")]

    def user_access(self, server_id: str) -> list[dict[str, Any]]:
        with self.db() as db:
            return [dict(row) for row in db.execute("SELECT users.id,users.username,grants.role FROM grants JOIN users ON users.id=grants.user_id WHERE server_id=? ORDER BY users.username",(server_id,))]

    def disable_user(self, identity: str, actor: dict[str, Any]) -> None:
        if identity == actor["id"]:
            raise ValueError("You cannot disable your own account here")
        with self.db() as db:
            db.execute("UPDATE users SET active=0 WHERE id=?",(identity,))
            db.execute("DELETE FROM sessions WHERE user_id=?",(identity,))
            db.execute("UPDATE commands SET status='expired' WHERE actor_id=? AND status IN ('queued','dispatched')",(identity,))
            self.event(db,actor["username"],"user.disabled",identity)

    def agent(self, secret: str) -> dict[str, Any] | None:
        if not 20 <= len(secret) <= 128:
            return None
        with self.db() as db:
            row=db.execute("SELECT id,name FROM servers WHERE token_hash=? AND active=1",(digest(secret),)).fetchone()
            return dict(row) if row else None

    def servers(self, user: dict[str, Any]) -> list[dict[str, Any]]:
        with self.db() as db:
            if user["is_admin"]:
                rows=db.execute("SELECT servers.id,servers.name,telemetry.received_ms,telemetry.generated_ms,telemetry.payload,'manager' AS role FROM servers LEFT JOIN telemetry ON telemetry.server_id=servers.id WHERE servers.active=1 ORDER BY name").fetchall()
            else:
                rows=db.execute("SELECT servers.id,servers.name,telemetry.received_ms,telemetry.generated_ms,telemetry.payload,grants.role FROM servers JOIN grants ON grants.server_id=servers.id LEFT JOIN telemetry ON telemetry.server_id=servers.id WHERE grants.user_id=? AND servers.active=1 ORDER BY name",(user["id"],)).fetchall()
        result=[]
        for row in rows:
            item=dict(row);payload=json.loads(item.pop("payload") or "{}")
            item["health"]=payload.get("health",{});item["session"]=payload.get("session",{})
            item["agent_online"]=bool(item["received_ms"] and now_ms()-item["received_ms"]<30000)
            item["snapshot_fresh"]=bool(item["generated_ms"] and -30000<now_ms()-item["generated_ms"]<30000)
            result.append(item)
        return result

    def latest(self, server_id: str) -> dict[str, Any]:
        with self.db() as db:
            row=db.execute("SELECT * FROM telemetry WHERE server_id=?",(server_id,)).fetchone()
        return {"snapshot":json.loads(row["payload"]),"received_ms":row["received_ms"]} if row else {"snapshot":None,"received_ms":None}

    def heartbeat(self, server_id: str, snapshot: dict[str, Any]) -> list[dict[str, Any]]:
        validate_snapshot(snapshot);now=now_ms()
        if snapshot["generated_ms"] > now+60000:
            raise ValueError("Server clock is more than one minute ahead of the dashboard")
        payload=bounded_json(snapshot)
        with self.db() as db:
            db.execute("BEGIN IMMEDIATE")
            previous=db.execute("SELECT generated_ms FROM telemetry WHERE server_id=?",(server_id,)).fetchone()
            if previous and snapshot["generated_ms"] < previous["generated_ms"]:
                raise ValueError("Out-of-order telemetry rejected")
            db.execute("INSERT INTO telemetry VALUES(?,?,?,?) ON CONFLICT(server_id) DO UPDATE SET payload=excluded.payload,received_ms=excluded.received_ms,generated_ms=excluded.generated_ms",(server_id,payload,now,snapshot["generated_ms"]))
            last=db.execute("SELECT max(received_ms) FROM history WHERE server_id=?",(server_id,)).fetchone()[0]
            if (not previous or snapshot["generated_ms"]>previous["generated_ms"]) and (last is None or now-last>=15000):
                db.execute("INSERT INTO history(server_id,received_ms,payload) VALUES(?,?,?)",(server_id,now,bounded_json(snapshot["health"])))
            db.execute("DELETE FROM history WHERE server_id=? AND received_ms<?",(server_id,now-self.settings.history_hours*3600000))
            db.execute("UPDATE commands SET status='expired' WHERE server_id=? AND status IN ('queued','dispatched') AND expires_ms<=?",(server_id,now))
            # Recent snapshots only. An agent staying alive does not mean BDS is running.
            if now-snapshot["generated_ms"]>30000:
                return []
            rows=db.execute("SELECT id,payload FROM commands WHERE server_id=? AND status IN ('queued','dispatched') AND expires_ms>? AND (dispatched_ms IS NULL OR dispatched_ms<?) ORDER BY created_ms LIMIT 4",(server_id,now,now-10000)).fetchall()
            for row in rows:
                db.execute("UPDATE commands SET status='dispatched',dispatched_ms=? WHERE id=?",(now,row["id"]))
            # Keep receipt/audit growth bounded even on long-lived installations.
            db.execute("DELETE FROM commands WHERE server_id=? AND created_ms<? AND status NOT IN ('queued','dispatched')",(server_id,now-7*86400000))
            db.execute("DELETE FROM audit WHERE id NOT IN (SELECT id FROM audit ORDER BY id DESC LIMIT 10000)")
        return [json.loads(row["payload"]) for row in rows]

    def history(self, server_id: str, limit: int=240) -> list[dict[str, Any]]:
        with self.db() as db:
            rows=db.execute("SELECT received_ms,payload FROM history WHERE server_id=? ORDER BY id DESC LIMIT ?",(server_id,min(max(limit,1),1000))).fetchall()
        return [{"received_ms":r["received_ms"],"health":json.loads(r["payload"])} for r in reversed(rows)]

    def queue_command(self, user: dict[str, Any], server_id: str, action: str, preset: str="-", expected_session: int=0) -> dict[str, Any]:
        role=self.require(user,server_id,"operator")
        if action not in ACTIONS or (action=="record" and preset not in PRESETS) or (action!="record" and preset!="-"):
            raise ValueError("Unsupported profiler action or preset")
        management="-" in action or preset=="memory"
        if management and role!="manager":
            raise PermissionError("This action requires manager access")
        current=self.latest(server_id)
        snapshot=current["snapshot"]
        now=now_ms()
        if not snapshot or now-snapshot["generated_ms"]>30000 or now-(current["received_ms"] or 0)>30000:
            raise ValueError("No fresh server snapshot is available. Remote actions are disabled until the agent reconnects.")
        valid_id(snapshot.get("instance_id",""))
        capability=snapshot.get("capabilities",{})
        if not capability.get("remote_controls"):
            raise PermissionError("Remote controls are disabled in the plugin's local configuration")
        if management and not capability.get("remote_management"):
            raise PermissionError("Remote management is disabled in the plugin's local configuration")
        session=snapshot.get("session",{})
        if action in {"stop","cancel"}:
            if not session.get("running") or expected_session<=0 or expected_session!=session.get("started_ms"):
                raise ValueError("Recording changed; refresh the session before trying again")
            if role!="manager" and session.get("owner")!=user["username"]:
                raise PermissionError("Only the recording owner or a manager can stop this session")
        identity=secrets.token_hex(16)
        command={"id":identity,"instance":snapshot["instance_id"],"action":action,"preset":preset,
                 "actor":user["username"],"role":role,"issued_ms":now,"expires_ms":now+120000,
                 "expected_session":expected_session}
        with self.db() as db:
            db.execute("BEGIN IMMEDIATE")
            pending=db.execute("SELECT count(*) FROM commands WHERE server_id=? AND status IN ('queued','dispatched') AND expires_ms>?",(server_id,now)).fetchone()[0]
            if pending>=8:
                raise ValueError("This server already has eight pending requests")
            db.execute("INSERT INTO commands(id,server_id,actor_id,actor,action,payload,status,created_ms,expires_ms) VALUES(?,?,?,?,?,?,'queued',?,?)",(identity,server_id,user["id"],user["username"],action,bounded_json(command),now,command["expires_ms"]))
            self.event(db,user["username"],"command.queued",action,server_id)
        return {"id":identity,"status":"queued","expires_ms":command["expires_ms"]}

    def acknowledge(self, server_id: str, receipt: dict[str, Any]) -> None:
        valid_id(receipt.get("id",""))
        if receipt.get("status") not in TERMINAL or not isinstance(receipt.get("message",""),str):
            raise ValueError("Invalid command receipt")
        message=bounded_json(receipt,16384)
        with self.db() as db:
            row=db.execute("SELECT status FROM commands WHERE id=? AND server_id=?",(receipt["id"],server_id)).fetchone()
            if not row:
                raise LookupError("Request not found for this agent")
            if row["status"] in TERMINAL:
                return
            db.execute("UPDATE commands SET status=?,result=? WHERE id=?",(receipt["status"],message,receipt["id"]))
            self.event(db,"agent","command."+receipt["status"],receipt["id"],server_id)

    def commands(self, server_id: str) -> list[dict[str, Any]]:
        with self.db() as db:
            db.execute("UPDATE commands SET status='expired' WHERE server_id=? AND status IN ('queued','dispatched') AND expires_ms<=?",(server_id,now_ms()))
            rows=db.execute("SELECT id,actor,action,status,created_ms,expires_ms,result FROM commands WHERE server_id=? ORDER BY created_ms DESC LIMIT 100",(server_id,)).fetchall()
        return [{**dict(r),"result":json.loads(r["result"]) if r["result"] else None} for r in rows]

    def ingest_report(self, server_id: str, key: str, report: dict[str, Any]) -> tuple[str,bool]:
        if not isinstance(key,str) or not REPORT_KEY.fullmatch(key):
            raise ValueError("Invalid report filename")
        validate_snapshot(report)
        if report["generated_ms"]>now_ms()+60000:
            raise ValueError("Report timestamp is in the future")
        payload=bounded_json(report)
        identity=secrets.token_hex(16)
        with self.db() as db:
            row=db.execute("SELECT id FROM reports WHERE server_id=? AND source_key=?",(server_id,key)).fetchone()
            if row:
                return row["id"],False
            db.execute("INSERT INTO reports(id,server_id,source_key,kind,created_ms,payload) VALUES(?,?,?,?,?,?)",(identity,server_id,key,str(report.get("kind","health"))[:40],report["generated_ms"],payload))
            old=db.execute("SELECT id,profile_hash FROM reports WHERE server_id=? ORDER BY created_ms DESC LIMIT -1 OFFSET ?",(server_id,self.settings.report_limit)).fetchall()
            for row in old:
                db.execute("DELETE FROM reports WHERE id=?",(row["id"],))
            self.event(db,"agent","report.received",identity,server_id)
        self.remove_unreferenced_profiles([row["profile_hash"] for row in old if row["profile_hash"]])
        return identity,True

    def remove_unreferenced_profiles(self, hashes: list[str]) -> None:
        for value in hashes:
            if len(value)!=64 or any(c not in "0123456789abcdef" for c in value):
                continue
            with self.db() as db:
                used=db.execute("SELECT 1 FROM reports WHERE profile_hash=?",(value,)).fetchone()
            if not used:
                (self.settings.data_dir/"profiles"/(value+".sparkprofile")).unlink(missing_ok=True)

    def reports(self, server_id: str, query: str="") -> list[dict[str, Any]]:
        with self.db() as db:
            rows=db.execute("SELECT id,source_key,kind,created_ms,notes,tags,profile_hash,profile_bytes FROM reports WHERE server_id=? ORDER BY created_ms DESC LIMIT ?",(server_id,self.settings.report_limit)).fetchall()
        result=[{**dict(r),"tags":json.loads(r["tags"])} for r in rows]
        needle=query.lower()
        return [r for r in result if not needle or needle in (r["source_key"]+" "+r["kind"]+" "+r["notes"]+" "+" ".join(r["tags"])).lower()]

    def report(self, identity: str) -> dict[str, Any]:
        valid_id(identity)
        with self.db() as db:
            row=db.execute("SELECT * FROM reports WHERE id=?",(identity,)).fetchone()
        if not row:
            raise LookupError("Report not found")
        return {**dict(row),"payload":json.loads(row["payload"]),"tags":json.loads(row["tags"])}

    def annotate(self, identity: str, notes: str, tags: list[str], actor: str) -> None:
        if len(notes)>10000 or len(tags)>16 or any(not isinstance(t,str) or not 1<=len(t)<=40 for t in tags):
            raise ValueError("Notes or tags exceed the limits")
        report=self.report(identity)
        with self.db() as db:
            db.execute("UPDATE reports SET notes=?,tags=? WHERE id=?",(notes,json.dumps(tags),identity))
            self.event(db,actor,"report.annotated",identity,report["server_id"])

    def share(self, identity: str, user: dict[str, Any], hours: int, locations: bool) -> dict[str, Any]:
        if not 1<=hours<=168:
            raise ValueError("Sharing must expire within one hour to seven days")
        report=self.report(identity);self.require(user,report["server_id"],"manager")
        secret=token();expires=now_ms()+hours*3600000
        payload=redact_for_share(report["payload"],locations)
        with self.db() as db:
            db.execute("INSERT INTO shares(hash,report_id,creator_id,expires_ms,payload) VALUES(?,?,?,?,?)",(digest(secret),identity,user["id"],expires,bounded_json(payload)))
            self.event(db,user["username"],"report.shared",f"report={identity}; locations={locations}; hours={hours}",report["server_id"])
        return {"url":self.settings.origin+"/share/"+secret,"expires_ms":expires,"locations_included":locations}

    def shared(self, secret: str) -> dict[str, Any]:
        with self.db() as db:
            row=db.execute("SELECT payload,expires_ms FROM shares WHERE hash=? AND expires_ms>? AND revoked=0",(digest(secret),now_ms())).fetchone()
        if not row:
            raise LookupError("This shared report has expired or was revoked")
        return {"snapshot":json.loads(row["payload"]),"expires_ms":row["expires_ms"]}

    def revoke_shares(self, report_id: str, actor: str) -> None:
        report=self.report(report_id)
        with self.db() as db:
            db.execute("UPDATE shares SET revoked=1 WHERE report_id=?",(report_id,))
            self.event(db,actor,"report.shares_revoked",report_id,report["server_id"])

    def create_runtime_key(self, server_id: str, source: str, actor: str) -> dict[str,str]:
        valid_name(source);secret=token();identity=secrets.token_hex(16)
        with self.db() as db:
            db.execute("INSERT INTO runtime_keys VALUES(?,?,?,?,1)",(identity,server_id,source,digest(secret)))
            self.event(db,actor,"runtime.key_created",source,server_id)
        return {"id":identity,"runtime_token":secret,"source":source}

    def runtime_key(self, secret: str) -> dict[str, Any] | None:
        with self.db() as db:
            row=db.execute("SELECT runtime_keys.* FROM runtime_keys JOIN servers ON servers.id=runtime_keys.server_id WHERE runtime_keys.hash=? AND runtime_keys.active=1 AND servers.active=1",(digest(secret),)).fetchone()
            return dict(row) if row else None

    def runtime_keys(self, server_id: str) -> list[dict[str,Any]]:
        with self.db() as db:
            return [dict(r) for r in db.execute("SELECT id,source,active FROM runtime_keys WHERE server_id=?",(server_id,))]

    def revoke_runtime_key(self, server_id: str, identity: str, actor: str) -> None:
        with self.db() as db:
            db.execute("UPDATE runtime_keys SET active=0 WHERE id=? AND server_id=?",(identity,server_id))
            self.event(db,actor,"runtime.key_revoked",identity,server_id)

    def put_runtime(self, server_id: str, source: str, payload: dict[str,Any]) -> None:
        valid_name(source)
        text=bounded_json(payload,128*1024)
        if not isinstance(payload,dict):
            raise ValueError("Runtime telemetry must be an object")
        if payload.get("runtime") not in {"python","nodejs","bedrock-script"} or not isinstance(payload.get("callbacks"),list) or len(payload["callbacks"])>200:
            raise ValueError("Invalid runtime telemetry")
        if type(payload.get("window_ms")) not in (int,float) or payload["window_ms"]<=0:
            raise ValueError("Runtime window must be positive")
        for callback in payload["callbacks"]:
            if not isinstance(callback,dict) or not isinstance(callback.get("name"),str) or len(callback["name"])>200:
                raise ValueError("Invalid callback name")
            for name in ("count","total_ms","max_ms","errors"):
                if type(callback.get(name)) not in (int,float) or callback[name]<0:
                    raise ValueError("Invalid callback statistic")
            if type(callback["count"]) is not int or type(callback["errors"]) is not int or callback["errors"]>callback["count"] or callback["max_ms"]>callback["total_ms"]+0.000001:
                raise ValueError("Callback count or elapsed-time totals are inconsistent")
        with self.db() as db:
            previous=db.execute("SELECT received_ms FROM runtime WHERE server_id=? AND source=?",(server_id,source)).fetchone()
            if previous and now_ms()-previous["received_ms"]<1000:
                raise ValueError("Runtime telemetry is limited to one report per second per source")
            if not previous and db.execute("SELECT count(*) FROM runtime WHERE server_id=?",(server_id,)).fetchone()[0]>=100:
                raise ValueError("Runtime source limit reached")
            db.execute("INSERT INTO runtime VALUES(?,?,?,?) ON CONFLICT(server_id,source) DO UPDATE SET payload=excluded.payload,received_ms=excluded.received_ms",(server_id,source,text,now_ms()))

    def runtime(self, server_id: str) -> list[dict[str,Any]]:
        with self.db() as db:
            rows=db.execute("SELECT source,payload,received_ms FROM runtime WHERE server_id=? ORDER BY source",(server_id,)).fetchall()
        return [{"source":r["source"],"payload":json.loads(r["payload"]),"received_ms":r["received_ms"],"stale":now_ms()-r["received_ms"]>60000} for r in rows]

    def audit(self, user: dict[str,Any], server_id: str | None = None) -> list[dict[str,Any]]:
        with self.db() as db:
            if server_id:
                rows=db.execute("SELECT * FROM audit WHERE server_id=? ORDER BY id DESC LIMIT 200",(server_id,)).fetchall()
            elif user["is_admin"]:
                rows=db.execute("SELECT * FROM audit ORDER BY id DESC LIMIT 200").fetchall()
            else:
                rows=db.execute("SELECT * FROM audit WHERE server_id IN (SELECT server_id FROM grants WHERE user_id=?) ORDER BY id DESC LIMIT 200",(user["id"],)).fetchall()
        return [dict(r) for r in rows]

    def backup(self, destination: Path) -> None:
        destination=destination.resolve()
        if destination==self.path.resolve() or destination.exists():
            raise ValueError("Backup destination must be a new file, not the live database")
        with self.db() as source:
            with closing(sqlite3.connect(destination)) as target:
                source.backup(target)
        destination.chmod(0o600)
