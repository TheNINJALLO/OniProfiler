"""Opt-in Python callback timing. Wall time is not CPU time or whole-interpreter coverage."""
from __future__ import annotations
from contextlib import contextmanager
from functools import wraps
import inspect
import json
import logging
from pathlib import Path
import threading
import time
from typing import Callable, Any
from .agent import atomic_private
from .security import valid_name

class Instrumentor:
    def __init__(self,source: str,output_directory: Path | None=None):
        self.source=valid_name(source)
        self.output_directory=output_directory
        self._lock=threading.Lock()
        self._callbacks: dict[str,dict[str,Any]]={}
        self._start=time.perf_counter_ns()
        self._export_stop=threading.Event()
        self._export_thread: threading.Thread | None=None

    def _record(self,name: str,elapsed_ms: float,error: bool) -> None:
        with self._lock:
            if name not in self._callbacks and len(self._callbacks)>=199:
                name="other-instrumented-callbacks"
            row=self._callbacks.setdefault(name,{"name":name,"count":0,"total_ms":0.0,"max_ms":0.0,"errors":0})
            row["count"]+=1;row["total_ms"]+=elapsed_ms;row["max_ms"]=max(row["max_ms"],elapsed_ms);row["errors"]+=int(error)

    @contextmanager
    def measure(self,name: str):
        if not isinstance(name,str) or not 1<=len(name)<=200:
            raise ValueError("Callback name must contain 1 to 200 characters")
        start=time.perf_counter_ns();failed=False
        try:
            yield
        except BaseException:
            failed=True;raise
        finally:
            self._record(name,(time.perf_counter_ns()-start)/1e6,failed)

    def callback(self,name: str | None=None):
        def decorate(function: Callable):
            label=name or function.__qualname__
            if inspect.iscoroutinefunction(function):
                @wraps(function)
                async def async_wrapper(*args,**kwargs):
                    with self.measure(label):
                        return await function(*args,**kwargs)
                return async_wrapper
            @wraps(function)
            def wrapper(*args,**kwargs):
                with self.measure(label):
                    return function(*args,**kwargs)
            return wrapper
        return decorate

    def snapshot(self,reset: bool=True) -> dict[str,Any]:
        end=time.perf_counter_ns()
        with self._lock:
            rows=[dict(v) for v in self._callbacks.values()]
            span=max((end-self._start)/1e6,0.001)
            if reset:
                self._callbacks.clear();self._start=end
        rows.sort(key=lambda r:r["total_ms"],reverse=True)
        return {"schema_version":1,"source":self.source,"runtime":"python","window_ms":span,
                "generated_ms":time.time_ns()//1_000_000,"timer":"perf_counter_ns", "unit":"elapsed_wall_ms",
                "coverage":"Only explicitly instrumented callbacks. Nested calls overlap; async callbacks include await time. Not total CPU or full plugin cost.","callbacks":rows}

    def flush(self) -> dict[str,Any]:
        result=self.snapshot()
        if self.output_directory is not None:
            atomic_private(self.output_directory/(self.source+".json"),json.dumps(result,allow_nan=False).encode())
        return result

    def start_exporter(self, interval_seconds: float=15.0) -> None:
        """Export immutable snapshots on a dedicated worker, not the game thread."""
        if self.output_directory is None:
            raise ValueError("Set an output_directory before starting the exporter")
        if not 5 <= interval_seconds <= 300:
            raise ValueError("Export interval must be between 5 and 300 seconds")
        if self._export_thread and self._export_thread.is_alive():
            raise RuntimeError("Exporter is already running")
        self._export_stop.clear()
        def run():
            while not self._export_stop.wait(interval_seconds):
                try:
                    self.flush()
                except (OSError, ValueError):
                    # Export failure never becomes an exception in a game callback.
                    logging.getLogger("oniprofiler.sdk").warning("Runtime snapshot export failed")
        self._export_thread=threading.Thread(target=run,name="oni-runtime-export",daemon=True)
        self._export_thread.start()

    def stop_exporter(self, timeout: float=10.0) -> bool:
        """Stop on plugin shutdown; return False if a filesystem operation is still blocked."""
        self._export_stop.set()
        if self._export_thread:
            self._export_thread.join(timeout)
            return not self._export_thread.is_alive()
        return True
