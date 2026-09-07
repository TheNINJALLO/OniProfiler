# OniProfiler contributor instructions

Product: OniProfiler powered by spark. GitHub owner for this project is
TheNINJALLO; the display identity may use TheN1NJ4LL0. This project integrates the
GPL-3.0 EndstoneMC/spark engine. Do not erase upstream attribution or rename
native internals merely to make upstream work look original.

Read README.md, VALIDATION.md, docs/ARCHITECTURE.md and docs/SMOKE_TEST.md first.
The source release candidate has not been validated against a running BDS process. Never
report native compilation, CI success, runtime compatibility or performance
improvement without executing the relevant checks and recording their results.

Do not weaken tools/patch_engine.py blob checks. Upstream revisions are pinned in
that file and upstream/manifest.json. Change them only after source/API review.
Keep Endstone API calls on the server thread. Workers must receive immutable
snapshots and must not dereference players, chunks or server objects.

Preserve unknown/null metrics, scope/window labels, symbol uncertainty and
local-only defaults. Permission checks must apply to forms, advanced commands
and legacy aliases. Stale forms cannot mutate a new native session. Entity count
is not CPU cost. No automatic destructive "fix lag" workflows.

Run:
  python -m pip install -e 'controlplane[test]'
  cmake -S . -B build/offline -DONIPROFILER_OFFLINE_TESTS_ONLY=ON -DCMAKE_BUILD_TYPE=Debug
  cmake --build build/offline --parallel 2
  ctest --test-dir build/offline --output-on-failure
  node --check web/app.js

Native build commands and staging gates are in README.md and docs/SMOKE_TEST.md.
Do not publish source, releases or existing-repository changes without the user's
authorization. The bundled publisher creates a new repository only.
