// SPDX-License-Identifier: GPL-3.0-only
// Pure timing core shared by Node.js and Bedrock Script adapters. No global hooks.
export function createProfiler({source, runtime = "nodejs", clock = () => globalThis.performance?.now?.() ?? Date.now()}) {
  if (!/^[A-Za-z0-9_.@-]{1,80}$/.test(source)) throw new Error("Invalid telemetry source");
  let start = clock();
  let callbacks = new Map();
  function record(name, begin, error) {
    if (!callbacks.has(name) && callbacks.size >= 199) name = "other-instrumented-callbacks";
    const row = callbacks.get(name) ?? {name, count: 0, total_ms: 0, max_ms: 0, errors: 0};
    const elapsed = Math.max(0, clock() - begin);
    if (!Number.isFinite(elapsed)) return;
    row.count += 1; row.total_ms += elapsed; row.max_ms = Math.max(row.max_ms, elapsed); row.errors += error ? 1 : 0;
    callbacks.set(name, row);
  }
  function label(name) {
    if (typeof name !== "string" || name.length < 1 || name.length > 200) throw new Error("Invalid callback label");
  }
  return {
    wrap(name, fn) {
      label(name);
      return function (...args) {
        const begin = clock();
        let failed = false;
        try { return fn.apply(this, args); }
        catch (error) { failed = true; throw error; }
        finally { record(name, begin, failed); }
      };
    },
    wrapAsync(name, fn) {
      label(name);
      return async function (...args) {
        const begin = clock();
        let failed = false;
        try { return await fn.apply(this, args); }
        catch (error) { failed = true; throw error; }
        finally { record(name, begin, failed); }
      };
    },
    snapshot(reset = true) {
      const end = clock();
      const result = {schema_version: 1, source, runtime, generated_ms: Date.now(),
        window_ms: Math.max(0.001, end - start), unit: "elapsed_wall_ms",
        coverage: "Only explicitly instrumented callbacks. Nested measurements overlap. wrapAsync includes await time; wrap measures only synchronous invocation. Not total CPU or full plugin cost.",
        callbacks: [...callbacks.values()].map(row => ({...row})).sort((a,b) => b.total_ms-a.total_ms)};
      if (reset) { callbacks = new Map(); start = end; }
      return result;
    }
  };
}
