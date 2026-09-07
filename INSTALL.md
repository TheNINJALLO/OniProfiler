# Install OniProfiler

OniProfiler is a native Endstone plugin. Use exactly one game-plugin binary for the server's operating system.

## Linux

1. Download `endstone_oniprofiler.so` directly from the GitHub release.
2. Stop the server completely.
3. Remove any standalone `endstone_spark.so`; OniProfiler already includes the Spark engine.
4. Copy the file to `bedrock_server/plugins/endstone_oniprofiler.so`.
5. Start the server and look for the early `OniProfiler ... native plugin loaded` message.

The release Linux binary is built on Ubuntu 22.04 and packaging rejects a requirement newer than `GLIBC_2.35`. Check a host with `ldd --version` if the loader reports a GLIBC error.

## Windows

1. Download `endstone_oniprofiler.dll` directly from the GitHub release.
2. Stop the server completely.
3. Remove any standalone `endstone_spark.dll`.
4. Copy the file to `bedrock_server/plugins/endstone_oniprofiler.dll`.
5. Start the server and look for the early `OniProfiler ... native plugin loaded` message.

## Important file distinction

- `endstone_oniprofiler.so` and `endstone_oniprofiler.dll` are the game plugins.
- `oniprofiler_control-*.whl` runs only on the optional central dashboard host. It is not installed on an Endstone game server and is not an Endstone plugin.
- `OniProfiler-*-x86_64.zip` is the complete platform bundle. Extract it before using its contents; Endstone does not load that ZIP.

Use a full stop/start when changing this native plugin. Hot reload is not supported. Run `/oniprofiler` after startup and follow [docs/SMOKE_TEST.md](docs/SMOKE_TEST.md) before production use.

To link the live dashboard, let the plugin generate `plugins/oniprofiler/oniprofiler.toml`, paste the dashboard URL and one-time server token into that file, set `dashboard_enabled = true`, and restart. The native `.so` or `.dll` performs the connection itself.
