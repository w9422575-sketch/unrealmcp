<#
.SYNOPSIS
    Demarre l'agent de developpement local : Copilot CLI + Ollama + gpt-oss:20b + MCP + Unreal 5.8.

.DESCRIPTION
    Verifie chaque couche de l'infrastructure, corrige ce qui peut l'etre
    automatiquement, puis lance Copilot CLI en mode BYOK sur le modele local.
    Aucune erreur n'est masquee : un [FAIL] bloquant interrompt le demarrage.

.PARAMETER Check
    Ne lance pas Copilot : effectue uniquement les verifications.

.PARAMETER Prompt
    Execute un prompt en mode non interactif puis rend la main.

.PARAMETER Context
    Taille du contexte Ollama. "auto" (defaut) vaut 32768 : c'est le minimum
    viable pour les definitions d'outils MCP, et le maximum tenable en VRAM.

.PARAMETER Force
    Redemarre Ollama meme si la configuration courante semble correcte.

.EXAMPLE
    .\start-agent.ps1
    .\start-agent.ps1 -Check
    .\start-agent.ps1 -Prompt "Analyse le projet et liste les Blueprints du joueur."
#>

[CmdletBinding()]
param(
    [switch] $Check,
    [string] $Prompt,
    [string] $Context = "auto",
    [switch] $Force
)

$ErrorActionPreference = "Stop"
$ProjectRoot = $PSScriptRoot
$AgentDir    = Join-Path $ProjectRoot "agent"
$ConfigDir   = Join-Path $AgentDir "config"
$LogDir      = Join-Path $AgentDir "logs"
$McpConfig   = Join-Path $LogDir "mcp-config.json"
$EnvFile     = Join-Path $ConfigDir "agent.env"
$StateFile   = Join-Path $LogDir "ollama-state.json"
$OllamaApi   = "http://127.0.0.1:11434"
$Model       = "gpt-oss:20b"

New-Item -ItemType Directory -Force -Path $LogDir | Out-Null

$script:Failed = $false

function Write-Status {
    param([string] $Tag, [string] $Message, [string] $Detail = "")
    $color = switch ($Tag) { "OK" { "Green" } "WARN" { "Yellow" } default { "Red" } }
    Write-Host ("[{0}] " -f $Tag) -ForegroundColor $color -NoNewline
    Write-Host $Message
    if ($Detail) { Write-Host "       $Detail" -ForegroundColor DarkGray }
    if ($Tag -eq "FAIL") { $script:Failed = $true }
}

function Import-AgentEnv {
    if (-not (Test-Path $EnvFile)) { return @{} }
    $map = @{}
    foreach ($line in Get-Content $EnvFile) {
        $trimmed = $line.Trim()
        if (-not $trimmed -or $trimmed.StartsWith("#")) { continue }
        $idx = $trimmed.IndexOf("=")
        if ($idx -lt 1) { continue }
        $map[$trimmed.Substring(0, $idx).Trim()] = $trimmed.Substring($idx + 1).Trim()
    }
    return $map
}

function Test-OllamaApi {
    try { return (Invoke-RestMethod "$OllamaApi/api/version" -TimeoutSec 5).version }
    catch { return $null }
}

function Write-McpConfig {
    $servers = [ordered]@{
        "agent-test" = [ordered]@{
            type = "local"
            command = "python"
            args = @((Join-Path $AgentDir "mcp\test_server.py"))
            tools = @("*")
            timeout = 30000
        }
        "workspace" = [ordered]@{
            type = "local"
            command = "python"
            args = @((Join-Path $AgentDir "mcp\workspace_server.py"))
            env = [ordered]@{ AGENT_WORKSPACE = $ProjectRoot }
            tools = @("*")
            timeout = 180000
        }
        "unreal" = [ordered]@{
            type = "local"
            command = "python"
            args = @((Join-Path $AgentDir "mcp\unreal_server.py"))
            env = [ordered]@{
                AGENT_WORKSPACE = $ProjectRoot
                UNREAL_MCP_URL = "http://127.0.0.1:8000/mcp"
            }
            tools = @("*")
            timeout = 1800000
        }
        "unreal-editor" = [ordered]@{
            type = "http"
            url = "http://127.0.0.1:8000/mcp"
            tools = @("*")
            timeout = 120000
        }
    }
    @{ mcpServers = $servers } |
        ConvertTo-Json -Depth 10 |
        Set-Content $McpConfig -Encoding UTF8
}

