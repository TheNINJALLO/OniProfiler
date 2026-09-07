/* SPDX-License-Identifier: GPL-3.0-only */
(function (root) {
  "use strict";
  const object = (v) => v !== null && typeof v === "object" && !Array.isArray(v);
  const finite = (v) => typeof v === "number" && Number.isFinite(v);
  const text = (v, max = 2000) => typeof v === "string" ? v.slice(0, max) : "";
  const numeric = (v) => finite(v) ? v : null;
  const arr = (v, max) => Array.isArray(v) ? v.slice(0, max) : [];
  function health(v) {
    if (!object(v)) throw new Error("The report has no valid health snapshot.");
    const out = {};
    for (const key of ["timestamp_ms", "history_ms", "tps_span_ms", "mspt_span_ms", "cpu_span_ms", "tick_samples", "tps", "mspt_mean", "mspt_p95", "mspt_max", "cpu_percent", "rss_bytes", "players", "entities", "chunks"]) out[key] = numeric(v[key]);
    return out;
  }
  function validate(v) {
    if (!object(v) || v.schema_version !== 1 || v.product !== "OniProfiler powered by spark") throw new Error("Choose an OniProfiler schema-version 1 JSON report, not a native .sparkprofile file.");
    if (!["dashboard", "health", "incident", "recording"].includes(v.kind)) throw new Error("Unsupported report kind.");
    if (!finite(v.generated_ms) || v.generated_ms <= 0) throw new Error("The report has no valid generation timestamp.");
    const out = {schema_version: 1, product: v.product, version: text(v.version, 80), kind: v.kind, generated_ms: v.generated_ms, demo: v.demo === true,
      title: text(v.title, 180), health: health(v.health), session: {description: text(v.session?.description)},
      history: arr(v.history, 1000).filter(object).map(health),
      findings: arr(v.findings, 30).filter(object).map(f => ({level: ["ok","warning","critical","info","unknown"].includes(f.level) ? f.level : "unknown", evidence: text(f.evidence, 80), title: text(f.title, 200), detail: text(f.detail)})),
      limitations: arr(v.limitations, 30).map(x => text(x)),
      native_reports: arr(v.native_reports, 100).filter(object).map(r => ({owner: text(r.owner, 200), time_ms: numeric(r.time_ms), type: text(r.type, 100), storage: r.storage === "url" ? "url" : "file", result: text(r.result, 4000)})),
      recording: null, loaded_areas: {snapshot_ms: numeric(v.loaded_areas?.snapshot_ms), areas: []}};
    out.loaded_areas.areas = arr(v.loaded_areas?.areas, 1000).filter(object).map(a => ({dimension: text(a.dimension, 200), chunk_x: numeric(a.chunk_x), chunk_z: numeric(a.chunk_z), entities: numeric(a.entities),
      types: object(a.types) ? Object.entries(a.types).slice(0, 200).filter(([, n]) => finite(n) && n >= 0).map(([name, count]) => ({name: text(name, 200), count})) : []}));
    if (object(v.recording)) {
      const r = v.recording;
      out.recording = {id: text(r.id, 80), title: text(r.title, 200), preset: text(r.preset, 80), owner: text(r.owner, 200), started_ms: numeric(r.started_ms),
        mode: text(r.mode, 80), interval: numeric(r.interval), only_ticks_over_ms: numeric(r.only_ticks_over_ms), samples: numeric(r.samples), dropped_samples: numeric(r.dropped_samples), native_outcome: text(r.native_outcome, 80), native_result: text(r.native_result, 4000)};
    }
    return out;
  }
  function compatibility(a, b) {
    const warnings = [];
    if (a === b) warnings.push("A and B are the same imported report.");
    if (a.demo || b.demo) warnings.push("At least one report contains demonstration data, not server measurements.");
    if (a.health.players !== b.health.players) warnings.push("Player counts differ. The workloads may not be comparable.");
    if (a.health.mspt_span_ms !== b.health.mspt_span_ms) warnings.push("Tick measurement windows differ.");
    if ((a.health.history_ms ?? 0) < 10000 || (b.health.history_ms ?? 0) < 10000) warnings.push("One report has less than 10 seconds of baseline history.");
    if ((a.health.tick_samples ?? 0) < 20 || (b.health.tick_samples ?? 0) < 20) warnings.push("One report has too few valid tick samples for a useful comparison.");
    for (const key of ["mode", "interval", "only_ticks_over_ms"]) if (a.recording?.[key] !== b.recording?.[key]) warnings.push("Native recording settings differ: " + key.replaceAll("_", " ") + ".");
    if (a.recording?.preset !== b.recording?.preset) warnings.push("Investigation presets differ.");
    if (a.recording?.dropped_samples > 0 || b.recording?.dropped_samples > 0) warnings.push("One native recording dropped samples. Review its coverage before drawing conclusions.");
    return warnings;
  }
  function delta(a, b) { return finite(a) && finite(b) ? {absolute: b-a, percent: a === 0 ? null : (b-a)/Math.abs(a)*100} : null; }
  const api = {validate, compatibility, delta, finite};
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  else root.OniData = api;
})(typeof globalThis !== "undefined" ? globalThis : this);
