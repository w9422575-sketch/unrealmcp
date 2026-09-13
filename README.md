# u - local Unreal MCP agent

A local development agent for Unreal Engine projects. It combines:

- Ollama with `gpt-oss:20b`
- GitHub Copilot CLI through the supported OpenAI-compatible provider
- Python MCP servers for workspace, Unreal, and editor access
- Laster, a local React and Python web interface

The repository is portable: MCP configuration is generated at runtime from the
current clone path and project path. No credentials or machine-specific paths
are committed.

## Requirements

- Windows and PowerShell
- Python 3.10 or newer
- Python package `mcp`
- Node.js and npm for the Laster interface
- Ollama with `gpt-oss:20b`
- GitHub Copilot CLI only when using Copilot models
- Unreal Engine 5.8 for the Unreal-specific tools

Install the Python dependency with:

```powershell
python -m pip install -r laster/requirements.txt
```

Install the frontend dependencies with:

```powershell
npm --prefix laster install
```

## Start the agent

Run the local Copilot CLI agent from the repository root:

```powershell
.\start-agent.ps1 -Check
.\start-agent.ps1
.\start-agent.ps1 -Prompt "Inspect the active project and report compilation risks."
```

Copy `agent/config/agent.env.example` to `agent/config/agent.env` to override
local settings. That file is ignored by Git.

## Start Laster

```powershell
.\start-laster.ps1
```

Open `http://127.0.0.1:4317/laster`. Laster can register an Unreal project and
run the workspace and Unreal MCP tools against it. Chat mode is read-only;
Agent mode enables the guarded write and command tools.

## MCP self-tests

```powershell
python agent/selftest_mcp.py agent/mcp/test_server.py
python agent/selftest_mcp.py agent/mcp/workspace_server.py
python agent/selftest_mcp.py agent/mcp/unreal_server.py
```

The workspace MCP server confines file operations to `AGENT_WORKSPACE` and
blocks destructive command patterns. The Unreal HTTP server is optional and
becomes available when the Unreal Editor MCP endpoint is running at
`http://127.0.0.1:8000/mcp`.