# ---------------------------------------------------------------------------
Write-Host ""
Write-Host "  Agent local  -  Copilot CLI + Ollama + gpt-oss:20b + MCP + Unreal 5.8" -ForegroundColor Cyan
Write-Host "  =====================================================================" -ForegroundColor Cyan
Write-Host ""

$overrides = Import-AgentEnv
if ($overrides.Count) { Write-Status "OK" "agent.env charge" "$($overrides.Count) variable(s) personnalisee(s)" }

# --- 1. Copilot CLI --------------------------------------------------------
$copilot = Get-Command copilot -ErrorAction SilentlyContinue
if ($copilot) {
    $version = (& copilot --version 2>&1 | Select-Object -First 1)
    Write-Status "OK" "Copilot CLI" $version
} else {
    Write-Status "FAIL" "Copilot CLI introuvable" "Installez-le : winget install GitHub.CopilotCLI"
}

# --- 2. Python + SDK MCP ---------------------------------------------------
try {
    $pyVersion = (& python --version 2>&1)
    & python -c "import mcp" 2>&1 | Out-Null
    if ($LASTEXITCODE -eq 0) { Write-Status "OK" "Python + SDK MCP" $pyVersion }
    else { Write-Status "FAIL" "SDK MCP absent" "Installez-le : python -m pip install mcp" }
} catch {
    Write-Status "FAIL" "Python introuvable" $_.Exception.Message
}

# --- 3. Projet Unreal ------------------------------------------------------
$uproject = Get-ChildItem $ProjectRoot -Filter "*.uproject" | Select-Object -First 1
if ($uproject) {
    $data = Get-Content $uproject.FullName -Raw | ConvertFrom-Json
    $engineVersion = $data.EngineAssociation
    $engineRoot = "C:\Program Files\Epic Games\UE_$engineVersion"
    if (Test-Path $engineRoot) {
        $mcpPlugin = $data.Plugins | Where-Object { $_.Name -eq "ModelContextProtocol" -and $_.Enabled }
        $pluginNote = if ($mcpPlugin) { "plugin MCP Epic active" } else { "plugin MCP Epic NON active" }
        Write-Status "OK" "Projet Unreal : $($uproject.BaseName) (UE $engineVersion)" "$engineRoot - $pluginNote"
    } else {
        Write-Status "WARN" "Projet Unreal : $($uproject.BaseName)" "Moteur UE $engineVersion introuvable dans $engineRoot"
    }
} else {
    Write-Status "WARN" "Aucun projet .uproject dans $ProjectRoot" "Les outils Unreal seront inoperants."
}

# --- 4. Choix du contexte (optimisation phase 3) ---------------------------
# Le contexte ne peut PAS descendre sous ~24576 : les definitions statiques des
# outils (serveurs MCP + outils integres de Copilot CLI) saturent alors le
# budget avant le premier message. Mesure : 16384 -> refus de Copilot CLI
# ("Static system messages and tool definitions exceed the model's usable
# context budget"), 32768 -> fonctionne. On garde donc 32768 meme editeur
# ouvert ; le modele deborde simplement davantage sur le CPU (plus lent).
$ueRunning = [bool](Get-Process UnrealEditor -ErrorAction SilentlyContinue)
if ($Context -eq "auto") {
    $targetContext = 32768
} else {
    $targetContext = [int] $Context
}
$contextReason = if ($ueRunning) { "Unreal Editor ouvert : plus de debordement CPU, generation plus lente" }
                 else { "Unreal Editor ferme : placement GPU optimal (RTX 3060 12 Go)" }
Write-Status "OK" "Contexte Ollama cible : $targetContext tokens" $contextReason

