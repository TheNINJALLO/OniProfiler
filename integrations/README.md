# Opt-in runtime instrumentation

These SDKs measure only callbacks you deliberately wrap. They do not monkey-patch Endstone, scan all Python frames, or automatically instrument every JavaScript add-on. Native Spark profiling remains separate. Timings are **elapsed wall milliseconds**, not CPU percentages. Nested spans overlap and async spans include await time.

## Python plugins

Install the control-plane wheel into the Python environment that executes the plugin, or package the module under your normal dependency process. Create one instrumentor with a stable source name per plugin:

```python
from pathlib import Path
from oniprofiler_control.sdk import Instrumentor

# Resolve this from your actual server/plugin configuration, not player input.
profiler = Instrumentor("MyShopPlugin", Path("plugins/oniprofiler/runtime"))
profiler.start_exporter(interval_seconds=15)

@profiler.callback("shop.open")
def open_shop(player):
    return existing_open_shop(player)

@profiler.callback("database.lookup")
async def lookup_price(item):
    return await existing_lookup_price(item)

# In the plugin's shutdown handler:
# profiler.stop_exporter()
```

The example's `existing_*` functions stand for the application's own callbacks. Integrate the wrapper around those real functions; do not paste a second disconnected callback. The exporter writes snapshots from a worker thread. No Endstone APIs are called by that worker. Match the runtime output folder to the actual native plugin data directory. Shut down the exporter on disable/reload. A failed filesystem write is logged and does not escape into the game callback, but the failed interval may be lost.

The Python `flush()` method is also available for your own worker scheduler. It performs filesystem I/O and must not be called every server tick. No final synchronous disk flush is forced by `stop_exporter()`.

## Node-based scripting integrations

Copy `runtime-sdk.mjs` and `node-exporter.mjs` into the plugin/project. This route requires a Node environment with filesystem access, not the vanilla sandboxed Bedrock script runtime:

```javascript
import {createProfiler} from "./runtime-sdk.mjs";
import {exportSnapshot} from "./node-exporter.mjs";

const profiler = createProfiler({source: "MyNodePlugin", runtime: "nodejs"});
const wrapped = profiler.wrap("shop.open", existingOpenShop);
// Register `wrapped` in the application's normal event or task registration.

let exporting = false;
const timer = setInterval(async () => {
  if (exporting) return;
  exporting = true;
  try {
    await exportSnapshot(profiler, "plugins/oniprofiler/runtime");
  } catch {
    console.warn("OniProfiler callback snapshot export failed");
  } finally {
    exporting = false;
  }
}, 15000);
// On project shutdown: clearInterval(timer).
```

Use `wrapAsync` for Promise-returning callbacks whose whole awaited duration you intend to record. `wrap` measures synchronous invocation only and does not change the original return value. Use a clock appropriate to the actual runtime; the default prefers `performance.now()` and falls back to `Date.now()`.

The source identifier is bounded and used as the output filename. It is owner-controlled. Source count and callback label count are bounded; overflow labels are grouped. Native, Python and JavaScript totals are not additive CPU accounting.

## Bedrock dedicated-server HTTP publisher

`bedrock-http-adapter.js` is an optional **BDS-only experimental** adapter using `@minecraft/server-net` and `@minecraft/server-admin`. It is not a client/Realms integration. Match dependency module versions, module permissions and experiment requirements to the installed Bedrock dedicated server. This adapter has not been tested in a BDS runtime here. Do not invent a universal manifest version.

In the dashboard, a manager creates a **runtime-only credential** for the exact source identifier. Provision a named BDS secret, by default `oniprofiler_runtime_token`, containing the **entire** header value `Bearer <runtime_token>`. It is passed as a `SecretString` header value without string concatenation. Never use an agent token, dashboard password or panel key in the add-on.

```javascript
import {system} from "@minecraft/server";
import {createProfiler} from "./runtime-sdk.mjs";
import {createRuntimePublisher} from "./bedrock-http-adapter.js";

const profiler = createProfiler({source: "MyBedrockAddon", runtime: "bedrock-script"});
const publish = createRuntimePublisher("https://profiler.example.com");
const wrapped = profiler.wrap("crop.update", updateCrops);
// Register `wrapped` instead of `updateCrops` in the existing scheduling code.
const exportTask = system.runInterval(() => {
  publish(profiler.snapshot()).catch(() => console.warn("OniProfiler telemetry unavailable"));
}, 300);
// On shutdown: system.clearRun(exportTask).
```

Intervals here are game ticks, not guaranteed wall seconds under lag. The publisher has a one-request-in-flight guard and an eight-second HTTP timeout. It writes only this source's callback telemetry and cannot read reports or control recordings. No automatic upload of source code, player records or keys is implemented.

## Coverage and interpretation

The live dashboard shows counts, total, mean, maximum and error count for each submitted callback window. It labels stale windows and keeps coverage text visible. Timing a callback can itself add cost; measure overhead before broad instrumentation. For global interpreter/native attribution, use a separately validated runtime integration rather than relabeling these opt-in measurements as complete coverage.
