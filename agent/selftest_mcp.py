"""
Auto-test d'un serveur MCP stdio.
=================================
Lance un serveur MCP local, liste ses outils et appelle ceux demandes.
Sert a valider CHAQUE couche MCP independamment du modele,
avant de tester le tool calling via Copilot CLI + gpt-oss:20b.

Usage :
    python agent/selftest_mcp.py agent/mcp/test_server.py
    python agent/selftest_mcp.py agent/mcp/test_server.py test_tool
"""

import asyncio
import json
import sys
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


async def run(server_path: str, calls: list[tuple[str, dict, bool]]) -> int:
    params = StdioServerParameters(
        command=sys.executable,
        args=[str(Path(server_path).resolve())],
        env=None,
    )
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            init = await session.initialize()
            print(f"[OK]   Handshake MCP -> {init.serverInfo.name} v{init.serverInfo.version}")

            tools = (await session.list_tools()).tools
            print(f"[OK]   {len(tools)} outil(s) expose(s) :")
            for t in tools:
                first_line = (t.description or "").strip().splitlines()
                desc = first_line[0] if first_line else ""
                print(f"         - {t.name}: {desc}")

            failures = 0
            for name, args, must_fail in calls:
                label = "REFUS ATTENDU" if must_fail else "call"
                try:
                    res = await session.call_tool(name, args)
                    payload = "".join(
                        c.text for c in res.content if getattr(c, "type", None) == "text"
                    )
                    ok = res.isError if must_fail else not res.isError
                except Exception as exc:  # noqa: BLE001
                    payload, ok = f"exception: {exc}", must_fail
                if not ok:
                    failures += 1
                status = "OK" if ok else "FAIL"
                print(f"[{status}] {label} {name}({json.dumps(args)}) -> {payload[:400]}")
            return failures


def main() -> int:
    if len(sys.argv) < 2:
        print("usage: python selftest_mcp.py <server.py> [tool_name ...]")
        return 2

    server = sys.argv[1]
    requested = sys.argv[2:]

    # Scenarios de validation par serveur.
    # Chaque entree : (nom_outil, arguments, doit_echouer)
    presets: dict[str, list[tuple[str, dict, bool]]] = {
        "test_server.py": [
            ("test_tool", {}, False),
            ("echo", {"message": "hello"}, False),
            ("add_numbers", {"a": 21, "b": 21}, False),
        ],
        "workspace_server.py": [
            ("ws_info", {}, False),
            ("list_dir", {"path": "."}, False),
            ("find_files", {"pattern": "*.uproject"}, False),
            ("read_file", {"path": "onepiece.uproject", "start_line": 1, "end_line": 5}, False),
            ("search_text", {"pattern": "GameplayStateTree", "file_glob": "*.uproject"}, False),
            ("git_status", {}, False),
            ("git_log", {"max_count": 3}, False),
            ("run_powershell", {"command": "Write-Output SHELL_OK"}, False),
            # Controles de securite (phase 11) : ces appels DOIVENT etre refuses.
            ("read_file", {"path": "..\\..\\..\\..\\Windows\\win.ini"}, True),
            ("run_powershell", {"command": "Remove-Item C:\\ -Recurse -Force"}, True),
            ("run_powershell", {"command": "git reset --hard HEAD~5"}, True),
            ("write_file", {"path": "C:\\Windows\\pwned.txt", "content": "x"}, True),
        ],
        "unreal_server.py": [
            ("unreal_get_project_info", {}, False),
            ("unreal_list_engine_versions", {}, False),
            ("unreal_get_output_log", {"lines": 5}, False),
        ],
    }

    name = Path(server).name
    calls = [(n, {}, False) for n in requested] if requested else presets.get(name, [])
    if not calls:
        print(f"[WARN] aucun scenario predefini pour {name}; liste des outils uniquement.")

    failures = asyncio.run(run(server, calls))
    print()
    print("RESULTAT : [OK] tous les appels ont reussi" if failures == 0
          else f"RESULTAT : [FAIL] {failures} appel(s) en echec")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