# --- 5. Ollama -------------------------------------------------------------
$ollamaExe = Get-Command ollama -ErrorAction SilentlyContinue
if (-not $ollamaExe) {
    Write-Status "FAIL" "Ollama introuvable" "Installez-le : winget install Ollama.Ollama"
} else {
    $ollamaEnv = @{
        OLLAMA_CONTEXT_LENGTH    = "$targetContext"
        OLLAMA_FLASH_ATTENTION   = "1"
        OLLAMA_KV_CACHE_TYPE     = "q8_0"
        OLLAMA_MAX_LOADED_MODELS = "1"
        OLLAMA_NUM_PARALLEL      = "1"
        OLLAMA_KEEP_ALIVE        = "30m"
    }
    foreach ($key in @($ollamaEnv.Keys)) {
        if ($overrides.ContainsKey($key) -and $Context -eq "auto" -and $key -ne "OLLAMA_CONTEXT_LENGTH") {
            $ollamaEnv[$key] = $overrides[$key]
        }
    }

    $previous = if (Test-Path $StateFile) { Get-Content $StateFile -Raw | ConvertFrom-Json } else { $null }
    $running  = Test-OllamaApi
    $needsRestart = $Force -or (-not $running) -or (-not $previous) -or ([int]$previous.context -ne $targetContext)

    if ($needsRestart) {
        if ($running) {
            Write-Host "       Redemarrage d'Ollama (contexte $targetContext)..." -ForegroundColor DarkGray
            foreach ($proc in Get-Process ollama, "ollama app" -ErrorAction SilentlyContinue) {
                Stop-Process -Id $proc.Id -Force -ErrorAction SilentlyContinue
            }
            Start-Sleep -Seconds 5
        }
        # Les variables doivent etre presentes dans CE processus : le serveur
        # Ollama herite de l'environnement de son lanceur, pas du registre.
        foreach ($entry in $ollamaEnv.GetEnumerator()) {
            Set-Item -Path "Env:$($entry.Key)" -Value $entry.Value
            [Environment]::SetEnvironmentVariable($entry.Key, $entry.Value, "User")
        }
        $ollamaApp = Join-Path $env:LOCALAPPDATA "Programs\Ollama\ollama app.exe"
        if (Test-Path $ollamaApp) { Start-Process $ollamaApp } else { Start-Process "ollama" -ArgumentList "serve" -WindowStyle Hidden }

        $deadline = (Get-Date).AddSeconds(60)
        do { Start-Sleep -Seconds 2; $running = Test-OllamaApi } while (-not $running -and (Get-Date) -lt $deadline)
    }

    if ($running) {
        Write-Status "OK" "Ollama $running" "$OllamaApi  |  contexte $targetContext, flash-attn on, KV cache q8_0"
        @{ context = $targetContext; startedAt = (Get-Date).ToString("o") } |
            ConvertTo-Json | Set-Content $StateFile -Encoding UTF8
    } else {
        Write-Status "FAIL" "Ollama ne repond pas sur $OllamaApi" "Consultez $env:LOCALAPPDATA\Ollama\server.log"
    }

    # --- 6. Modele ---------------------------------------------------------
    if ($running) {
        $tags = (Invoke-RestMethod "$OllamaApi/api/tags" -TimeoutSec 10).models.name
        if ($tags -contains $Model) {
            $size = (Invoke-RestMethod "$OllamaApi/api/tags" -TimeoutSec 10).models |
                    Where-Object { $_.name -eq $Model } | Select-Object -First 1
            Write-Status "OK" "Modele $Model" ("{0:N1} Go sur disque" -f ($size.size / 1GB))
        } else {
            Write-Status "FAIL" "Modele $Model absent" "Telechargez-le : ollama pull $Model"
        }
    }
}

# --- 7. Serveurs MCP -------------------------------------------------------
Write-McpConfig
if (Test-Path $McpConfig) {
    $servers = (Get-Content $McpConfig -Raw | ConvertFrom-Json).mcpServers
    $names = $servers.PSObject.Properties.Name
    $missing = @()
    foreach ($name in $names) {
        $entry = $servers.$name
        if ($entry.type -eq "local") {
            $scriptPath = $entry.args | Select-Object -Last 1
            if (-not (Test-Path $scriptPath)) { $missing += "$name -> $scriptPath" }
        }
    }
    if ($missing.Count) { Write-Status "FAIL" "Serveurs MCP : fichier(s) manquant(s)" ($missing -join "; ") }
    else { Write-Status "OK" "Serveurs MCP configures" ($names -join ", ") }
} else {
    Write-Status "FAIL" "Configuration MCP introuvable" $McpConfig
}

