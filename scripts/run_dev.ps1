param(
    [int]$BackendPort = 8000,
    [string]$FrontendHost = "127.0.0.1",
    [string]$RemoteUser = "",
    [string]$RemoteHost = "",
    [string]$RemoteVenvActivate = "",
    [int]$AppSyncIntervalMs = 5000,
    [int]$SpectrumPollIntervalMs = 100,
    [int]$WaterfallPollIntervalMs = 100,
    [bool]$InstallDeps = $true,
    [bool]$InstallTools = $true,
    [bool]$FullBackendDeps = $false,
    [string]$BackendPythonPath = "",
    [string]$RadioCondaPythonPath = "C:\Users\Usuario\radioconda\python.exe",
    [object]$UseRealSdr = $false
)

$ErrorActionPreference = "Stop"

$RootDir = Resolve-Path (Join-Path $PSScriptRoot "..")
$BackendDir = Join-Path $RootDir "backend"
$FrontendDir = Join-Path $RootDir "frontend"
$VenvDir = Join-Path $BackendDir "venv"
$VenvPython = Join-Path $VenvDir "Scripts\python.exe"
$FilteredRequirements = Join-Path $BackendDir "requirements.dev-windows.txt"

function Write-Step {
    param([string]$Message)
    Write-Host ""
    Write-Host "==> $Message" -ForegroundColor Cyan
}

function Test-Command {
    param([string]$Name)
    return [bool](Get-Command $Name -ErrorAction SilentlyContinue)
}

function Convert-ToBool {
    param([object]$Value)

    if ($Value -is [bool]) {
        return $Value
    }

    $Text = "$Value".Trim().ToLowerInvariant()
    return $Text -in @("1", "true", "`$true", "yes", "y", "on")
}

function Get-CommandPath {
    param([string[]]$Names)

    foreach ($Name in $Names) {
        $Command = Get-Command $Name -ErrorAction SilentlyContinue
        if ($Command) {
            return $Command.Source
        }
    }

    return $null
}

function Test-WindowsAppsPython {
    param([string]$Path)
    return ($Path -like "*\WindowsApps\PythonSoftwareFoundation.Python*")
}

