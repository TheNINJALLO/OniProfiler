#!/usr/bin/env bash
# Clang/libc++ 20 is an intentional native ABI choice, not the latest compiler.
set -euo pipefail
. /etc/os-release
[[ "${VERSION_CODENAME}" == noble ]] || { echo "This setup script requires Ubuntu 24.04 (noble)." >&2; exit 1; }
sudo apt-get update
sudo apt-get install -y ca-certificates curl gnupg ninja-build pkg-config
key="$(mktemp)"
trap 'rm -f "$key" "$key.gpg"' EXIT
curl --fail --silent --show-error --location --proto '=https' --tlsv1.2 https://apt.llvm.org/llvm-snapshot.gpg.key -o "$key"
fingerprint="$(gpg --batch --show-keys --with-colons "$key" | awk -F: '$1=="fpr" {print $10; exit}')"
[[ "$fingerprint" == '6084F3CF814B57C1CF12EFD515CF4D18AF4F7421' ]] || { echo 'LLVM signing key fingerprint mismatch.' >&2; exit 1; }
gpg --batch --dearmor --output "$key.gpg" "$key"
sudo install -m 0644 "$key.gpg" /usr/share/keyrings/oniprofiler-llvm.gpg
printf '%s\n' 'deb [signed-by=/usr/share/keyrings/oniprofiler-llvm.gpg] https://apt.llvm.org/noble/ llvm-toolchain-noble-20 main' | sudo tee /etc/apt/sources.list.d/oniprofiler-llvm.list >/dev/null
sudo apt-get update
sudo apt-get install -y clang-20 lld-20 libc++-20-dev libc++abi-20-dev
sudo ln -sf /usr/bin/clang-20 /usr/local/bin/clang
sudo ln -sf /usr/bin/clang++-20 /usr/local/bin/clang++
clang --version | grep -E 'clang version 20\.'
