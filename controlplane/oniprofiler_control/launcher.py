"""Run an outbound agent beside an existing server command; forward graceful shutdown signals."""
from __future__ import annotations
import argparse
import os
import signal
import subprocess
import sys
import time


def spawn(command: list[str], **kwargs) -> subprocess.Popen:
    # Process groups let a launcher reach the real loader/server children as well.
    if os.name=="nt":
        kwargs["creationflags"]=subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        kwargs["start_new_session"]=True
    return subprocess.Popen(command,**kwargs)


def request_stop(process: subprocess.Popen) -> None:
    """Request graceful group shutdown. Never force-terminate a game server here."""
    if process.poll() is not None:
        return
    try:
        if os.name=="nt":
            process.send_signal(signal.CTRL_BREAK_EVENT)
        else:
            os.killpg(process.pid,signal.SIGTERM)
    except ProcessLookupError:
        pass
    except OSError as error:
        print(f"OniProfiler could not forward a graceful stop signal: {error}. Stop the server through its normal console.",file=sys.stderr)


def close_agent(agent: subprocess.Popen) -> None:
    request_stop(agent)
    try:
        agent.wait(timeout=20)
    except subprocess.TimeoutExpired:
        # This is only the auxiliary agent, never the game process.
        agent.kill();agent.wait()


def main() -> None:
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--agent-config",required=True)
    parser.add_argument("command",nargs=argparse.REMAINDER)
    args=parser.parse_args()
    command=args.command[1:] if args.command and args.command[0]=="--" else args.command
    if not command:
        parser.error("Provide the existing server launch command after --")
    agent_command=[sys.executable,"-m","oniprofiler_control.agent","--config",args.agent_config]
    agent=spawn(agent_command,stdin=subprocess.DEVNULL)
    try:
        server=spawn(command)
    except BaseException:
        close_agent(agent);raise
    stopping=False
    next_restart=0.0
    def stop(*_):
        nonlocal stopping
        stopping=True;request_stop(server)
    signals=[signal.SIGINT,signal.SIGTERM]
    if hasattr(signal,"SIGBREAK"):
        signals.append(signal.SIGBREAK)
    for sig in signals:
        signal.signal(sig,stop)
    try:
        while server.poll() is None:
            if agent.poll() is not None and not stopping and time.monotonic()>=next_restart:
                print("OniProfiler agent exited. The server remains running; inspect the agent configuration.",file=sys.stderr)
                agent=spawn(agent_command,stdin=subprocess.DEVNULL)
                next_restart=time.monotonic()+10
            time.sleep(0.25)
        raise SystemExit(server.returncode)
    finally:
        close_agent(agent)

if __name__=="__main__":
    main()