function Install-WithWinget {
    param(
        [string]$Id,
        [string]$Name
    )

    if (-not (Test-Command "winget")) {
        throw "No se encontro $Name y no esta disponible winget para instalarlo automaticamente."
    }

    Write-Step "Installing $Name with winget"
    Invoke-Native `
        -FilePath "winget" `
        -ArgumentList @("install", "--id", $Id, "--exact", "--accept-package-agreements", "--accept-source-agreements") `
        -ErrorMessage "No se pudo instalar $Name con winget."
}

function Invoke-Native {
    param(
        [string]$FilePath,
        [string[]]$ArgumentList,
        [string]$ErrorMessage
    )

    & $FilePath @ArgumentList
    if ($LASTEXITCODE -ne 0) {
        throw $ErrorMessage
    }
}

function Get-PythonVersion {
    param(
        [string]$FilePath,
        [string[]]$ArgumentList = @()
    )

    $Output = & $FilePath @($ArgumentList + @("-c", "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}')")) 2>$null
    if ($LASTEXITCODE -ne 0 -or -not $Output) {
        return $null
    }

    try {
        return [version]($Output | Select-Object -First 1)
    } catch {
        return $null
    }
}

function Test-Python310 {
    param(
        [string]$FilePath,
        [string[]]$ArgumentList = @()
    )

    $Version = Get-PythonVersion -FilePath $FilePath -ArgumentList $ArgumentList
    return ($Version -and $Version -ge [version]"3.10.0")
}

function Get-CompatiblePython {
    if ($BackendPythonPath) {
        if (-not (Test-Path $BackendPythonPath)) {
            throw "No se encontro BackendPythonPath: $BackendPythonPath"
        }
        if (-not (Test-Python310 -FilePath $BackendPythonPath)) {
            throw "BackendPythonPath debe ser Python 3.10+: $BackendPythonPath"
        }
        return @{ FilePath = $BackendPythonPath; Args = @() }
    }

    $Candidates = @()

    $CommonPythonPaths = @(
        (Join-Path $env:LOCALAPPDATA "Programs\Python\Python312\python.exe"),
        (Join-Path $env:LOCALAPPDATA "Programs\Python\Python311\python.exe"),
        (Join-Path $env:LOCALAPPDATA "Programs\Python\Python310\python.exe"),
        (Join-Path $env:ProgramFiles "Python312\python.exe"),
        (Join-Path $env:ProgramFiles "Python311\python.exe"),
        (Join-Path $env:ProgramFiles "Python310\python.exe")
    )

    if (${env:ProgramFiles(x86)}) {
        $CommonPythonPaths += @(
            (Join-Path ${env:ProgramFiles(x86)} "Python312\python.exe"),
            (Join-Path ${env:ProgramFiles(x86)} "Python311\python.exe"),
            (Join-Path ${env:ProgramFiles(x86)} "Python310\python.exe")
        )
    }

    foreach ($Path in $CommonPythonPaths) {
        if (Test-Path $Path) {
            $Candidates += @{ FilePath = $Path; Args = @() }
        }
    }

    if (Test-Command "py") {
        $Candidates += @{ FilePath = "py"; Args = @("-3.12") }
        $Candidates += @{ FilePath = "py"; Args = @("-3.11") }
        $Candidates += @{ FilePath = "py"; Args = @("-3.10") }
    }

    $PythonCommandPath = Get-CommandPath -Names @("python.exe", "python")
    if ($PythonCommandPath -and -not (Test-WindowsAppsPython -Path $PythonCommandPath)) {
        $Candidates += @{ FilePath = $PythonCommandPath; Args = @() }
    }

    foreach ($Candidate in $Candidates) {
        if (Test-Python310 -FilePath $Candidate.FilePath -ArgumentList $Candidate.Args) {
            return $Candidate
        }
    }

    if ($InstallTools) {
        Install-WithWinget -Id "Python.Python.3.12" -Name "Python 3.12"
        $CandidatesAfterInstall = @()

        foreach ($Path in $CommonPythonPaths) {
            if (Test-Path $Path) {
                $CandidatesAfterInstall += @{ FilePath = $Path; Args = @() }
            }
        }

        if (Test-Command "py") {
            $CandidatesAfterInstall += @{ FilePath = "py"; Args = @("-3.12") }
        }
        $PythonCommandPathAfterInstall = Get-CommandPath -Names @("python.exe", "python")
        if ($PythonCommandPathAfterInstall -and -not (Test-WindowsAppsPython -Path $PythonCommandPathAfterInstall)) {
            $CandidatesAfterInstall += @{ FilePath = $PythonCommandPathAfterInstall; Args = @() }
        }
        foreach ($Candidate in $CandidatesAfterInstall) {
            if (Test-Python310 -FilePath $Candidate.FilePath -ArgumentList $Candidate.Args) {
                return $Candidate
            }
        }
    }

    throw "No se encontro Python 3.10+. Instala Python 3.10 o superior, cierra PowerShell y vuelve a ejecutar el script."
}

function New-FilteredRequirements {
    $ExcludedPackages = @("gnuradio", "uhd", "pyrtlsdr")
    $Lines = Get-Content (Join-Path $BackendDir "requirements.txt") | Where-Object {
        $Line = $_.Trim()
        if ($Line -eq "" -or $Line.StartsWith("#")) {
            return $true
        }

        foreach ($Package in $ExcludedPackages) {
            if ($Line -match "(?i)^$Package([<>=!~ ]|$)") {
                return $false
            }
        }

        return $true
    }

    $Lines | Set-Content -Path $FilteredRequirements -Encoding ASCII
    return $FilteredRequirements
}

function Ensure-Tools {
    Write-Step "Checking tools"

    $script:PythonCommand = Get-CompatiblePython

    if (-not (Test-Command "node")) {
        if ($InstallTools) {
            Install-WithWinget -Id "OpenJS.NodeJS.LTS" -Name "Node.js"
        } else {
            throw "Node.js no encontrado. Instala Node.js 18+."
        }
    }

    if (-not (Test-Command "npm")) {
        throw "npm no encontrado. Cierra y abre PowerShell despues de instalar Node.js, y vuelve a ejecutar este script."
    }
}

Ensure-Tools

Write-Step "Preparing backend"
$ExistingVenvVersion = $null
if (Test-Path $VenvPython) {
    $ExistingVenvVersion = Get-PythonVersion -FilePath $VenvPython
}

if ((Test-Path $VenvPython) -and (-not $ExistingVenvVersion -or $ExistingVenvVersion -lt [version]"3.10.0")) {
    $VersionLabel = if ($ExistingVenvVersion) { "$ExistingVenvVersion" } else { "invalido o Microsoft Store/WindowsApps" }
    Write-Host "El entorno virtual existente usa Python $VersionLabel. Se va a recrear: $VenvDir" -ForegroundColor Yellow
    Remove-Item -LiteralPath $VenvDir -Recurse -Force
}

if (-not (Test-Path $VenvDir)) {
    Invoke-Native `
        -FilePath $PythonCommand.FilePath `
        -ArgumentList @($PythonCommand.Args + @("-m", "venv", $VenvDir)) `
        -ErrorMessage "No se pudo crear el entorno virtual del backend."
}

