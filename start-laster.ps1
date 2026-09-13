<#
.SYNOPSIS
    Démarre l'interface locale Laster et ouvre http://127.0.0.1:4317/laster.

.PARAMETER Port
    Port HTTP local utilisé par Laster.

.PARAMETER Rebuild
    Force une nouvelle compilation de l'interface React.

.PARAMETER NoBrowser
    Démarre le serveur sans ouvrir le navigateur.

.PARAMETER Mobile
    Rend Laster accessible à un iPhone sur le même réseau local avec un jeton privé.
#>

[CmdletBinding()]
param(
    [int] $Port = 4317,
    [switch] $Rebuild,
    [switch] $NoBrowser,
    [switch] $Mobile
)

$ErrorActionPreference = "Stop"
$ProjectRoot = $PSScriptRoot
$AppDir = Join-Path $ProjectRoot "laster"
$DistIndex = Join-Path $AppDir "dist\index.html"
$ServerScript = Join-Path $AppDir "backend\server.py"
$DataDir = Join-Path $AppDir "data"
$HealthUrl = "http://127.0.0.1:$Port/api/health"
$LocalAppUrl = "http://127.0.0.1:$Port/laster"
$AppUrl = $LocalAppUrl
$OllamaUrl = "http://127.0.0.1:11434"

function Write-LasterStatus {
    param([string] $Tag, [string] $Message)
    $color = if ($Tag -eq "OK") { "Green" } elseif ($Tag -eq "WARN") { "Yellow" } else { "Cyan" }
    Write-Host ("[{0}] " -f $Tag) -ForegroundColor $color -NoNewline
    Write-Host $Message
}

function Test-Endpoint {
    param([string] $Url, [int] $TimeoutSeconds = 2)
    try {
        Invoke-RestMethod -Uri $Url -TimeoutSec $TimeoutSeconds -ErrorAction Stop | Out-Null
        return $true
    } catch {
        return $false
    }
}

Write-Host ""
Write-Host "  LASTER  /  Local Development Agent" -ForegroundColor Green
Write-Host "  ===================================" -ForegroundColor DarkGreen
Write-Host ""

if (Test-Endpoint $HealthUrl) {
    Write-LasterStatus "OK" "Laster est déjà actif sur $LocalAppUrl"
    if ($Mobile) {
        Write-LasterStatus "WARN" "Redémarre Laster avec -Mobile pour autoriser l’accès iPhone."
    }
    if (-not $NoBrowser) { Start-Process $AppUrl }
    return
}

$python = Get-Command python -ErrorAction SilentlyContinue
if (-not $python) {
    throw "Python est introuvable. Installez Python 3.10 ou supérieur."
}
& $python.Source -c "import mcp" 2>$null
if ($LASTEXITCODE -ne 0) {
    throw "Le SDK MCP Python est absent. Exécutez: python -m pip install mcp"
}
Write-LasterStatus "OK" "Python et SDK MCP"

$ollama = Get-Command ollama -ErrorAction SilentlyContinue
if (-not $ollama) {
    throw "Ollama est introuvable. Installez-le avec: winget install Ollama.Ollama"
}

if (-not (Test-Endpoint "$OllamaUrl/api/version")) {
    $env:OLLAMA_CONTEXT_LENGTH = "32768"
    $env:OLLAMA_FLASH_ATTENTION = "1"
    $env:OLLAMA_KV_CACHE_TYPE = "q8_0"
    $env:OLLAMA_MAX_LOADED_MODELS = "1"
    $env:OLLAMA_NUM_PARALLEL = "1"
    $env:OLLAMA_KEEP_ALIVE = "30m"
    $ollamaApp = Join-Path $env:LOCALAPPDATA "Programs\Ollama\ollama app.exe"
    if (Test-Path $ollamaApp) {
        Start-Process $ollamaApp
    } else {
        Start-Process $ollama.Source -ArgumentList "serve" -WindowStyle Hidden
    }
    $deadline = (Get-Date).AddSeconds(45)
    while (-not (Test-Endpoint "$OllamaUrl/api/version") -and (Get-Date) -lt $deadline) {
        [System.Threading.Thread]::Sleep(500)
    }
}