# --- 8. Serveur MCP officiel de l'editeur Unreal ---------------------------
$editorUrl = if ($overrides.ContainsKey("UNREAL_MCP_URL")) { $overrides["UNREAL_MCP_URL"] } else { "http://127.0.0.1:8000/mcp" }
try {
    Invoke-WebRequest -Uri $editorUrl -Method Post -TimeoutSec 3 `
        -Body '{"jsonrpc":"2.0","id":1,"method":"ping"}' `
        -ContentType "application/json" -ErrorAction Stop | Out-Null
    Write-Status "OK" "Unreal MCP (editeur)" "$editorUrl - outils de scene vivante disponibles"
} catch {
    # Une reponse HTTP, meme en erreur, prouve que le serveur ecoute.
    # Compatible PowerShell 5.1 et 7 : on inspecte l'exception sans typer.
    $response = $_.Exception.PSObject.Properties['Response']
    if ($response -and $response.Value) {
        Write-Status "OK" "Unreal MCP (editeur)" "$editorUrl - serveur present"
    } else {
        Write-Status "WARN" "Unreal MCP (editeur) injoignable" "Ouvrez le projet dans Unreal Editor 5.8 pour les outils de scene vivante. Les outils hors-ligne restent disponibles."
    }
}

# ---------------------------------------------------------------------------
Write-Host ""
if ($script:Failed) {
    Write-Host "  Demarrage interrompu : corrigez les [FAIL] ci-dessus." -ForegroundColor Red
    Write-Host ""
    exit 1
}

if ($Check) {
    Write-Host "  Toutes les verifications sont passees." -ForegroundColor Green
    Write-Host ""
    exit 0
}

# --- 9. Lancement de Copilot CLI en mode BYOK ------------------------------
# Marge de securite : le contexte doit accueillir le prompt ET la reponse.
$maxPromptTokens = [int] ($targetContext * 0.80)
$maxOutputTokens = [Math]::Min(4096, [int] ($targetContext * 0.15))

$env:COPILOT_PROVIDER_BASE_URL           = if ($overrides.ContainsKey("COPILOT_PROVIDER_BASE_URL")) { $overrides["COPILOT_PROVIDER_BASE_URL"] } else { "http://localhost:11434/v1" }
$env:COPILOT_PROVIDER_TYPE               = "openai"
$env:COPILOT_PROVIDER_WIRE_API           = "completions"
$env:COPILOT_MODEL                       = if ($overrides.ContainsKey("COPILOT_MODEL")) { $overrides["COPILOT_MODEL"] } else { $Model }
$env:COPILOT_PROVIDER_MAX_PROMPT_TOKENS  = "$maxPromptTokens"
$env:COPILOT_PROVIDER_MAX_OUTPUT_TOKENS  = "$maxOutputTokens"
if ($overrides.ContainsKey("COPILOT_PROVIDER_API_KEY") -and $overrides["COPILOT_PROVIDER_API_KEY"]) {
    $env:COPILOT_PROVIDER_API_KEY = $overrides["COPILOT_PROVIDER_API_KEY"]
}
$env:AGENT_WORKSPACE = $ProjectRoot

Write-Host "  Lancement de Copilot CLI" -ForegroundColor Cyan
Write-Host "     provider : $env:COPILOT_PROVIDER_BASE_URL (type openai, wire api completions)" -ForegroundColor DarkGray
Write-Host "     modele   : $env:COPILOT_MODEL" -ForegroundColor DarkGray
Write-Host "     tokens   : prompt max $maxPromptTokens / sortie max $maxOutputTokens" -ForegroundColor DarkGray
Write-Host "     mcp      : $McpConfig" -ForegroundColor DarkGray
Write-Host ""

$copilotArgs = @(
    "--additional-mcp-config", "@$McpConfig"
    "--add-dir", $ProjectRoot
    # Budget de contexte : gpt-oss:20b plafonne a 32768 tokens sur cette machine.
    # Les outils integres de Copilot CLI (serveur GitHub MCP, recherche web,
    # sous-agents, memoire...) ajoutent plusieurs milliers de tokens de
    # definitions statiques et font depasser le budget avant meme le premier
    # message ("Static system messages and tool definitions exceed the model's
    # usable context budget"). On desactive tout ce qui est inutile hors-ligne.
    "--disable-builtin-mcps"
    "--no-ask-user"
    "--excluded-tools", "task,session_store_sql,sql"
    "--banner"
)
if ($Prompt) { $copilotArgs += @("-p", $Prompt, "--allow-all-tools") }

& copilot @copilotArgs
exit $LASTEXITCODE
