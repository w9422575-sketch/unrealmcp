from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import mimetypes
import os
import re
import sqlite3
import shutil
import subprocess
import sys
import urllib.error
import urllib.request
import uuid
from contextlib import AsyncExitStack
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.client.streamable_http import streamablehttp_client

APP_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = APP_ROOT.parent
DIST_ROOT = APP_ROOT / "dist"
DATA_ROOT = Path(os.environ.get("LASTER_DATA_DIR", APP_ROOT / "data")).resolve()
DB_PATH = DATA_ROOT / "laster.db"
OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://127.0.0.1:11434").rstrip("/")
PORT = int(os.environ.get("LASTER_PORT", "4317"))
HOST = os.environ.get("LASTER_HOST", "127.0.0.1")
ACCESS_TOKEN = os.environ.get("LASTER_ACCESS_TOKEN", "")
DEFAULT_PROJECT = Path(os.environ.get("LASTER_DEFAULT_PROJECT", REPO_ROOT)).resolve()
READ_ONLY_TOOLS = {
    "ws_info",
    "read_file",
    "list_dir",
    "find_files",
    "search_text",
    "git_status",
    "git_diff",
    "git_log",
    "unreal_get_project_info",
    "unreal_list_engine_versions",
    "unreal_get_output_log",
    "unreal_get_compile_errors",
    "unreal_mcp_status",
}
COPILOT_MODEL_FALLBACK = (
    "auto",
    "claude-sonnet-5",
    "claude-fable-5.1",
    "claude-fable-5",
    "claude-opus-5",
    "claude-opus-4.8",
    "claude-opus-4.8-fast",
    "claude-opus-4.7",
    "claude-sonnet-4.6",
    "claude-haiku-4.5",
    "gpt-6-astra",
    "gpt-5.6-sol",
    "gpt-5.6-terra",
    "gpt-5.6-luna",
    "gpt-5.5",
    "gpt-5.4",
    "gpt-5.4-mini",
    "gpt-5.3-codex",
    "gpt-5-mini",
    "mai-code-1.1-flash",
    "mai-code-1-flash-picker",
    "gemini-3.8-flash",
    "gemini-3.7-flash",
    "gemini-3.6-flash",
    "gemini-3.5-flash",
    "grok-4.5",
    "kimi-k3",
    "kimi-k2.7-code",
)


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def open_db() -> sqlite3.Connection:
    connection = sqlite3.connect(DB_PATH, timeout=20)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA journal_mode=WAL")
    connection.execute("PRAGMA foreign_keys=ON")
    return connection


