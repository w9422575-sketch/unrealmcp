"""
Serveur MCP "workspace" - PHASE 7
==================================
Outils fichiers / recherche / terminal / Git, confines au projet Unreal.

SECURITE (phase 11) :
  - Toutes les operations sont confinees a WORKSPACE_ROOT (anti path-traversal).
  - Les commandes destructives connues sont refusees (liste noire).
  - Chaque commande a un timeout (defaut 120 s, plafond 900 s).
  - Les ecritures sont journalisees dans agent/logs/workspace.log.
  - Aucun secret n'est present dans ce fichier.

La racine du workspace se configure via la variable d'environnement
AGENT_WORKSPACE ; a defaut, le dossier parent de agent/.
"""

from __future__ import annotations

import fnmatch
import logging
import os
import re
import subprocess
import sys
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
    filename=LOG_DIR / "workspace.log",
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    encoding="utf-8",
)
log = logging.getLogger("workspace")

DEFAULT_TIMEOUT = 120
MAX_TIMEOUT = 900
MAX_READ_BYTES = 400_000
MAX_OUTPUT_CHARS = 30_000

# Dossiers generes : exclus des recherches pour ne pas noyer le modele.
EXCLUDED_DIRS = {
    ".git", "Binaries", "Build", "DerivedDataCache", "Intermediate",
    "Saved", ".vs", "node_modules", "__pycache__", ".venv",
}

# Commandes refusees sans condition (phase 11).
FORBIDDEN_PATTERNS: list[tuple[str, str]] = [
    (r"\bformat\s+[a-z]:", "formatage de disque"),
    (r"\bdiskpart\b", "manipulation de partitions"),
    (r"\bmkfs\b", "formatage de systeme de fichiers"),
    (r"\bgit\s+reset\s+--hard\b", "git reset --hard (perte de travail)"),
    (r"\bgit\s+clean\s+-[a-z]*f", "git clean -fd (suppression non suivie)"),
    (r"\bgit\s+push\b.*--force", "push force"),
    (r"\bRemove-Item\b[^|;]*\s-Recurse\b[^|;]*\s-Force\b", "suppression recursive forcee"),
    (r"\brd\s+/s\b|\brmdir\s+/s\b", "suppression recursive"),
    (r"\bdel\s+/[sq]\b", "suppression massive"),
    (r"\brm\s+-rf\b", "suppression recursive forcee"),
    (r"\bShutdown\b|\bRestart-Computer\b|\bStop-Computer\b", "arret/redemarrage systeme"),
    (r"\bSet-ExecutionPolicy\b", "modification de la politique d'execution"),
    (r"\bcipher\s+/w", "effacement securise"),
    (r"\bvssadmin\b.*delete", "suppression des cliches instantanes"),
    (r"\bbcdedit\b", "modification du demarrage"),
    (r"\bNew-ItemProperty\b.*HKLM|\breg\s+add\b.*HKLM", "ecriture dans HKLM"),
    (r"\bStop-Process\b(?![^|;]*-Id\s+\d+)", "arret de processus sans PID explicite"),
    (r"\btaskkill\b\s+/im", "arret de processus par nom"),
]

mcp = FastMCP("agent-workspace")


# --------------------------------------------------------------------------
# Helpers de securite
# --------------------------------------------------------------------------

class WorkspaceError(Exception):
    """Erreur de securite ou d'usage, renvoyee proprement au modele."""


def _resolve(relative_path: str) -> Path:
    """Resout un chemin en garantissant qu'il reste dans le workspace."""
    candidate = Path(relative_path)
    target = (candidate if candidate.is_absolute() else WORKSPACE_ROOT / candidate).resolve()
    if target != WORKSPACE_ROOT and WORKSPACE_ROOT not in target.parents:
        raise WorkspaceError(
            f"REFUS: '{relative_path}' sort du workspace autorise ({WORKSPACE_ROOT})."
        )
    return target


def _rel(path: Path) -> str:
    try:
        return str(path.relative_to(WORKSPACE_ROOT))
    except ValueError:
        return str(path)


def _check_command(command: str) -> None:
    for pattern, label in FORBIDDEN_PATTERNS:
        if re.search(pattern, command, re.IGNORECASE):
            log.warning("COMMANDE REFUSEE (%s): %s", label, command)
            raise WorkspaceError(
                f"REFUS: commande bloquee par la politique de securite ({label}). "
                f"Demande a l'utilisateur de l'executer manuellement s'il le souhaite."
            )


def _is_excluded(path: Path) -> bool:
    return any(part in EXCLUDED_DIRS for part in path.parts)


def _truncate(text: str, limit: int = MAX_OUTPUT_CHARS) -> str:
    if len(text) <= limit:
        return text
    return text[:limit] + f"\n... [tronque, {len(text) - limit} caracteres supplementaires]"