if (-not (Test-Endpoint "$OllamaUrl/api/version")) {
    throw "Ollama ne répond pas sur $OllamaUrl."
}
$models = (Invoke-RestMethod "$OllamaUrl/api/tags" -TimeoutSec 10).models.name
if ($models -notcontains "gpt-oss:20b") {
    throw "Le modèle gpt-oss:20b est absent. Exécutez: ollama pull gpt-oss:20b"
}
Write-LasterStatus "OK" "Ollama et gpt-oss:20b"

if ($Rebuild -or -not (Test-Path $DistIndex)) {
    $npm = Get-Command npm -ErrorAction SilentlyContinue
    if (-not $npm) {
        throw "Node.js/npm est requis pour compiler l'interface."
    }
    if (-not (Test-Path (Join-Path $AppDir "node_modules"))) {
        & $npm.Source --prefix $AppDir install
        if ($LASTEXITCODE -ne 0) { throw "npm install a échoué." }
    }
    & $npm.Source --prefix $AppDir run build
    if ($LASTEXITCODE -ne 0) { throw "La compilation de Laster a échoué." }
    Write-LasterStatus "OK" "Interface compilée"
} else {
    Write-LasterStatus "OK" "Interface compilée disponible"
}

New-Item -ItemType Directory -Force -Path $DataDir | Out-Null
$env:LASTER_PORT = "$Port"
$env:LASTER_DEFAULT_PROJECT = $ProjectRoot
if ($Mobile) {
    $lanIp = [System.Net.Dns]::GetHostAddresses([System.Net.Dns]::GetHostName()) |
        Where-Object {
            $_.AddressFamily -eq [System.Net.Sockets.AddressFamily]::InterNetwork -and
            -not [System.Net.IPAddress]::IsLoopback($_)
        } |
        Select-Object -First 1
    if (-not $lanIp) {
        throw "Aucune adresse IPv4 locale n’a été trouvée pour l’accès iPhone."
    }
    $accessToken = [guid]::NewGuid().ToString("N") + [guid]::NewGuid().ToString("N")
    $env:LASTER_HOST = "0.0.0.0"
    $env:LASTER_ACCESS_TOKEN = $accessToken
    $AppUrl = "http://$($lanIp.IPAddressToString):$Port/laster?token=$accessToken"
} else {
    $env:LASTER_HOST = "127.0.0.1"
    Remove-Item Env:LASTER_ACCESS_TOKEN -ErrorAction SilentlyContinue
}
$stdoutLog = Join-Path $DataDir "server.out.log"
$stderrLog = Join-Path $DataDir "server.err.log"
$process = Start-Process `
    -FilePath $python.Source `
    -ArgumentList "`"$ServerScript`"" `
    -WorkingDirectory $ProjectRoot `
    -WindowStyle Hidden `
    -RedirectStandardOutput $stdoutLog `
    -RedirectStandardError $stderrLog `
    -PassThru
$process.Id | Set-Content (Join-Path $DataDir "server.pid") -Encoding ASCII

$deadline = (Get-Date).AddSeconds(20)
while (-not (Test-Endpoint $HealthUrl) -and (Get-Date) -lt $deadline -and -not $process.HasExited) {
    [System.Threading.Thread]::Sleep(250)
}
if (-not (Test-Endpoint $HealthUrl)) {
    $detail = if (Test-Path $stderrLog) { Get-Content $stderrLog -Raw } else { "Aucun journal disponible." }
    throw "Laster n'a pas démarré: $detail"
}

Write-LasterStatus "OK" "Serveur local démarré (PID $($process.Id))"
Write-Host "       $AppUrl" -ForegroundColor DarkGray
if ($Mobile) {
    Write-LasterStatus "WARN" "Garde cette URL privée : elle permet de piloter l’agent MCP."
}
if (-not $NoBrowser) {
    Start-Process $AppUrl
    Write-LasterStatus "OK" "Interface ouverte dans le navigateur"
}
