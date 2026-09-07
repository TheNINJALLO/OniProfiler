"""Bounded, evidence-preserving telemetry and a fixed-action control protocol."""
from __future__ import annotations
import copy
import json
import math
from typing import Any
from .security import valid_id, valid_name

ACTIONS = {"health", "scan", "record", "stop", "cancel", "background-on", "background-off",
           "incidents-on", "incidents-off", "automatic-on", "automatic-off"}
PRESETS = {"quick", "lag", "spikes", "memory"}
TERMINAL = {"applied", "rejected", "error", "expired", "indeterminate"}

def bounded_json(value: Any, max_bytes: int = 2*1024*1024) -> str:
    def check(v: Any, depth: int = 0) -> None:
        if depth > 16:
            raise ValueError("JSON nesting is too deep")
        if isinstance(v, dict):
            if len(v) > 2048:
                raise ValueError("JSON object has too many entries")
            for k, item in v.items():
                if not isinstance(k, str) or len(k) > 200:
                    raise ValueError("Invalid JSON key")
                check(item, depth+1)
        elif isinstance(v, list):
            if len(v) > 4096:
                raise ValueError("JSON array has too many entries")
            for item in v:
                check(item, depth+1)
        elif isinstance(v, str):
            if len(v) > 16384:
                raise ValueError("JSON string is too long")
        elif isinstance(v, float):
            if not math.isfinite(v):
                raise ValueError("Non-finite numbers are not accepted")
        elif isinstance(v, int):
            if abs(v) > 2**63-1:
                raise ValueError("Integer is outside the supported range")
        elif v is not None and not isinstance(v, bool):
            raise ValueError("Unsupported JSON value")
    check(value)
    text = json.dumps(value, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
    if len(text.encode()) > max_bytes:
        raise ValueError("JSON document exceeds the size limit")
    return text

def validate_snapshot(value: Any) -> dict[str, Any]:
    bounded_json(value)
    if not isinstance(value, dict) or type(value.get("schema_version")) is not int or value.get("schema_version") != 1 or not isinstance(value.get("health"), dict):
        raise ValueError("Expected an OniProfiler schema-version-1 report")
    generated = value.get("generated_ms")
    if type(generated) is not int or generated <= 0:
        raise ValueError("Report generated_ms must be a positive integer")
    for key in ("tps", "mspt_mean", "mspt_p95", "mspt_max", "cpu_percent", "rss_bytes", "players", "entities", "chunks", "tick_samples"):
        number = value["health"].get(key)
        if number is not None and (type(number) not in (int, float) or not math.isfinite(number) or number < 0):
            raise ValueError("Invalid numeric health field: " + key)
    if "instance_id" in value:
        valid_id(value["instance_id"])
    if not isinstance(value.get("session", {}), dict) or not isinstance(value.get("capabilities", {}), dict):
        raise ValueError("Invalid session or capabilities object")
    areas = value.get("loaded_areas", {})
    if not isinstance(areas, dict) or not isinstance(areas.get("areas", []), list):
        raise ValueError("Invalid loaded-area collection")
    for area in areas.get("areas", []):
        if not isinstance(area, dict) or not isinstance(area.get("dimension"), str) or len(area["dimension"]) > 200:
            raise ValueError("Invalid area dimension")
        for key in ("chunk_x", "chunk_z", "entities"):
            if type(area.get(key)) is not int:
                raise ValueError("Invalid area coordinate/count")
        if area["entities"] < 0 or not isinstance(area.get("types", {}), dict):
            raise ValueError("Invalid area counts")
        for count in area.get("types", {}).values():
            if type(count) is not int or count < 0:
                raise ValueError("Invalid entity-type count")
    return value

def encode_command(command: dict[str, Any]) -> bytes:
    valid_id(command["id"]); valid_id(command["instance"]); valid_name(command["actor"])
    if command["action"] not in ACTIONS or command["role"] not in {"operator", "manager"}:
        raise ValueError("Command is outside the allowlist")
    preset = command.get("preset", "-")
    if (command["action"] == "record" and preset not in PRESETS) or (command["action"] != "record" and preset != "-"):
        raise ValueError("Preset does not match the command")
    for key in ("issued_ms", "expires_ms", "expected_session"):
        if type(command.get(key)) is not int or not 0 <= command[key] <= 2**63-1:
            raise ValueError("Invalid command time or session")
    if not 0 < command["expires_ms"] - command["issued_ms"] <= 180000:
        raise ValueError("Invalid command lifetime")
    fields = {"protocol": 1, **{k: command[k] for k in ("id", "instance", "action")}, "preset": preset,
              **{k: command[k] for k in ("actor", "role", "issued_ms", "expires_ms", "expected_session")}}
    return ("\n".join(f"{k}={v}" for k, v in fields.items())+"\n").encode("ascii")

def redact_for_share(report: dict[str, Any], include_locations: bool = False) -> dict[str, Any]:
    # Allowlist, not a recursive blacklist. New private fields stay private by default.
    shared = {key: copy.deepcopy(report[key]) for key in ("schema_version", "product", "version", "kind", "generated_ms", "health", "findings", "limitations") if key in report}
    shared["share_notice"] = "Shared diagnostic snapshot. Identities, local paths, native profiles and notes are excluded."
    if include_locations:
        shared["loaded_areas"] = copy.deepcopy(report.get("loaded_areas", {}))
    else:
        shared["locations_redacted"] = True
    return shared

def compare_reports(a: dict[str, Any], b: dict[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {"metrics": [], "warnings": []}
    ah, bh = a.get("health", {}), b.get("health", {})
    for key in ("tps", "mspt_mean", "mspt_p95", "mspt_max", "rss_bytes", "players", "entities", "chunks"):
        x, y = ah.get(key), bh.get(key)
        valid = type(x) in (int, float) and type(y) in (int, float) and math.isfinite(x) and math.isfinite(y)
        result["metrics"].append({"metric":key,"before":x,"after":y,"delta":y-x if valid else None,
                                  "percent_change":100*(y-x)/x if valid and x != 0 else None})
    if ah.get("players") != bh.get("players"):
        result["warnings"].append("Player counts differ; workloads may not be comparable.")
    ar, br = a.get("recording") or {}, b.get("recording") or {}
    for key in ("mode", "interval", "only_ticks_over_ms"):
        if ar.get(key) != br.get(key):
            result["warnings"].append(f"Recording {key} settings differ.")
    for h in (ah, bh):
        if type(h.get("tick_samples")) not in (int,float) or h["tick_samples"] < 20:
            result["warnings"].append("At least one report has too few tick samples."); break
    result["warnings"].append("These are rolling snapshots, not full-session averages or proof of causation.")
    return result
