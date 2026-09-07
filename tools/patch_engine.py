#!/usr/bin/env python3
"""Apply a small, reversible, content-verified integration to a pinned Spark checkout.

No line-number patches and no silent best-effort substitutions. The complete input
blob must match the inspected upstream revision. Re-running this script is safe.
"""
from __future__ import annotations
import argparse
import hashlib
from pathlib import Path

SPARK_COMMIT = "8958173ad40c1da9adf3254305526443c9853848"
ENDSTONE_COMMIT = "8f84d6f5b556916597ed5b6b71329b2ed3ca8fc8"
PAPI_COMMIT = "3bc3dbf99010e7af09b967d913b5b6a7e182e989"

API = '''    // ONIPROFILER_INTEGRATION: main-thread-only structured access.
    struct OniSessionSnapshot {
        bool running = false, background = false, exporting = false, allocation = false;
        std::string owner;
        std::int64_t started_ms = 0, ends_ms = 0, threshold = 0;
        int interval = 0;
        std::uint64_t samples = 0, dropped = 0;
    };
    struct OniExportReceipt {
        std::uint64_t sequence = 0;
        std::int64_t started_ms = 0;
        ExportOutcome outcome = ExportOutcome::Failed;
        std::string result;
        std::uint64_t samples = 0, dropped = 0;
    };
    OniSessionSnapshot oniStatus() const {
        OniSessionSnapshot s;
        s.running = running(); s.background = isBackgroundRunning(); s.exporting = exporting();
        s.allocation = profiler_.mode() == ProfileMode::Allocation;
        s.owner = start_sender_name_; s.started_ms = profiler_.startTimeMs();
        s.ends_ms = profiler_.autoEndTimeMs(); s.threshold = profiler_.options().only_ticks_over_ms;
        s.interval = s.allocation ? profiler_.options().allocation_interval_bytes : profiler_.options().interval_ms;
        s.samples = profiler_.sampleCount(); s.dropped = profiler_.droppedSamples();
        return s;
    }
    OniExportReceipt oniLastExport() const { return oni_last_export_; }
    void oniSetBackgroundEnabled(bool enabled) {
        oni_resume_background_ = true;
        background_enabled_ = enabled;
        if (!enabled) restart_background_after_export_ = false;
        if (!running()) { background_started_ = false; background_suppressed_ = !enabled; }
        // Caller cancels an existing background session separately, on the main thread.
    }

'''
RECEIPT = '''    // ONIPROFILER_INTEGRATION: bind a structured result to the native session.
    oni_last_export_ = {oni_last_export_.sequence + 1, profiler_.startTimeMs(),
                        pending_outcome_, pending_result_, profiler_.sampleCount(), profiler_.droppedSamples()};
'''
RESUME = '''    // ONIPROFILER_INTEGRATION: an enabled policy resumes after stop, cancel,
    // timeout or failed export. Disabling the policy is the explicit pause action.
    // Preserve the upstream retry backoff rather than retrying on every tick.
    if (oni_resume_background_ && background_enabled_ && !profiler_.running() && !exporting_.load()) {
        background_suppressed_ = false;
        background_started_ = false;
    }
'''
PATCHES: dict[str, tuple[str, list[tuple[str, str]]]] = {
    "src/application/spark_application.h": (
        "4350c8ee8562dd9aba97ecc0aeceef404b30a0c9", [
            ("    StatisticsService &statistics() { return statistics_; }",
             "    ProfilerService &profilerService() { return profiler_; }  // ONIPROFILER_INTEGRATION\n    StatisticsService &statistics() { return statistics_; }")]),
    "src/application/profiler/profiler_service.h": (
        "a6014a920f8d7cda6b3286ce69d5509e6b838159", [
            ("class ProfilerService {\npublic:\n", "class ProfilerService {\npublic:\n" + API),
            ("    StatisticsService &statistics_;", "    OniExportReceipt oni_last_export_;\n    bool oni_resume_background_ = false;\n    StatisticsService &statistics_;")]),
    "src/application/profiler/profiler_service.cpp": (
        "caa271ddccb62adf91b6374f9925598aa09f4b52", [
            ("void ProfilerService::announceResult()\n{\n", "void ProfilerService::announceResult()\n{\n" + RECEIPT),
            ("void ProfilerService::onTick(double mspt)\n{\n", "void ProfilerService::onTick(double mspt)\n{\n" + RESUME)]),
    "tests/CMakeLists.txt": ("c0635ba54ce5b39c1bf47cce77296359ea084d36", [
        ("${CMAKE_SOURCE_DIR}/tests/" + name, "${CMAKE_CURRENT_SOURCE_DIR}/" + name)
        for name in ["test_architecture_boundaries.py", "test_release_changelog.py", "test_profile_evaluator.py", "test_workflows.py"]]),
    "CMakeLists.txt": ("47570dbaecd4ebfb31f232c53aa742ab27a7d59e", [
        ("        GIT_TAG v0.11)", f"        GIT_TAG {ENDSTONE_COMMIT})"),
        ('set(ENDSTONE_SPARK_PAPI_GIT_TAG "main" CACHE STRING', f'set(ENDSTONE_SPARK_PAPI_GIT_TAG "{PAPI_COMMIT}" CACHE STRING'),
        ('        GIT_SHALLOW TRUE\n        SOURCE_SUBDIR cmake/headers-only)', '        GIT_SHALLOW FALSE\n        SOURCE_SUBDIR cmake/headers-only)')]),
}

def git_blob_sha(data: bytes) -> str:
    return hashlib.sha1(b"blob " + str(len(data)).encode("ascii") + b"\0" + data).hexdigest()

def transform(data: bytes, expected_sha: str, replacements: list[tuple[str, str]]) -> bytes:
    text = data.decode("utf-8")
    # Reverse our own changes before checking the complete upstream blob.
    for old, new in reversed(replacements):
        if new in text:
            if text.count(new) != 1:
                raise ValueError("Ambiguous already-applied patch")
            text = text.replace(new, old, 1)
    original = text.encode("utf-8")
    if git_blob_sha(original) != expected_sha:
        raise ValueError(f"Unexpected source blob: wanted {expected_sha}, found {git_blob_sha(original)}")
    for old, new in replacements:
        if text.count(old) != 1:
            raise ValueError(f"Patch anchor missing or ambiguous: {old[:70]!r}")
        text = text.replace(old, new, 1)
    return text.encode("utf-8")

def patch(root: Path) -> None:
    changes: dict[Path, bytes] = {}
    for name, (sha, replacements) in PATCHES.items():
        path = root / name
        changes[path] = transform(path.read_bytes(), sha, replacements)
    # Validate every file before changing any of them.
    for path, result in changes.items():
        if path.read_bytes() != result:
            path.write_bytes(result)
    print(f"OniProfiler integration verified against Spark {SPARK_COMMIT}")

def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("engine", type=Path)
    args = parser.parse_args()
    patch(args.engine.resolve())

if __name__ == "__main__":
    main()
