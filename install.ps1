# install.ps1 - Hermes Agent one-shot fix entry (Windows PowerShell)
#
# Usage (PowerShell 5.1+ / PowerShell 7):
#   iex "& { $(irm https://raw.githubusercontent.com/eyan-ai/hermes-fix-scripts/main/install.ps1) } fix-message-loss"
#
# Or with an explicit Hermes dir:
#   iex "& { $(irm https://raw.githubusercontent.com/eyan-ai/hermes-fix-scripts/main/install.ps1) } fix-message-loss C:\Users\you\.hermes\hermes-agent"
#
# All scripts are idempotent: safe to re-run, auto-backup, rollback on syntax error.
# NOTE: English-only output on purpose - PowerShell 5.1 parses .ps1 without BOM
# as ANSI, so non-ASCII would garble. Chinese instructions live in README.md.

param(
    [string]$ScriptName = "",
    [string]$HermesDir = ""
)

$RepoRaw = "https://raw.githubusercontent.com/eyan-ai/hermes-fix-scripts/main"

function Get-TargetFile {
    param([string]$name)
    switch ($name) {
        "fix-message-loss" { return "fix-hermes-desktop-message-loss.py" }
        default { return "" }
    }
}

function Show-Usage {
    Write-Host ""
    Write-Host "Usage: iex `"& { `$(irm $RepoRaw/install.ps1) `} <script-name> [hermes-dir]`""
    Write-Host ""
    Write-Host "Available scripts:"
    Write-Host "  fix-message-loss  ->  fix desktop message loss after sleep/shutdown"
    Write-Host ""
    Write-Host "Examples:"
    Write-Host "  iex `"& { `$(irm $RepoRaw/install.ps1) `} fix-message-loss`""
    Write-Host ""
    throw "No valid script name given"
}

$filename = Get-TargetFile $ScriptName
if (-not $filename) { Show-Usage }

Write-Host "Downloading $ScriptName ($filename) ..."
$tmpDir = Join-Path ([System.IO.Path]::GetTempPath()) ("hermes-fix-" + [guid]::NewGuid().ToString("N"))
New-Item -ItemType Directory -Path $tmpDir -Force | Out-Null
$scriptPath = Join-Path $tmpDir $filename

try {
    Invoke-WebRequest -Uri "$RepoRaw/$filename" -OutFile $scriptPath -UseBasicParsing
}
catch {
    Write-Host "Download failed: $RepoRaw/$filename"
    Remove-Item -Recurse -Force $tmpDir -ErrorAction SilentlyContinue
    throw
}

Write-Host "Downloaded. Running ..."
Write-Host ""

# Windows may have python / py (launcher) / python3
$py = Get-Command python -ErrorAction SilentlyContinue
if (-not $py) { $py = Get-Command py -ErrorAction SilentlyContinue }
if (-not $py) { $py = Get-Command python3 -ErrorAction SilentlyContinue }
if (-not $py) {
    Remove-Item -Recurse -Force $tmpDir -ErrorAction SilentlyContinue
    throw "python not found. Install Python 3 first: https://www.python.org/downloads/"
}

if ($HermesDir) {
    & $py.Source $scriptPath $HermesDir
}
else {
    & $py.Source $scriptPath
}

Remove-Item -Recurse -Force $tmpDir -ErrorAction SilentlyContinue
Write-Host ""
Write-Host "Done. Restart the Hermes desktop app (fully quit, then reopen) to apply the fix."