def _run(args: list[str], timeout: int, cwd: Path | None = None) -> dict:
    # IMPORTANT : sur un serveur MCP stdio, stdin/stdout du processus sont les
    # tuyaux du protocole. Un enfant qui en herite peut bloquer indefiniment ou
    # corrompre le flux MCP. On isole donc systematiquement son stdin.
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_CONFIG_")}
    env["GIT_TERMINAL_PROMPT"] = "0"
    env["GIT_PAGER"] = "cat"
    try:
        proc = subprocess.run(
            args,
            cwd=str(cwd or WORKSPACE_ROOT),
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            env=env,
        )
    except subprocess.TimeoutExpired:
        return {"exit_code": -1, "stdout": "", "stderr": f"TIMEOUT apres {timeout}s", "timed_out": True}
    except OSError as exc:
        return {"exit_code": -1, "stdout": "", "stderr": f"Echec d'execution: {exc}", "timed_out": False}
    return {
        "exit_code": proc.returncode,
        "stdout": _truncate(proc.stdout or ""),
        "stderr": _truncate(proc.stderr or ""),
        "timed_out": False,
    }


# --------------------------------------------------------------------------
# Outils : informations
# --------------------------------------------------------------------------

@mcp.tool()
def ws_info() -> dict:
    """Retourne la racine du workspace et ses regles de securite.

    Appelle cet outil en premier pour savoir sur quel dossier tu travailles.
    """
    return {
        "workspace_root": str(WORKSPACE_ROOT),
        "excluded_dirs": sorted(EXCLUDED_DIRS),
        "default_timeout_s": DEFAULT_TIMEOUT,
        "max_timeout_s": MAX_TIMEOUT,
        "forbidden_command_count": len(FORBIDDEN_PATTERNS),
        "note": "Toute operation hors de workspace_root est refusee.",
    }


# --------------------------------------------------------------------------
# Outils : fichiers
# --------------------------------------------------------------------------

@mcp.tool()
def read_file(path: str, start_line: int = 1, end_line: int = 0) -> str:
    """Lit un fichier texte du workspace.

    Args:
        path: Chemin relatif a la racine du workspace.
        start_line: Premiere ligne a lire (1-indexee).
        end_line: Derniere ligne incluse. 0 = jusqu'a la fin.
    """
    target = _resolve(path)
    if not target.is_file():
        raise WorkspaceError(f"Fichier introuvable: {path}")
    if target.stat().st_size > MAX_READ_BYTES:
        raise WorkspaceError(
            f"Fichier trop volumineux ({target.stat().st_size} octets). "
            f"Utilise start_line/end_line pour lire une portion."
        )
    lines = target.read_text(encoding="utf-8", errors="replace").splitlines()
    last = len(lines) if end_line <= 0 else min(end_line, len(lines))
    selected = lines[max(start_line - 1, 0):last]
    numbered = "\n".join(f"{i}: {t}" for i, t in enumerate(selected, start=max(start_line, 1)))
    return _truncate(numbered)


