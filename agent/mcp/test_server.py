"""
MCP minimal de validation - PHASE 6
====================================
Objectif unique : prouver que le tool calling fonctionne reellement
entre Copilot CLI, gpt-oss:20b (via Ollama) et un serveur MCP.

Transport : stdio (le mode utilise par Copilot CLI)
Dependance : paquet `mcp` (SDK officiel), deja present.

Aucun effet de bord, aucune ecriture disque, aucune commande systeme.
"""

from mcp.server.fastmcp import FastMCP

mcp = FastMCP("agent-test")


@mcp.tool()
def test_tool() -> str:
    """Outil de validation de la chaine MCP.

    Retourne systematiquement la valeur sentinelle MCP_TEST_OK.
    Appelle cet outil quand on te demande de verifier que MCP fonctionne.
    """
    return "MCP_TEST_OK"


@mcp.tool()
def echo(message: str) -> str:
    """Renvoie le message recu prefixe par ECHO:.

    Sert a verifier que les arguments sont correctement transmis
    du modele vers le serveur MCP.

    Args:
        message: Le texte a renvoyer.
    """
    return f"ECHO:{message}"


@mcp.tool()
def add_numbers(a: float, b: float) -> float:
    """Additionne deux nombres.

    Sert a verifier le typage des arguments (nombres, pas chaines).

    Args:
        a: Premier nombre.
        b: Second nombre.
    """
    return a + b


if __name__ == "__main__":
    mcp.run(transport="stdio")