def init_db() -> None:
    DATA_ROOT.mkdir(parents=True, exist_ok=True)
    with open_db() as connection:
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS projects (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                path TEXT NOT NULL UNIQUE,
                uproject TEXT,
                last_opened TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS conversations (
                id TEXT PRIMARY KEY,
                project_id TEXT NOT NULL,
                title TEXT NOT NULL,
                model TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY(project_id) REFERENCES projects(id) ON DELETE CASCADE
            );
            CREATE TABLE IF NOT EXISTS messages (
                id TEXT PRIMARY KEY,
                conversation_id TEXT NOT NULL,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                meta_json TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL,
                FOREIGN KEY(conversation_id) REFERENCES conversations(id) ON DELETE CASCADE
            );
            CREATE TABLE IF NOT EXISTS prompt_versions (
                id TEXT PRIMARY KEY,
                project_id TEXT NOT NULL,
                content TEXT NOT NULL,
                source TEXT NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY(project_id) REFERENCES projects(id) ON DELETE CASCADE
            );
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );
            """
        )
    if DEFAULT_PROJECT.is_dir():
        project = register_project(DEFAULT_PROJECT)
        with open_db() as connection:
            existing = connection.execute(
                "SELECT value FROM settings WHERE key = 'active_project_id'"
            ).fetchone()
            if not existing:
                connection.execute(
                    "INSERT INTO settings(key, value) VALUES('active_project_id', ?)",
                    (project["id"],),
                )


def project_identifier(path: Path) -> str:
    return hashlib.sha1(str(path).casefold().encode("utf-8")).hexdigest()[:12]


def register_project(path_value: str | Path) -> dict[str, Any]:
    path = Path(path_value).expanduser().resolve()
    if not path.is_dir():
        raise ValueError("Le dossier de projet n'existe pas.")
    uprojects = sorted(path.glob("*.uproject"))
    name = uprojects[0].stem if uprojects else path.name
    project = {
        "id": project_identifier(path),
        "name": name,
        "path": str(path),
        "uproject": str(uprojects[0]) if uprojects else None,
        "lastOpened": now_iso(),
    }
    with open_db() as connection:
        connection.execute(
            """
            INSERT INTO projects(id, name, path, uproject, last_opened)
            VALUES(?, ?, ?, ?, ?)
            ON CONFLICT(path) DO UPDATE SET
                name = excluded.name,
                uproject = excluded.uproject,
                last_opened = excluded.last_opened
            """,
            (
                project["id"],
                project["name"],
                project["path"],
                project["uproject"],
                project["lastOpened"],
            ),
        )
    return project


def list_projects() -> list[dict[str, Any]]:
    with open_db() as connection:
        rows = connection.execute(
            "SELECT id, name, path, uproject, last_opened FROM projects ORDER BY last_opened DESC"
        ).fetchall()
    return [
        {
            "id": row["id"],
            "name": row["name"],
            "path": row["path"],
            "uproject": row["uproject"],
            "lastOpened": row["last_opened"],
        }
        for row in rows
    ]


def get_project(project_id: str) -> dict[str, Any]:
    with open_db() as connection:
        row = connection.execute(
            "SELECT id, name, path, uproject, last_opened FROM projects WHERE id = ?",
            (project_id,),
        ).fetchone()
    if not row:
        raise ValueError("Projet introuvable.")
    return {
        "id": row["id"],
        "name": row["name"],
        "path": row["path"],
        "uproject": row["uproject"],
        "lastOpened": row["last_opened"],
    }


def active_project_id() -> str | None:
    with open_db() as connection:
        row = connection.execute(
            "SELECT value FROM settings WHERE key = 'active_project_id'"
        ).fetchone()
    return row["value"] if row else None


def set_active_project(project_id: str) -> None:
    project = get_project(project_id)
    with open_db() as connection:
        connection.execute(
            "INSERT INTO settings(key, value) VALUES('active_project_id', ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (project_id,),
        )
        connection.execute(
            "UPDATE projects SET last_opened = ? WHERE id = ?",
            (now_iso(), project["id"]),
        )


def list_conversations(project_id: str) -> list[dict[str, Any]]:
    with open_db() as connection:
        rows = connection.execute(
            """
            SELECT c.id, c.title, c.model, c.created_at, c.updated_at,
                   COUNT(m.id) AS message_count
            FROM conversations c
            LEFT JOIN messages m ON m.conversation_id = c.id
            WHERE c.project_id = ?
            GROUP BY c.id
            ORDER BY c.updated_at DESC
            """,
            (project_id,),
        ).fetchall()
    return [
        {
            "id": row["id"],
            "title": row["title"],
            "model": row["model"],
            "createdAt": row["created_at"],
            "updatedAt": row["updated_at"],
            "messageCount": row["message_count"],
        }
        for row in rows
    ]


def create_conversation(project_id: str, model: str, title: str = "Nouvelle conversation") -> dict[str, Any]:
    get_project(project_id)
    conversation_id = uuid.uuid4().hex
    timestamp = now_iso()
    with open_db() as connection:
        connection.execute(
            "INSERT INTO conversations(id, project_id, title, model, created_at, updated_at) "
            "VALUES(?, ?, ?, ?, ?, ?)",
            (conversation_id, project_id, title[:80], model, timestamp, timestamp),
        )
    return {
        "id": conversation_id,
        "title": title[:80],
        "model": model,
        "createdAt": timestamp,
        "updatedAt": timestamp,
        "messageCount": 0,
    }


def list_messages(conversation_id: str) -> list[dict[str, Any]]:
    with open_db() as connection:
        rows = connection.execute(
            "SELECT id, role, content, meta_json, created_at FROM messages "
            "WHERE conversation_id = ? ORDER BY created_at, rowid",
            (conversation_id,),
        ).fetchall()
    return [
        {
            "id": row["id"],
            "role": row["role"],
            "content": row["content"],
            "meta": json.loads(row["meta_json"]),
            "createdAt": row["created_at"],
        }
        for row in rows
    ]


def add_message(conversation_id: str, role: str, content: str, meta: dict[str, Any] | None = None) -> dict[str, Any]:
    message_id = uuid.uuid4().hex
    timestamp = now_iso()
    with open_db() as connection:
        conversation = connection.execute(
            "SELECT title FROM conversations WHERE id = ?", (conversation_id,)
        ).fetchone()
        if not conversation:
            raise ValueError("Conversation introuvable.")
        connection.execute(
            "INSERT INTO messages(id, conversation_id, role, content, meta_json, created_at) "
            "VALUES(?, ?, ?, ?, ?, ?)",
            (message_id, conversation_id, role, content, json.dumps(meta or {}), timestamp),
        )
        if role == "user" and conversation["title"] == "Nouvelle conversation":
            title = " ".join(content.strip().split())[:62] or "Nouvelle conversation"
            connection.execute(
                "UPDATE conversations SET title = ?, updated_at = ? WHERE id = ?",
                (title, timestamp, conversation_id),
            )
        else:
            connection.execute(
                "UPDATE conversations SET updated_at = ? WHERE id = ?",
                (timestamp, conversation_id),
            )
    return {
        "id": message_id,
        "role": role,
        "content": content,
        "meta": meta or {},
        "createdAt": timestamp,
    }


def save_prompt(project_id: str, content: str, source: str) -> None:
    normalized = content.strip()
    if not normalized:
        return
    with open_db() as connection:
        previous = connection.execute(
            "SELECT content FROM prompt_versions WHERE project_id = ? ORDER BY created_at DESC LIMIT 1",
            (project_id,),
        ).fetchone()
        if previous and previous["content"] == normalized:
            return
        connection.execute(
            "INSERT INTO prompt_versions(id, project_id, content, source, created_at) VALUES(?, ?, ?, ?, ?)",
            (uuid.uuid4().hex, project_id, normalized, source, now_iso()),
        )
        connection.execute(
            """
            DELETE FROM prompt_versions
            WHERE project_id = ? AND id NOT IN (
                SELECT id FROM prompt_versions WHERE project_id = ? ORDER BY created_at DESC LIMIT 60
            )
            """,
            (project_id, project_id),
        )


def list_prompts(project_id: str) -> list[dict[str, str]]:
    with open_db() as connection:
        rows = connection.execute(
            "SELECT id, content, source, created_at FROM prompt_versions "
            "WHERE project_id = ? ORDER BY created_at DESC LIMIT 60",
            (project_id,),
        ).fetchall()
    return [dict(row) for row in rows]


def ollama_request(endpoint: str, payload: dict[str, Any] | None = None, timeout: int = 600) -> dict[str, Any]:
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    request = urllib.request.Request(
        f"{OLLAMA_URL}{endpoint}",
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST" if payload is not None else "GET",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.URLError as error:
        raise RuntimeError(f"Ollama est injoignable sur {OLLAMA_URL}: {error}") from error


def format_size(size: int) -> str:
    return f"{size / 1_000_000_000:.1f} Go" if size else "local"


def copilot_model_name(model_id: str) -> str:
    if model_id == "auto":
        return "Auto"
    names = {
        "claude": "Claude",
        "sonnet": "Sonnet",
        "fable": "Fable",
        "opus": "Opus",
        "haiku": "Haiku",
        "gpt": "GPT",
        "astra": "Astra",
        "sol": "Sol",
        "terra": "Terra",
        "luna": "Luna",
        "mini": "Mini",
        "codex": "Codex",
        "mai": "MAI",
        "code": "Code",
        "flash": "Flash",
        "picker": "Picker",
        "gemini": "Gemini",
        "grok": "Grok",
        "kimi": "Kimi",
        "fast": "Fast",
    }
    return " ".join(names.get(part, part) for part in model_id.split("-"))


def list_copilot_model_ids(executable: str | None) -> list[str]:
    if not executable:
        return list(COPILOT_MODEL_FALLBACK)
    try:
        completed = subprocess.run(
            [executable, "help", "config"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=10,
            check=False,
        )
        output = f"{completed.stdout}\n{completed.stderr}"
        model_section = re.search(
            r"`model`:[^\n]*\n(?P<models>.*?)(?=\n\s*`contextTier`:)",
            output,
            re.DOTALL,
        )
        discovered = (
            re.findall(r'^\s*-\s*"([^"]+)"', model_section.group("models"), re.MULTILINE)
            if model_section
            else []
        )
        if discovered:
            return list(dict.fromkeys(["auto", *discovered]))
    except (OSError, subprocess.SubprocessError):
        pass
    return list(COPILOT_MODEL_FALLBACK)


def list_models() -> list[dict[str, Any]]:
    try:
        models = ollama_request("/api/tags", timeout=4).get("models", [])
    except RuntimeError:
        models = []
    result = []
    for model in models:
        details = model.get("details", {})
        name = model.get("name", "")
        lower = name.casefold()
        if any(token in lower for token in ("embed", "nomic-bert")):
            continue
        code_score = 3 if any(token in lower for token in ("coder", "code", "devstral")) else 1
        if "gpt-oss" in lower:
            code_score = 2
        result.append(
            {
                "id": name,
                "name": name,
                "size": model.get("size", 0),
                "sizeLabel": format_size(model.get("size", 0)),
                "parameterSize": details.get("parameter_size", ""),
                "quantization": details.get("quantization_level", ""),
                "codeScore": code_score,
                "local": True,
                "provider": "ollama",
                "available": True,
            }
        )
    copilot_executable = os.environ.get("LASTER_COPILOT_PATH") or shutil.which("copilot")
    for model_id in list_copilot_model_ids(copilot_executable):
        result.append(
            {
                "id": f"copilot:{model_id}",
                "name": copilot_model_name(model_id),
                "size": 0,
                "sizeLabel": "Copilot",
                "parameterSize": "",
                "quantization": "",
                "codeScore": 3,
                "local": False,
                "provider": "copilot",
                "available": bool(copilot_executable),
                "description": "Sélection automatique Copilot" if model_id == "auto" else "Modèle Copilot",
            }
        )
    return sorted(
        result,
        key=lambda item: (
            item["provider"] != "ollama",
            -item["codeScore"],
            item["name"],
        ),
    )


def select_adapter_model(models: list[dict[str, Any]], target_model: str) -> str:
    models = [model for model in models if model.get("provider") == "ollama"]
    if not models:
        raise RuntimeError("Aucun modèle Ollama installé.")
    ranked = sorted(
        models,
        key=lambda item: (
            item["codeScore"],
            item["id"] == target_model,
            item.get("size", 0),
        ),
        reverse=True,
    )
    return ranked[0]["id"]


def copilot_executable() -> str:
    executable = os.environ.get("LASTER_COPILOT_PATH") or shutil.which("copilot")
    if not executable:
        raise RuntimeError(
            "Le CLI Copilot est indisponible. Installez-le et connectez votre compte Copilot, "
            "ou choisissez un modèle Ollama local."
        )
    return executable


def write_mcp_config(project_path: str) -> Path:
    project_root = str(Path(project_path).resolve())
    config = {
        "mcpServers": {
            "agent-test": {
                "type": "local",
                "command": sys.executable,
                "args": [str(REPO_ROOT / "agent" / "mcp" / "test_server.py")],
                "tools": ["*"],
                "timeout": 30000,
            },
            "workspace": {
                "type": "local",
                "command": sys.executable,
                "args": [str(REPO_ROOT / "agent" / "mcp" / "workspace_server.py")],
                "env": {"AGENT_WORKSPACE": project_root},
                "tools": ["*"],
                "timeout": 180000,
            },
            "unreal": {
                "type": "local",
                "command": sys.executable,
                "args": [str(REPO_ROOT / "agent" / "mcp" / "unreal_server.py")],
                "env": {
                    "AGENT_WORKSPACE": project_root,
                    "UNREAL_MCP_URL": "http://127.0.0.1:8000/mcp",
                },
                "tools": ["*"],
                "timeout": 1800000,
            },
            "unreal-editor": {
                "type": "http",
                "url": "http://127.0.0.1:8000/mcp",
                "tools": ["*"],
                "timeout": 120000,
            },
        }
    }
    DATA_ROOT.mkdir(parents=True, exist_ok=True)
    config_path = DATA_ROOT / f"mcp-config-{uuid.uuid4().hex}.json"
    config_path.write_text(json.dumps(config, indent=2), encoding="utf-8")
    return config_path


def run_copilot_cli(
    project: dict[str, Any],
    model: str,
    messages: list[dict[str, Any]],
    mode: str,
) -> tuple[str, list[dict[str, Any]]]:
    model_id = model.removeprefix("copilot:")
    prompt_parts = []
    for message in messages[-40:]:
        role = "Utilisateur" if message["role"] == "user" else "Assistant"
        prompt_parts.append(f"{role}: {message['content']}")
    prompt = "\n\n".join(prompt_parts)
    prompt += (
        "\n\nRéponds en français. Le projet actif est "
        f"{project['name']} dans {project['path']}."
    )
    config_path = write_mcp_config(project["path"])
    args = [
        "--model",
        model_id,
        "-p",
        prompt,
        "--add-dir",
        project["path"],
        "--additional-mcp-config",
        f"@{config_path}",
        "--disable-builtin-mcps",
        "--no-ask-user",
    ]
    if mode == "agent":
        args.append("--allow-all-tools")
    try:
        completed = subprocess.run(
            [copilot_executable(), *args],
            cwd=project["path"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=1800,
            check=False,
        )
    except subprocess.TimeoutExpired as error:
        raise RuntimeError("Le modèle Copilot a dépassé le délai de 30 minutes.") from error
    finally:
        config_path.unlink(missing_ok=True)
    output = (completed.stdout or completed.stderr).strip()
    if completed.returncode != 0:
        raise RuntimeError(f"Copilot CLI a échoué ({completed.returncode}): {output[-1200:]}")
    if not output:
        raise RuntimeError("Copilot CLI n'a retourné aucune réponse.")
    return output, []


async def run_agent(
    project: dict[str, Any],
    model: str,
    messages: list[dict[str, Any]],
    mode: str,
) -> tuple[str, list[dict[str, Any]]]:
    if model.startswith("copilot:"):
        return await asyncio.to_thread(run_copilot_cli, project, model, messages, mode)
    server_paths = [
        REPO_ROOT / "agent" / "mcp" / "workspace_server.py",
        REPO_ROOT / "agent" / "mcp" / "unreal_server.py",
    ]
    tool_map: dict[str, tuple[ClientSession, Any]] = {}
    ollama_tools: list[dict[str, Any]] = []
    trace: list[dict[str, Any]] = []
    environment = os.environ.copy()
    environment["AGENT_WORKSPACE"] = project["path"]
    environment.setdefault("UNREAL_MCP_URL", "http://127.0.0.1:8000/mcp")

    async with AsyncExitStack() as stack:
        for server_path in server_paths:
            if not server_path.is_file():
                continue
            parameters = StdioServerParameters(
                command=sys.executable,
                args=[str(server_path)],
                env=environment,
            )
            read, write = await stack.enter_async_context(stdio_client(parameters))
            session = await stack.enter_async_context(ClientSession(read, write))
            await session.initialize()
            for tool in (await session.list_tools()).tools:
                if mode != "agent" and tool.name not in READ_ONLY_TOOLS:
                    continue
                if tool.name in tool_map:
                    continue
                tool_map[tool.name] = (session, tool)
                ollama_tools.append(
                    {
                        "type": "function",
                        "function": {
                            "name": tool.name,
                            "description": tool.description or "",
                            "parameters": tool.inputSchema,
                        },
                    }
                )

        if unreal_editor_online():
            try:
                read, write, _session_id = await stack.enter_async_context(
                    streamablehttp_client(
                        environment["UNREAL_MCP_URL"],
                        timeout=5,
                        sse_read_timeout=1800,
                    )
                )
                session = await stack.enter_async_context(ClientSession(read, write))
                await session.initialize()
                for tool in (await session.list_tools()).tools:
                    if tool.name in tool_map:
                        continue
                    tool_map[tool.name] = (session, tool)
                    ollama_tools.append(
                        {
                            "type": "function",
                            "function": {
                                "name": tool.name,
                                "description": tool.description or "",
                                "parameters": tool.inputSchema,
                            },
                        }
                    )
            except Exception:
                pass

        system_message = {
            "role": "system",
            "content": (
                "Tu es Laster, un agent de développement local précis et pragmatique. "
                f"Le projet actif est {project['name']} dans {project['path']}. "
                "Réponds en français sauf demande contraire. Utilise les outils pour vérifier les faits du projet. "
                "Ne prétends jamais avoir modifié ou exécuté quelque chose sans résultat d'outil. "
                + (
                    "Tu es en mode Agent: tu peux modifier les fichiers et exécuter les commandes utiles, "
                    "mais reste strictement dans le projet et évite toute opération destructive."
                    if mode == "agent"
                    else "Tu es en mode Chat: inspecte et conseille, sans modifier les fichiers ni lancer de compilation."
                )
            ),
        }
        dialogue = [system_message, *messages[-40:]]
        final_content = ""
        for _ in range(8):
            payload: dict[str, Any] = {
                "model": model,
                "messages": dialogue,
                "stream": False,
                "keep_alive": "30m",
                "options": {"num_ctx": 32768},
            }
            if ollama_tools:
                payload["tools"] = ollama_tools
            response = ollama_request("/api/chat", payload, timeout=1800)
            assistant = response.get("message", {})
            tool_calls = assistant.get("tool_calls") or []
            if not tool_calls:
                final_content = assistant.get("content", "").strip()
                break
            dialogue.append(assistant)
            for call in tool_calls:
                function = call.get("function", {})
                name = function.get("name", "")
                arguments = function.get("arguments") or {}
                if isinstance(arguments, str):
                    try:
                        arguments = json.loads(arguments)
                    except json.JSONDecodeError:
                        arguments = {}
                started = now_iso()
                if name not in tool_map:
                    output = f"Outil inconnu ou non autorisé dans ce mode: {name}"
                    is_error = True
                else:
                    session, _tool = tool_map[name]
                    try:
                        result = await session.call_tool(name, arguments)
                        output = "\n".join(
                            item.text
                            for item in result.content
                            if getattr(item, "type", None) == "text"
                        )
                        is_error = bool(result.isError)
                    except Exception as error:
                        output = f"Erreur d'outil: {error}"
                        is_error = True
                trace.append(
                    {
                        "name": name,
                        "arguments": arguments,
                        "result": output[:1200],
                        "isError": is_error,
                        "startedAt": started,
                    }
                )
                dialogue.append(
                    {"role": "tool", "tool_name": name, "content": output[:30000]}
                )
        if not final_content:
            final_content = "La limite d’itérations d’outils a été atteinte. Consulte la trace avant de relancer avec une demande plus ciblée."
        return final_content, trace


def adapt_prompt(project: dict[str, Any], target_model: str, prompt: str, intent: str) -> dict[str, Any]:
    models = list_models()
    adapter_model = select_adapter_model(models, target_model)
    response = ollama_request(
        "/api/chat",
        {
            "model": adapter_model,
            "stream": False,
            "keep_alive": "30m",
            "options": {"num_ctx": 8192, "temperature": 0.25},
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "Tu adaptes des prompts de développement. Retourne uniquement le prompt final, sans titre ni commentaire. "
                        "Préserve l'intention, rends les contraintes vérifiables, précise le résultat attendu et adapte la formulation "
                        "au modèle cible. Maximum strict: 200 mots. N'invente aucun fichier ni fait du projet."
                    ),
                },
                {
                    "role": "user",
                    "content": (
                        f"Projet: {project['name']}\nModèle cible: {target_model}\n"
                        f"Nouvelle intention du développeur: {intent or 'Aucune précision supplémentaire'}\n"
                        f"Prompt actuel:\n{prompt}"
                    ),
                },
            ],
        },
        timeout=600,
    )
    adapted = response.get("message", {}).get("content", "").strip()
    if not adapted:
        raise RuntimeError("Le modèle n'a retourné aucune adaptation.")
    words = adapted.split()
    if len(words) > 200:
        adapted = " ".join(words[:200])
    save_prompt(project["id"], prompt, "original")
    save_prompt(project["id"], adapted, "adapted")
    return {
        "prompt": adapted,
        "adapterModel": adapter_model,
        "targetModel": target_model,
        "estimatedCredits": 0,
        "budgetCredits": 200,
        "wordCount": len(adapted.split()),
    }


def unreal_editor_online() -> bool:
    request = urllib.request.Request(
        "http://127.0.0.1:8000/mcp",
        data=b'{"jsonrpc":"2.0","id":1,"method":"ping"}',
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=1):
            return True
    except urllib.error.HTTPError:
        return True
    except (urllib.error.URLError, TimeoutError):
        return False


def browse_for_project() -> str | None:
    try:
        import tkinter as tk
        from tkinter import filedialog

        root = tk.Tk()
        root.withdraw()
        root.attributes("-topmost", True)
        selected = filedialog.askdirectory(title="Choisir un projet pour Laster")
        root.destroy()
        return selected or None
    except Exception as error:
        raise RuntimeError(f"Le sélecteur Windows n'a pas pu s'ouvrir: {error}") from error


class LasterHandler(BaseHTTPRequestHandler):
    server_version = "Laster/1.0"

    def log_message(self, message_format: str, *args: Any) -> None:
        print(f"[{self.log_date_time_string()}] {message_format % args}")

    def read_json(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length", "0"))
        if length > 2_000_000:
            raise ValueError("Requête trop volumineuse.")
        raw = self.rfile.read(length) if length else b"{}"
        return json.loads(raw.decode("utf-8"))

    def send_json(self, payload: Any, status: int = 200) -> None:
        encoded = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(encoded)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(encoded)

    def send_error_json(self, error: Exception, status: int = 400) -> None:
        self.send_json({"error": str(error)}, status)

    def api_authorized(self) -> bool:
        if not ACCESS_TOKEN:
            return True
        provided = self.headers.get("X-Laster-Token", "")
        return hmac.compare_digest(provided, ACCESS_TOKEN)

    def do_GET(self) -> None:
        try:
            parsed = urlparse(self.path)
            if (
                parsed.path.startswith("/api/")
                and parsed.path != "/api/health"
                and not self.api_authorized()
            ):
                self.send_error_json(PermissionError("Jeton d’accès Laster invalide."), 401)
                return
            if parsed.path == "/api/bootstrap":
                project_id = active_project_id()
                projects = list_projects()
                models = list_models()
                if project_id and not any(project["id"] == project_id for project in projects):
                    project_id = projects[0]["id"] if projects else None
                self.send_json(
                    {
                        "projects": projects,
                        "activeProjectId": project_id,
                        "conversations": list_conversations(project_id) if project_id else [],
                        "models": models,
                        "status": {
                            "ollama": any(model["provider"] == "ollama" for model in models),
                            "copilot": any(
                                model["provider"] == "copilot" and model["available"]
                                for model in models
                            ),
                            "mcp": True,
                            "unrealEditor": unreal_editor_online(),
                        },
                        "launcherCommand": f"& '{REPO_ROOT / 'start-laster.ps1'}'",
                    }
                )
                return
            if parsed.path == "/api/conversations":
                project_id = parse_qs(parsed.query).get("project_id", [""])[0]
                self.send_json({"conversations": list_conversations(project_id)})
                return
            if parsed.path.startswith("/api/conversations/") and parsed.path.endswith("/messages"):
                conversation_id = parsed.path.split("/")[3]
                self.send_json({"messages": list_messages(conversation_id)})
                return
            if parsed.path == "/api/prompts":
                project_id = parse_qs(parsed.query).get("project_id", [""])[0]
                self.send_json({"prompts": list_prompts(project_id)})
                return
            if parsed.path == "/api/health":
                self.send_json(
                    {
                        "ok": True,
                        "ollama": bool(list_models()),
                        "copilot": bool(
                            os.environ.get("LASTER_COPILOT_PATH") or shutil.which("copilot")
                        ),
                        "unrealEditor": unreal_editor_online(),
                    }
                )
                return
            self.serve_static(parsed.path)
        except Exception as error:
            self.send_error_json(error, 500)

    def do_POST(self) -> None:
        try:
            parsed = urlparse(self.path)
            if not self.api_authorized():
                self.send_error_json(PermissionError("Jeton d’accès Laster invalide."), 401)
                return
            body = self.read_json()
            if parsed.path == "/api/projects":
                project = register_project(body.get("path", ""))
                set_active_project(project["id"])
                self.send_json({"project": project}, 201)
                return
            if parsed.path == "/api/projects/browse":
                selected = browse_for_project()
                if not selected:
                    self.send_json({"cancelled": True})
                    return
                project = register_project(selected)
                set_active_project(project["id"])
                self.send_json({"project": project}, 201)
                return
            if parsed.path == "/api/settings/project":
                set_active_project(body.get("projectId", ""))
                self.send_json({"ok": True})
                return
            if parsed.path == "/api/conversations":
                conversation = create_conversation(
                    body.get("projectId", ""),
                    body.get("model", ""),
                    body.get("title", "Nouvelle conversation"),
                )
                self.send_json({"conversation": conversation}, 201)
                return
            if parsed.path == "/api/prompts":
                save_prompt(body.get("projectId", ""), body.get("content", ""), body.get("source", "draft"))
                self.send_json({"ok": True}, 201)
                return
            if parsed.path == "/api/adapt":
                project = get_project(body.get("projectId", ""))
                result = adapt_prompt(
                    project,
                    body.get("targetModel", ""),
                    body.get("prompt", ""),
                    body.get("intent", ""),
                )
                self.send_json(result)
                return
            if parsed.path == "/api/chat":
                project = get_project(body.get("projectId", ""))
                conversation_id = body.get("conversationId", "")
                content = body.get("content", "").strip()
                if not content:
                    raise ValueError("Le message est vide.")
                user_message = add_message(conversation_id, "user", content)
                save_prompt(project["id"], content, "sent")
                history = [
                    {"role": message["role"], "content": message["content"]}
                    for message in list_messages(conversation_id)
                    if message["role"] in {"user", "assistant"}
                ]
                answer, trace = asyncio.run(
                    run_agent(
                        project,
                        body.get("model", ""),
                        history,
                        body.get("mode", "chat"),
                    )
                )
                assistant_message = add_message(
                    conversation_id,
                    "assistant",
                    answer,
                    {"tools": trace, "model": body.get("model", "")},
                )
                self.send_json(
                    {"userMessage": user_message, "assistantMessage": assistant_message}
                )
                return
            self.send_error_json(ValueError("Route inconnue."), 404)
        except ValueError as error:
            self.send_error_json(error, 400)
        except Exception as error:
            self.send_error_json(error, 500)

    def do_DELETE(self) -> None:
        try:
            parsed = urlparse(self.path)
            if not self.api_authorized():
                self.send_error_json(PermissionError("Jeton d’accès Laster invalide."), 401)
                return
            if parsed.path.startswith("/api/conversations/"):
                conversation_id = parsed.path.split("/")[3]
                with open_db() as connection:
                    connection.execute("DELETE FROM conversations WHERE id = ?", (conversation_id,))
                self.send_json({"ok": True})
                return
            self.send_error_json(ValueError("Route inconnue."), 404)
        except Exception as error:
            self.send_error_json(error, 500)

    def serve_static(self, request_path: str) -> None:
        if not DIST_ROOT.is_dir():
            self.send_error_json(
                RuntimeError("Interface non compilée. Exécutez npm run build dans laster."),
                503,
            )
            return
        relative = request_path.lstrip("/")
        candidate = (DIST_ROOT / relative).resolve()
        if request_path in {"/", "/laster"} or not candidate.is_file():
            candidate = DIST_ROOT / "index.html"
        if DIST_ROOT.resolve() not in candidate.resolve().parents and candidate.resolve() != DIST_ROOT.resolve():
            self.send_error_json(ValueError("Chemin statique invalide."), 403)
            return
        content = candidate.read_bytes()
        content_type = mimetypes.guess_type(candidate.name)[0] or "application/octet-stream"
        if candidate.suffix == ".js":
            content_type = "text/javascript"
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(content)))
        self.send_header("Cache-Control", "no-cache" if candidate.name == "index.html" else "public, max-age=31536000")
        self.end_headers()
        self.wfile.write(content)


def main() -> None:
    if HOST not in {"127.0.0.1", "localhost", "::1"} and not ACCESS_TOKEN:
        raise RuntimeError(
            "LASTER_ACCESS_TOKEN est requis lorsque Laster écoute sur le réseau."
        )
    init_db()
    server = ThreadingHTTPServer((HOST, PORT), LasterHandler)
    print(f"Laster prêt sur http://{HOST}:{PORT}/laster")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
