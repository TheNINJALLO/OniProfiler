# Official LLVM 20.1.8 release asset. Its SHA-256 was checked against the LLVM release API.
$ErrorActionPreference = 'Stop'
$destination = Join-Path $env:RUNNER_TEMP 'OniLLVM20'
$installer = Join-Path $env:RUNNER_TEMP 'LLVM-20.1.8-win64.exe'
Invoke-WebRequest -Uri 'https://github.com/llvm/llvm-project/releases/download/llvmorg-20.1.8/LLVM-20.1.8-win64.exe' -OutFile $installer
$expected = '3197846a2b19063687dd56e93e34cd941e3548d907f23a6131571321bdf9fe7b'
if ((Get-FileHash $installer -Algorithm SHA256).Hash.ToLowerInvariant() -ne $expected) {
    throw 'LLVM installer checksum mismatch. The installer was not executed.'
}
# NSIS requires /D last, without quotes inside its argument.
$process = Start-Process -FilePath $installer -ArgumentList @('/S', "/D=$destination") -Wait -PassThru
if ($process.ExitCode -ne 0) { throw "LLVM installer failed with $($process.ExitCode)" }
$bin = Join-Path $destination 'bin'
$bin | Out-File -FilePath $env:GITHUB_PATH -Encoding utf8 -Append
$version = & (Join-Path $bin 'clang-cl.exe') --version
$version
if ($LASTEXITCODE -ne 0 -or -not ($version | Select-String 'clang version 20\.1\.8')) {
    throw 'Expected clang-cl 20.1.8 was not installed.'
}
