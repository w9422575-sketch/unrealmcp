"""
Serveur MCP "unreal" - PHASES 8 et 9
=====================================
Outils Unreal Engine 5.8 utilisables SANS editeur ouvert (mode hors-ligne) :
inspection du projet, lecture des logs, compilation des Blueprints,
extraction des erreurs, execution de scripts Python de l'editeur.

IMPORTANT - repartition des roles
---------------------------------
Les operations sur une scene VIVANTE (lister/selectionner/spawner des acteurs,
executer une commande console, editer visuellement un Blueprint) ne sont PAS
implementees ici : elles necessitent un editeur en cours d'execution.
Elles sont fournies par le serveur MCP OFFICIEL d'Epic (plugin experimental
"ModelContextProtocol" livre avec UE 5.8), qui expose son propre serveur MCP
sur http://127.0.0.1:8000/mcp et que Copilot CLI consomme directement.

Ce fichier ne contient donc aucun outil factice : chaque outil declare ici
effectue reellement l'operation annoncee. L'outil unreal_mcp_status() permet
de savoir si le serveur officiel de l'editeur est joignable.
"""

from __future__ import annotations

import json
import logging
import os
import re
import subprocess
import tempfile
import time
import urllib.error
import urllib.request
import winreg
from pathlib import Path

from mcp.server.fastmcp import FastMCP

# --------------------------------------------------------------------------
# Configuration
# --------------------------------------------------------------------------

WORKSPACE_ROOT = Path(
    os.environ.get("AGENT_WORKSPACE", Path(__file__).resolve().parents[2])
).resolve()

LOG_DIR = WORKSPACE_ROOT / "agent" / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)

logging.basicConfig(
    filename=LOG_DIR / "unreal.log",
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    encoding="utf-8",
)
log = logging.getLogger("unreal")

EDITOR_MCP_URL = os.environ.get("UNREAL_MCP_URL", "http://127.0.0.1:8000/mcp")
COMPILE_TIMEOUT = int(os.environ.get("UNREAL_COMPILE_TIMEOUT", "1800"))
MAX_OUTPUT_CHARS = 30_000

# Motifs d'erreur/avertissement des logs Unreal.
ERROR_RE = re.compile(r"^(?P<ts>\[[^\]]+\])?\s*(?P<cat>[\w]+):\s*(?P<lvl>Error|Warning):\s*(?P<msg>.+)$")
COMPILER_RE = re.compile(r"\b(error|warning)\s*:", re.IGNORECASE)

mcp = FastMCP("agent-unreal")


class UnrealError(Exception):
    """Erreur d'usage renvoyee proprement au modele."""


def _truncate(text: str, limit: int = MAX_OUTPUT_CHARS) -> str:
    if len(text) <= limit:
        return text
    return text[:limit] + f"\n... [tronque, {len(text) - limit} caracteres supplementaires]"


def _find_uproject() -> Path:
    matches = sorted(WORKSPACE_ROOT.glob("*.uproject"))
    if not matches:
        raise UnrealError(f"Aucun fichier .uproject trouve dans {WORKSPACE_ROOT}")
    return matches[0]


def _engine_roots() -> dict[str, Path]:
    """Recense les moteurs installes : registre Epic + dossiers sur disque."""
    roots: dict[str, Path] = {}
    for hive, key in (
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\EpicGames\Unreal Engine"),
        (winreg.HKEY_CURRENT_USER, r"SOFTWARE\EpicGames\Unreal Engine"),
    ):
        try:
            with winreg.OpenKey(hive, key) as handle:
                for i in range(winreg.QueryInfoKey(handle)[0]):
                    version = winreg.EnumKey(handle, i)
                    try:
                        with winreg.OpenKey(handle, version) as sub:
                            path = Path(winreg.QueryValueEx(sub, "InstalledDirectory")[0])
                            if path.is_dir():
                                roots[version] = path
                    except OSError:
                        continue
        except OSError:
            continue

    # UE 5.8 peut etre installe sans etre declare dans le registre.
    for base in (Path(r"C:\Program Files\Epic Games"), Path(r"D:\Epic Games"), Path(r"E:\Epic Games")):
        if not base.is_dir():
            continue
        for entry in base.glob("UE_*"):
            version = entry.name.removeprefix("UE_")
            if version not in roots and (entry / "Engine").is_dir():
                roots[version] = entry
    return roots


