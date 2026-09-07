"""Local owner administration. Passwords are entered privately, not passed in arguments."""
from __future__ import annotations
import argparse
import getpass
import json
import os
from pathlib import Path
from .config import Settings
from .store import Store

def main() -> None:
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir",type=Path,default=Path(os.getenv("ONI_DATA_DIR","./oni-data")))
    sub=parser.add_subparsers(dest="action",required=True)
    sub.add_parser("init",help="Create the first administrator interactively")
    create=sub.add_parser("create-user");create.add_argument("username");create.add_argument("--admin",action="store_true")
    reset=sub.add_parser("reset-password");reset.add_argument("username")
    server=sub.add_parser("create-server");server.add_argument("name")
    backup=sub.add_parser("backup");backup.add_argument("destination",type=Path)
    args=parser.parse_args()
    # Local database administration does not bind a network socket.
    store=Store(Settings(args.data_dir.resolve(),"http://127.0.0.1:8080",True))
    if args.action=="init":
        if any(u["is_admin"] and u["active"] for u in store.users()):
            parser.error("An active administrator already exists. Use create-user or reset-password locally.")
        username=input("Administrator username: ").strip()
        password=getpass.getpass("Password (at least 14 characters): ")
        if password!=getpass.getpass("Repeat password: "):
            parser.error("Passwords do not match")
        print(json.dumps(store.create_user(username,password,True),indent=2))
    elif args.action=="create-user":
        print(json.dumps(store.create_user(args.username,getpass.getpass("Password (at least 14 characters): "),args.admin),indent=2))
    elif args.action=="reset-password":
        store.reset_password(args.username,getpass.getpass("New password (at least 14 characters): "))
        print("Password updated; existing sessions revoked.")
    elif args.action=="create-server":
        print(json.dumps(store.create_server(args.name,"local-admin"),indent=2))
        print("Store the agent token securely. It cannot be retrieved later.")
    elif args.action=="backup":
        store.backup(args.destination)
        print("Database backup written. Back up the profiles directory separately for native files.")

if __name__=="__main__":
    main()
