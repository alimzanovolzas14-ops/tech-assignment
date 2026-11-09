param([switch]$NoBrowser)
$ErrorActionPreference = 'Stop'
$qadamRoot = $PSScriptRoot
$qadamUrl = 'http://127.0.0.1:8766'
function Show-QadamError([string]$message) {
    Add-Type -AssemblyName PresentationFramework
    [System.Windows.MessageBox]::Show($message, 'Qadam', 'OK', 'Error') | Out-Null
}
try {
    $qadamReady = $false
    try {
        $qadamHealth = Invoke-RestMethod -Uri "$qadamUrl/api/health" -TimeoutSec 2
        $qadamReady = $qadamHealth.app -eq 'qadam'
    } catch {}
    if (-not $qadamReady) {
        $qadamBundledPython = Join-Path $env:USERPROFILE '.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe'
        $qadamPython = $null
        $qadamPrefix = @()
        if (Test-Path -LiteralPath $qadamBundledPython) { $qadamPython = $qadamBundledPython }
        else {
            $qadamPyLauncher = Get-Command py.exe -ErrorAction SilentlyContinue
            if ($qadamPyLauncher) { $qadamPython = $qadamPyLauncher.Source; $qadamPrefix = @('-3') }
            else {
                $qadamPythonCommand = Get-Command python.exe -ErrorAction SilentlyContinue
                if ($qadamPythonCommand) { $qadamPython = $qadamPythonCommand.Source }
            }
        }
        if (-not $qadamPython) { throw 'Python 3.10 or newer is required. Install Python from python.org and run START_QADAM.cmd again.' }
        $qadamDataPath = Join-Path $qadamRoot 'data'
        New-Item -ItemType Directory -Path $qadamDataPath -Force | Out-Null
        $qadamServerPath = Join-Path $qadamRoot 'server.py'
        $qadamArguments = $qadamPrefix + @('"' + $qadamServerPath + '"')
        $qadamProcess = Start-Process -FilePath $qadamPython -ArgumentList $qadamArguments -WorkingDirectory $qadamRoot -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $qadamDataPath 'server.log') -RedirectStandardError (Join-Path $qadamDataPath 'server-error.log')
        $qadamProcess.Id | Set-Content -LiteralPath (Join-Path $qadamDataPath 'server.pid')
        for ($qadamAttempt=0; $qadamAttempt -lt 30; $qadamAttempt++) {
            Start-Sleep -Milliseconds 500
            try {
                $qadamHealth = Invoke-RestMethod -Uri "$qadamUrl/api/health" -TimeoutSec 1
                if ($qadamHealth.app -eq 'qadam') { $qadamReady=$true; break }
            } catch {}
            if ($qadamProcess.HasExited) { break }
        }
        if (-not $qadamReady) { throw 'Qadam could not start. Check data\server-error.log. Port 8766 may already be used by another application.' }
    }
    if (-not $NoBrowser) { Start-Process $qadamUrl }
} catch { Show-QadamError $_.Exception.Message }
