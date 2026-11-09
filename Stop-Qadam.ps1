$ErrorActionPreference = 'Stop'
$qadamPidPath = Join-Path $PSScriptRoot 'data\server.pid'
if (Test-Path -LiteralPath $qadamPidPath) {
    $qadamProcessId = [int](Get-Content -LiteralPath $qadamPidPath -Raw).Trim()
    $qadamProcess = Get-CimInstance Win32_Process -Filter "ProcessId=$qadamProcessId" -ErrorAction SilentlyContinue
    $qadamServerPath = Join-Path $PSScriptRoot 'server.py'
    if ($qadamProcess -and $qadamProcess.CommandLine.Contains($qadamServerPath)) {
        Stop-Process -Id $qadamProcessId
    }
}