def _engine_root_for_project() -> Path:
    data = json.loads(_find_uproject().read_text(encoding="utf-8-sig"))
    wanted = str(data.get("EngineAssociation", "")).strip()
    roots = _engine_roots()
    if wanted in roots:
        return roots[wanted]
    if not roots:
        raise UnrealError("Aucune installation d'Unreal Engine detectee.")
    fallback = sorted(roots)[-1]
    log.warning("EngineAssociation '%s' introuvable, repli sur %s", wanted, fallback)
    return roots[fallback]


def _editor_cmd() -> Path:
    exe = _engine_root_for_project() / "Engine" / "Binaries" / "Win64" / "UnrealEditor-Cmd.exe"
    if not exe.is_file():
        raise UnrealError(f"UnrealEditor-Cmd.exe introuvable: {exe}")
    return exe


def _clear_stale_build_locks() -> list[int]:
    """Tue les 'cmd.exe Build.bat' orphelins qui bloquent le demarrage de l'editeur.

    CAUSE RACINE (diagnostiquee sur cette machine) : au demarrage, le module
    Turnkey de l'editeur lance
        cmd.exe /c Build.bat -Mode=ValidatePlatforms -OutputSDKs -AllPlatforms
    Or Build.bat s'auto-serialise via un verrou (Engine/Build/BatchFiles/Build.bat,
    ligne 26 : `9>"%LockFile%"`). Si le verrou ne peut pas etre pris, le script
    boucle INDEFINIMENT sur `ping 127.0.0.1 -n 2` (ligne 29) sans jamais definir
    ExitCode, donc sans jamais abandonner.
    Si une execution precedente de l'editeur a ete interrompue, son Build.bat
    survit en orphelin et retient le verrou : TOUTE execution suivante de
    UnrealEditor-Cmd se fige juste apres "InternalLoadLibrary: 'TurnkeySupport'".
    Symptomes : CPU a plat, aucun processus dotnet, AutoSDKInfo.txt jamais ecrit.

    On ne cible QUE des cmd.exe dont la ligne de commande contient Build.bat ET
    ValidatePlatforms, et qui tournent depuis plus de MAX_AGE_S. Une execution
    saine de cette commande dure moins de 2 s (mesure : 0,7 s) : au-dela, le
    processus est necessairement coince dans la boucle de verrou.
    """
    if os.name != "nt":
        return []
    max_age_s = 60
    killed: list[int] = []
    ps = (
        "Get-CimInstance Win32_Process -Filter \"Name='cmd.exe'\" | "
        "Where-Object { $_.CommandLine -match 'Build\\.bat' -and "
        "$_.CommandLine -match 'ValidatePlatforms' -and "
        f"((Get-Date) - $_.CreationDate).TotalSeconds -gt {max_age_s}"
        " } | ForEach-Object { $_.ProcessId }"
    )
    try:
        res = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", ps],
            capture_output=True, text=True, timeout=30,
            stdin=subprocess.DEVNULL,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except (OSError, subprocess.SubprocessError) as exc:
        log.warning("Nettoyage des verrous Build.bat impossible: %s", exc)
        return []
    for token in res.stdout.split():
        if not token.isdigit():
            continue
        target = int(token)
        try:
            subprocess.run(
                ["taskkill", "/PID", token, "/T", "/F"],
                capture_output=True, timeout=15, stdin=subprocess.DEVNULL,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            killed.append(target)
        except (OSError, subprocess.SubprocessError):
            pass
    if killed:
        log.warning("Verrous Build.bat orphelins supprimes: %s", killed)
    return killed


def _run_editor(extra_args: list[str], timeout: int, log_name: str) -> dict:
    """Lance UnrealEditor-Cmd sur le projet et capture le resultat."""
    out_log = LOG_DIR / log_name
    stdio_log = LOG_DIR / f"{Path(log_name).stem}.stdout.log"
    args = [
        str(_editor_cmd()),
        str(_find_uproject()),
        *extra_args,
        "-unattended",
        "-nopause",
        "-nosplash",
        "-nullrhi",
        "-stdout",
        "-utf8output",
        f"-abslog={out_log}",
    ]
    log.info("EDITOR %s", " ".join(args[2:]))
    _clear_stale_build_locks()

    # IMPORTANT : ne JAMAIS donner de tubes (pipes) a UnrealEditor-Cmd.
    # On redirige vers de VRAIS fichiers et on lit le log via -abslog.
    # CREATE_NO_WINDOW alloue une console aux enfants sans afficher de fenetre.
    creation_flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    deadline = time.monotonic() + timeout
    exit_code, timed_out = -1, False
    try:
        with open(stdio_log, "w", encoding="utf-8", errors="replace") as sink:
            proc = subprocess.Popen(
                args,
                cwd=str(WORKSPACE_ROOT),
                stdin=subprocess.DEVNULL,
                stdout=sink,
                stderr=subprocess.STDOUT,
                creationflags=creation_flags,
            )
            # Chien de garde : le Build.bat lance par Turnkey peut se coincer
            # sur son verrou pendant CETTE execution. On le detecte et on le
            # tue periodiquement, ce qui laisse l'editeur poursuivre son
            # demarrage au lieu d'attendre indefiniment.
            while True:
                try:
                    exit_code = proc.wait(timeout=30)
                    break
                except subprocess.TimeoutExpired:
                    if time.monotonic() >= deadline:
                        timed_out = True
                        proc.kill()
                        proc.wait(timeout=30)
                        break
                    _clear_stale_build_locks()
    except OSError as exc:
        log.error("EDITOR echec d'execution: %s", exc)
        return {"exit_code": -1, "timed_out": False, "log_file": str(out_log),
                "log": f"Echec d'execution: {exc}"}

    def _read(path: Path) -> str:
        return path.read_text(encoding="utf-8", errors="replace") if path.exists() else ""

    combined = _read(out_log) or _read(stdio_log)
    log.info("EDITOR exit=%s timed_out=%s", exit_code, timed_out)
    return {
        "exit_code": exit_code,
        "timed_out": timed_out,
        "log_file": str(out_log),
        "log": combined,
    }


def _extract_issues(text: str) -> dict:
    errors: list[str] = []
    warnings: list[str] = []
    for line in text.splitlines():
        match = ERROR_RE.match(line.strip())
        if match:
            (errors if match.group("lvl") == "Error" else warnings).append(line.strip()[:400])
        elif COMPILER_RE.search(line) and ("error" in line.lower()):
            errors.append(line.strip()[:400])
    # Deduplication en conservant l'ordre.
    return {
        "errors": list(dict.fromkeys(errors))[:150],
        "warnings": list(dict.fromkeys(warnings))[:80],
    }


# --------------------------------------------------------------------------
# Outils : inspection (hors-ligne, toujours disponibles)
# --------------------------------------------------------------------------

@mcp.tool()
def unreal_get_project_info() -> dict:
    """Retourne les informations du projet Unreal : version du moteur, plugins, structure.

    Appelle cet outil en premier pour comprendre le projet sur lequel tu travailles.
    """
    uproject = _find_uproject()
    data = json.loads(uproject.read_text(encoding="utf-8-sig"))
    has_source = (WORKSPACE_ROOT / "Source").is_dir()
    cpp_files = []
    if has_source:
        cpp_files = [
            str(p.relative_to(WORKSPACE_ROOT))
            for p in list((WORKSPACE_ROOT / "Source").rglob("*.cpp"))[:200]
        ]
    try:
        engine_root = str(_engine_root_for_project())
    except UnrealError as exc:
        engine_root = f"(indetermine: {exc})"

    return {
        "project_name": uproject.stem,
        "uproject": str(uproject),
        "workspace_root": str(WORKSPACE_ROOT),
        "engine_association": data.get("EngineAssociation"),
        "engine_root": engine_root,
        "enabled_plugins": [p.get("Name") for p in data.get("Plugins", []) if p.get("Enabled")],
        "has_source_folder": has_source,
        "cpp_file_count": len(cpp_files),
        "cpp_files_sample": cpp_files[:25],
        "content_asset_count": len(list((WORKSPACE_ROOT / "Content").rglob("*.uasset")))
        if (WORKSPACE_ROOT / "Content").is_dir() else 0,
        "project_type": "C++" if has_source else "Blueprint uniquement",
        "note": (
            "Projet sans dossier Source/ : il n'y a pas de code C++ a compiler. "
            "La compilation pertinente est celle des Blueprints "
            "(outil unreal_compile_blueprints)."
        ) if not has_source else "",
    }


@mcp.tool()
def unreal_list_engine_versions() -> dict:
    """Liste les versions d'Unreal Engine installees sur la machine."""
    roots = _engine_roots()
    versions = {}
    for version, path in sorted(roots.items()):
        build_version = path / "Engine" / "Build" / "Build.version"
        detail = {"path": str(path)}
        if build_version.is_file():
            try:
                detail |= json.loads(build_version.read_text(encoding="utf-8-sig"))
            except (OSError, json.JSONDecodeError):
                pass
        versions[version] = detail
    return {"installed": versions, "count": len(versions)}


@mcp.tool()
def unreal_get_output_log(lines: int = 200, only_issues: bool = False) -> dict:
    """Lit la fin du log de l'editeur Unreal du projet (Saved/Logs).

    Args:
        lines: Nombre de lignes a retourner depuis la fin du fichier.
        only_issues: True pour ne retourner que les erreurs et avertissements.
    """
    log_dir = WORKSPACE_ROOT / "Saved" / "Logs"
    if not log_dir.is_dir():
        raise UnrealError(f"Dossier de logs introuvable: {log_dir}")
    candidates = sorted(log_dir.glob("*.log"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not candidates:
        raise UnrealError(f"Aucun fichier .log dans {log_dir}")

    newest = candidates[0]
    text = newest.read_text(encoding="utf-8", errors="replace")
    if only_issues:
        issues = _extract_issues(text)
        return {"log_file": str(newest), **issues}
    tail = text.splitlines()[-max(1, min(lines, 3000)):]
    return {"log_file": str(newest), "lines": len(tail), "content": _truncate("\n".join(tail))}


# --------------------------------------------------------------------------
# Outils : compilation (boucle autonome de la phase 10)
# --------------------------------------------------------------------------

@mcp.tool()
def unreal_compile_blueprints(timeout: int = COMPILE_TIMEOUT) -> dict:
    """Compile TOUS les Blueprints du projet via le commandlet CompileAllBlueprints.

    C'est l'equivalent d'une compilation pour un projet Blueprint : l'editeur est
    lance en mode headless, chaque Blueprint est charge et compile, et les erreurs
    sont remontees. Operation longue (plusieurs minutes).

    Args:
        timeout: Delai maximum en secondes.
    """
    result = _run_editor(
        ["-run=CompileAllBlueprints", "-IgnoreFolder=/Engine"],
        timeout=timeout,
        log_name="compile_blueprints.log",
    )
    issues = _extract_issues(result["log"])
    success = result["exit_code"] == 0 and not issues["errors"] and not result["timed_out"]
    return {
        "success": success,
        "exit_code": result["exit_code"],
        "timed_out": result["timed_out"],
        "error_count": len(issues["errors"]),
        "warning_count": len(issues["warnings"]),
        "errors": issues["errors"],
        "warnings": issues["warnings"][:20],
        "log_file": result["log_file"],
    }


@mcp.tool()
def unreal_build_cpp(configuration: str = "Development", timeout: int = COMPILE_TIMEOUT) -> dict:
    """Compile le code C++ du projet via UnrealBuildTool (necessite un dossier Source/).

    Args:
        configuration: Development, DebugGame ou Shipping.
        timeout: Delai maximum en secondes.
    """
    if not (WORKSPACE_ROOT / "Source").is_dir():
        return {
            "success": False,
            "skipped": True,
            "reason": (
                "Ce projet n'a pas de dossier Source/ : c'est un projet Blueprint "
                "uniquement, il n'y a aucun code C++ a compiler. "
                "Utilise unreal_compile_blueprints a la place."
            ),
        }
    if configuration not in {"Development", "DebugGame", "Shipping"}:
        raise UnrealError("configuration doit valoir Development, DebugGame ou Shipping.")

    build_bat = _engine_root_for_project() / "Engine" / "Build" / "BatchFiles" / "Build.bat"
    target = f"{_find_uproject().stem}Editor"
    args = [str(build_bat), target, "Win64", configuration,
            f"-Project={_find_uproject()}", "-WaitMutex", "-FromMsBuild"]
    log.info("BUILD %s", " ".join(args))
    try:
        proc = subprocess.run(
            args, cwd=str(WORKSPACE_ROOT), stdin=subprocess.DEVNULL,
            capture_output=True, text=True, encoding="utf-8",
            errors="replace", timeout=timeout,
        )
        output, exit_code, timed_out = proc.stdout + proc.stderr, proc.returncode, False
    except subprocess.TimeoutExpired:
        output, exit_code, timed_out = "", -1, True

    issues = _extract_issues(output)
    return {
        "success": exit_code == 0 and not timed_out,
        "skipped": False,
        "exit_code": exit_code,
        "timed_out": timed_out,
        "error_count": len(issues["errors"]),
        "errors": issues["errors"],
        "warnings": issues["warnings"][:20],
        "output_tail": _truncate("\n".join(output.splitlines()[-120:])),
    }


@mcp.tool()
def unreal_get_compile_errors() -> dict:
    """Relit le log de la derniere compilation et en extrait les erreurs.

    Utile dans la boucle corriger/recompiler pour reexaminer les erreurs
    sans relancer une compilation complete.
    """
    candidates = [LOG_DIR / "compile_blueprints.log", LOG_DIR / "python_exec.log"]
    existing = [p for p in candidates if p.is_file()]
    if not existing:
        return {
            "available": False,
            "reason": "Aucune compilation n'a encore ete lancee par l'agent. "
                      "Execute d'abord unreal_compile_blueprints.",
        }
    newest = max(existing, key=lambda p: p.stat().st_mtime)
    issues = _extract_issues(newest.read_text(encoding="utf-8", errors="replace"))
    return {
        "available": True,
        "log_file": str(newest),
        "error_count": len(issues["errors"]),
        **issues,
    }


# --------------------------------------------------------------------------
# Outils : scripting de l'editeur
# --------------------------------------------------------------------------

@mcp.tool()
def unreal_run_python(script: str, timeout: int = 900) -> dict:
    """Execute un script Python de l'editeur Unreal en mode headless.

    Donne acces a l'API `unreal` complete (assets, acteurs, Blueprints) sans
    editeur ouvert. Necessite le plugin PythonScriptPlugin, active dans ce projet.

    Exemple de script :
        import unreal
        for a in unreal.EditorLevelLibrary.get_all_level_actors():
            print(a.get_name())

    Args:
        script: Code Python a executer (API `unreal` disponible).
        timeout: Delai maximum en secondes.
    """
    if not script.strip():
        raise UnrealError("Le script ne peut pas etre vide.")
    # Le script est ecrit dans un repertoire SANS ESPACE et le chemin est passe
    # avec des slashs : UE interprete mal '-ExecutePythonScript=' quand le chemin
    # contient des espaces (coupe a l'espace) ou des antislashs suivis d'une
    # lettre d'echappement (C:\Users\... -> '\n' interprete comme un saut de
    # ligne). Constate ici : "Could not load Python file 'C:/Users".
    script_dir = Path(tempfile.gettempdir()) / "ue_agent"
    script_dir.mkdir(parents=True, exist_ok=True)
    script_path = script_dir / "_exec.py"
    script_path.write_text(script, encoding="utf-8")
    script_arg = str(script_path).replace("\\", "/")
    if " " in script_arg:
        raise UnrealError(
            f"Chemin de script temporaire invalide (contient un espace): {script_arg}"
        )

    result = _run_editor(
        [f"-ExecutePythonScript={script_arg}"],
        timeout=timeout,
        log_name="python_exec.log",
    )
    issues = _extract_issues(result["log"])
    # Les lignes de sortie du script apparaissent via LogPython.
    printed = [
        line.split("LogPython:", 1)[1].strip()
        for line in result["log"].splitlines()
        if "LogPython:" in line
    ]
    return {
        "success": result["exit_code"] == 0 and not result["timed_out"],
        "exit_code": result["exit_code"],
        "timed_out": result["timed_out"],
        "output": _truncate("\n".join(printed)) or "(aucune sortie print)",
        "errors": issues["errors"][:40],
        "log_file": result["log_file"],
    }


# --------------------------------------------------------------------------
# Outils : pont vers le serveur MCP officiel de l'editeur
# --------------------------------------------------------------------------

@mcp.tool()
def unreal_mcp_status() -> dict:
    """Indique si le serveur MCP officiel d'Epic (editeur ouvert) est joignable.

    Si l'editeur Unreal est ouvert avec le plugin ModelContextProtocol actif,
    les outils de scene vivante (acteurs, commandes console, Blueprints) sont
    disponibles directement dans Copilot CLI via le serveur "unreal-editor".
    """
    request = urllib.request.Request(
        EDITOR_MCP_URL,
        data=json.dumps({"jsonrpc": "2.0", "id": 1, "method": "ping"}).encode("utf-8"),
        headers={"Content-Type": "application/json", "Accept": "application/json, text/event-stream"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=5) as response:
            return {
                "reachable": True,
                "url": EDITOR_MCP_URL,
                "http_status": response.status,
                "hint": "Les outils de scene vivante sont exposes par le serveur MCP 'unreal-editor'.",
            }
    except urllib.error.HTTPError as exc:
        # Une reponse HTTP, meme en erreur, prouve que le serveur ecoute.
        return {"reachable": True, "url": EDITOR_MCP_URL, "http_status": exc.code,
                "hint": "Serveur present (reponse HTTP recue)."}
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        return {
            "reachable": False,
            "url": EDITOR_MCP_URL,
            "reason": str(exc),
            "hint": (
                "Ouvre le projet dans Unreal Editor 5.8. Le plugin "
                "ModelContextProtocol demarre le serveur automatiquement "
                "(bAutoStartServer=True dans DefaultEditorPerProjectUserSettings.ini). "
                "En attendant, utilise les outils hors-ligne de ce serveur."
            ),
        }


if __name__ == "__main__":
    mcp.run(transport="stdio")
