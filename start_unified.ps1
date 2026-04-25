param(
    [string]$RadioCondaPythonPath = "C:\Users\Usuario\radioconda\python.exe",
    [string]$RemoteUser = "assouyat",
    [string]$RemoteHost = "192.168.193.49",
    [int]$BackendPort = 8000,
    [string]$FrontendHost = "127.0.0.1",
    [int]$AppSyncIntervalMs = 5000,
    [int]$SpectrumPollIntervalMs = 100,
    [int]$WaterfallPollIntervalMs = 100
)

$ErrorActionPreference = "Stop"
$RootDir = Resolve-Path $PSScriptRoot
$Runner = Join-Path $RootDir "scripts\run_dev.ps1"

if (-not (Test-Path $Runner)) {
    throw "No se encontro scripts\run_dev.ps1"
}

powershell -ExecutionPolicy Bypass -File $Runner `
    -UseRealSdr 1 `
    -RadioCondaPythonPath $RadioCondaPythonPath `
    -RemoteUser $RemoteUser `
    -RemoteHost $RemoteHost `
    -BackendPort $BackendPort `
    -FrontendHost $FrontendHost `
    -AppSyncIntervalMs $AppSyncIntervalMs `
    -SpectrumPollIntervalMs $SpectrumPollIntervalMs `
    -WaterfallPollIntervalMs $WaterfallPollIntervalMs