if (-not (Test-Path $VenvPython)) {
    throw "No se encontro Python dentro del entorno virtual: $VenvPython"
}

if ($InstallDeps) {
    Invoke-Native `
        -FilePath $VenvPython `
        -ArgumentList @("-m", "pip", "install", "--upgrade", "pip", "wheel", "setuptools<82") `
        -ErrorMessage "No se pudo actualizar pip/wheel/setuptools<82."

    if ($FullBackendDeps) {
        $RequirementsPath = Join-Path $BackendDir "requirements.txt"
    } else {
        $RequirementsPath = New-FilteredRequirements
        Write-Host "Modo desarrollo Windows: se omiten gnuradio, uhd y pyrtlsdr. Usa -FullBackendDeps `$true si tienes SDR/hardware configurado." -ForegroundColor Yellow
    }

    Invoke-Native `
        -FilePath $VenvPython `
        -ArgumentList @("-m", "pip", "install", "-r", $RequirementsPath) `
        -ErrorMessage "No se pudieron instalar las dependencias del backend."
}

Write-Step "Preparing frontend"
if ($InstallDeps) {
    Push-Location $FrontendDir
    try {
        Invoke-Native -FilePath "npm" -ArgumentList @("install") -ErrorMessage "No se pudieron instalar las dependencias del frontend."
    } finally {
        Pop-Location
    }
}

Write-Step "Starting backend on http://localhost:$BackendPort"
if ($RadioCondaPythonPath) {
    $env:RADIOCONDA_PYTHON = $RadioCondaPythonPath
}
$UseRealSdrEnabled = Convert-ToBool $UseRealSdr
if ($UseRealSdrEnabled) {
    $env:USE_REAL_SDR = "1"
} else {
    $env:USE_REAL_SDR = "0"
}

$BackendProcess = Start-Process `
    -FilePath $VenvPython `
    -ArgumentList @("-m", "uvicorn", "app.main:app", "--reload", "--host", "0.0.0.0", "--port", "$BackendPort") `
    -WorkingDirectory $BackendDir `
    -NoNewWindow `
    -PassThru

Write-Step "Starting frontend on http://localhost:5173"
$env:VITE_APP_SYNC_INTERVAL_MS = "$AppSyncIntervalMs"
$env:VITE_SPECTRUM_POLL_INTERVAL_MS = "$SpectrumPollIntervalMs"
$env:VITE_WATERFALL_POLL_INTERVAL_MS = "$WaterfallPollIntervalMs"
$env:VITE_REMOTE_USER = "$RemoteUser"
$env:VITE_REMOTE_HOST = "$RemoteHost"
$env:VITE_REMOTE_VENV_ACTIVATE = "$RemoteVenvActivate"
$env:VITE_RADIOCONDA_PYTHON = "$RadioCondaPythonPath"
$NpmCommand = Get-CommandPath -Names @("npm.cmd", "npm.exe")
if (-not $NpmCommand) {
    throw "No se encontro npm.cmd. Cierra y abre PowerShell despues de instalar Node.js, y vuelve a ejecutar el script."
}

$FrontendProcess = Start-Process `
    -FilePath $NpmCommand `
    -ArgumentList @("run", "dev", "--", "--host", $FrontendHost) `
    -WorkingDirectory $FrontendDir `
    -NoNewWindow `
    -PassThru

Write-Host ""
Write-Host "Backend API: http://localhost:$BackendPort"
Write-Host "API docs:    http://localhost:$BackendPort/docs"
Write-Host "Frontend:    http://localhost:5173"
if ($RemoteUser -or $RemoteHost) {
    Write-Host "Remote train target: $RemoteUser@$RemoteHost"
}
Write-Host "App sync interval:       $AppSyncIntervalMs ms"
Write-Host "Spectrum poll interval:  $SpectrumPollIntervalMs ms"
Write-Host "Waterfall poll interval: $WaterfallPollIntervalMs ms"
Write-Host ""
Write-Host "Pulsa Ctrl+C para parar ambos servicios."

try {
    while (-not $BackendProcess.HasExited -and -not $FrontendProcess.HasExited) {
        Start-Sleep -Seconds 1
        $BackendProcess.Refresh()
        $FrontendProcess.Refresh()
    }
} finally {
    Write-Step "Stopping services"
    if ($BackendProcess -and -not $BackendProcess.HasExited) {
        Stop-Process -Id $BackendProcess.Id -Force
    }
    if ($FrontendProcess -and -not $FrontendProcess.HasExited) {
        Stop-Process -Id $FrontendProcess.Id -Force
    }
}
