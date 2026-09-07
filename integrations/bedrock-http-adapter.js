// SPDX-License-Identifier: GPL-3.0-only
// Optional BDS-only adapter. Enable the experimental server-net module and use a
// dedicated *runtime* token from OniProfiler. Never embed an agent or admin token.
import {http, HttpRequest, HttpRequestMethod} from "@minecraft/server-net";
import {secrets} from "@minecraft/server-admin";

export function createRuntimePublisher(origin, secretName = "oniprofiler_runtime_token") {
  if (!/^https:\/\/[A-Za-z0-9.-]+(?::[0-9]+)?$/.test(origin)) throw new Error("An HTTPS control-service origin is required");
  let pending = false;
  return async function publish(snapshot) {
    if (pending) return false;
    const token = secrets.get(secretName);
    if (!token) throw new Error("Runtime secret has not been provisioned in BDS");
    pending = true;
    try {
      const request = new HttpRequest(`${origin}/api/runtime/report`);
      request.setMethod(HttpRequestMethod.Post);
      request.setBody(JSON.stringify(snapshot));
      request.setTimeout(8);
      request.addHeader("Content-Type", "application/json");
      // BDS SecretString supports direct header values, not string concatenation.
      // Provision the entire value "Bearer <runtime token>" in the named secret.
      request.addHeader("Authorization", token);
      const result = await http.request(request);
      if (result.status < 200 || result.status >= 300) throw new Error(`Telemetry HTTP ${result.status}`);
      return true;
    } finally { pending = false; }
  };
}
