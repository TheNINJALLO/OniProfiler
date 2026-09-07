// SPDX-License-Identifier: GPL-3.0-only
import {mkdir, writeFile, rename, lstat, unlink} from "node:fs/promises";
import {join} from "node:path";
import {randomUUID} from "node:crypto";
// Call from an owner-controlled path; never pass player-provided filenames.
export async function exportSnapshot(profiler, directory) {
  const snapshot = profiler.snapshot();
  if (!/^[A-Za-z0-9_.@-]{1,80}$/.test(snapshot.source)) throw new Error("Invalid telemetry source");
  await mkdir(directory, {recursive: true, mode: 0o700});
  if ((await lstat(directory)).isSymbolicLink()) throw new Error("Telemetry directory must not be a symlink");
  const destination = join(directory, `${snapshot.source}.json`);
  try { if ((await lstat(destination)).isSymbolicLink()) throw new Error("Telemetry file must not be a symlink"); }
  catch (error) { if (error.code !== "ENOENT") throw error; }
  const temporary = join(directory, `${snapshot.source}.${randomUUID()}.tmp`);
  try {
    await writeFile(temporary, JSON.stringify(snapshot), {mode: 0o600, flag: "wx"});
    await rename(temporary, destination);
  } finally { await unlink(temporary).catch(error => { if(error.code !== "ENOENT") throw error; }); }
}