@mcp.tool()
def write_file(path: str, content: str) -> str:
    """Cree ou remplace integralement un fichier du workspace.

    Args:
        path: Chemin relatif a la racine du workspace.
        content: Contenu complet du fichier.
    """
    target = _resolve(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    existed = target.exists()
    target.write_text(content, encoding="utf-8")
    log.info("WRITE %s (%d octets, %s)", _rel(target), len(content),
             "remplacement" if existed else "creation")
    return f"{'Remplace' if existed else 'Cree'}: {_rel(target)} ({len(content)} octets)"


@mcp.tool()
def edit_file(path: str, old_text: str, new_text: str) -> str:
    """Remplace une occurrence unique de texte dans un fichier.

    Echoue si old_text est absent ou present plusieurs fois : cela evite
    les remplacements involontaires. Ajoute du contexte pour desambiguiser.

    Args:
        path: Chemin relatif a la racine du workspace.
        old_text: Texte exact a remplacer.
        new_text: Texte de remplacement.
    """
    target = _resolve(path)
    if not target.is_file():
        raise WorkspaceError(f"Fichier introuvable: {path}")
    original = target.read_text(encoding="utf-8", errors="replace")
    count = original.count(old_text)
    if count == 0:
        raise WorkspaceError("old_text introuvable dans le fichier.")
    if count > 1:
        raise WorkspaceError(f"old_text present {count} fois. Ajoute du contexte pour le rendre unique.")
    target.write_text(original.replace(old_text, new_text, 1), encoding="utf-8")
    log.info("EDIT %s", _rel(target))
    return f"Modifie: {_rel(target)}"


@mcp.tool()
def list_dir(path: str = ".") -> dict:
    """Liste le contenu d'un dossier du workspace (dossiers generes exclus).

    Args:
        path: Chemin relatif du dossier. "." pour la racine.
    """
    target = _resolve(path)
    if not target.is_dir():
        raise WorkspaceError(f"Dossier introuvable: {path}")
    dirs, files = [], []
    for entry in sorted(target.iterdir(), key=lambda p: p.name.lower()):
        if entry.name in EXCLUDED_DIRS:
            continue
        if entry.is_dir():
            dirs.append(entry.name)
        else:
            files.append({"name": entry.name, "size": entry.stat().st_size})
    return {"path": _rel(target), "directories": dirs, "files": files}


@mcp.tool()
def find_files(pattern: str, max_results: int = 100) -> list[str]:
    """Recherche des fichiers par motif glob sur leur nom.

    Args:
        pattern: Motif glob, par ex. "*.uasset", "*.cpp", "Default*.ini".
        max_results: Nombre maximum de resultats.
    """
    results: list[str] = []
    for root, dirnames, filenames in os.walk(WORKSPACE_ROOT):
        dirnames[:] = [d for d in dirnames if d not in EXCLUDED_DIRS]
        for name in filenames:
            if fnmatch.fnmatch(name, pattern):
                results.append(_rel(Path(root) / name))
                if len(results) >= max_results:
                    return results
    return results


@mcp.tool()
def search_text(pattern: str, file_glob: str = "*", max_results: int = 60) -> list[dict]:
    """Recherche une expression reguliere dans les fichiers texte du workspace.

    Args:
        pattern: Expression reguliere Python.
        file_glob: Filtre sur le nom de fichier, par ex. "*.ini" ou "*.cpp".
        max_results: Nombre maximum de correspondances.
    """
    try:
        regex = re.compile(pattern)
    except re.error as exc:
        raise WorkspaceError(f"Expression reguliere invalide: {exc}") from exc

    hits: list[dict] = []
    for root, dirnames, filenames in os.walk(WORKSPACE_ROOT):
        dirnames[:] = [d for d in dirnames if d not in EXCLUDED_DIRS]
        for name in filenames:
            if not fnmatch.fnmatch(name, file_glob):
                continue
            fpath = Path(root) / name
            try:
                if fpath.stat().st_size > MAX_READ_BYTES:
                    continue
                text = fpath.read_text(encoding="utf-8", errors="strict")
            except (OSError, UnicodeDecodeError):
                continue  # binaire ou illisible
            for lineno, line in enumerate(text.splitlines(), start=1):
                if regex.search(line):
                    hits.append({"file": _rel(fpath), "line": lineno, "text": line.strip()[:300]})
                    if len(hits) >= max_results:
                        return hits
    return hits


# --------------------------------------------------------------------------
# Outils : terminal
# --------------------------------------------------------------------------

@mcp.tool()
def run_powershell(command: str, timeout: int = DEFAULT_TIMEOUT) -> dict:
    """Execute une commande PowerShell a la racine du workspace.

    Retourne stdout, stderr et le code de sortie. Les commandes destructives
    sont refusees par la politique de securite.

    Args:
        command: Commande PowerShell a executer.
        timeout: Delai maximum en secondes (plafond 900).
    """
    _check_command(command)
    timeout = max(1, min(int(timeout), MAX_TIMEOUT))
    log.info("RUN %s", command)
    shell = "powershell.exe" if sys.platform == "win32" else "pwsh"
    result = _run(
        [shell, "-NoProfile", "-NonInteractive", "-Command", command],
        timeout=timeout,
    )
    log.info("RUN exit=%s", result["exit_code"])
    return result


# --------------------------------------------------------------------------
# Outils : Git
# --------------------------------------------------------------------------

@mcp.tool()
def git_status() -> dict:
    """Retourne l'etat Git du workspace (branche et fichiers modifies)."""
    branch = _run(["git", "rev-parse", "--abbrev-ref", "HEAD"], timeout=30)
    status = _run(["git", "status", "--porcelain"], timeout=60)
    changes = [l for l in status["stdout"].splitlines() if l.strip()]
    return {
        "branch": branch["stdout"].strip(),
        "changed_file_count": len(changes),
        "changes": changes[:200],
    }


@mcp.tool()
def git_diff(path: str = "", staged: bool = False) -> str:
    """Affiche le diff Git du workspace.

    Args:
        path: Limite le diff a un chemin. Vide = tout le workspace.
        staged: True pour le diff de l'index, False pour l'arbre de travail.
    """
    args = ["git", "--no-pager", "diff"]
    if staged:
        args.append("--cached")
    if path:
        args += ["--", str(_resolve(path))]
    return _truncate(_run(args, timeout=90)["stdout"]) or "(aucune difference)"


@mcp.tool()
def git_log(max_count: int = 15) -> list[str]:
    """Retourne les derniers commits du workspace.

    Args:
        max_count: Nombre de commits a retourner.
    """
    res = _run(["git", "--no-pager", "log", f"-{max(1, min(max_count, 200))}", "--oneline"], timeout=60)
    return res["stdout"].splitlines()


@mcp.tool()
def git_commit(message: str, add_all: bool = True) -> dict:
    """Cree un commit Git dans le workspace (point de rollback).

    Args:
        message: Message de commit.
        add_all: True pour indexer toutes les modifications avant de commiter.
    """
    if not message.strip():
        raise WorkspaceError("Le message de commit ne peut pas etre vide.")
    if add_all:
        _run(["git", "add", "-A"], timeout=120)
    result = _run(["git", "commit", "-m", message], timeout=120)
    log.info("COMMIT exit=%s msg=%s", result["exit_code"], message)
    head = _run(["git", "--no-pager", "log", "-1", "--oneline"], timeout=30)
    result["head"] = head["stdout"].strip()
    return result


if __name__ == "__main__":
    mcp.run(transport="stdio")
