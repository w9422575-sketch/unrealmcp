# Laster

Interface web locale pour piloter Ollama et les outils MCP du projet Unreal sans compte externe.

## Démarrage

Depuis la racine du projet :

```powershell
.\start-laster.ps1
```

L'interface compilée est servie sur `http://127.0.0.1:4317/laster`. Le lanceur démarre Ollama si nécessaire, vérifie `gpt-oss:20b`, puis ouvre le navigateur.

Options utiles :

```powershell
.\start-laster.ps1 -Rebuild
.\start-laster.ps1 -Port 4400
.\start-laster.ps1 -NoBrowser
.\start-laster.ps1 -Mobile
```

Le mode `-Mobile` affiche une URL privée à ouvrir dans Safari sur un iPhone
connecté au même réseau Wi-Fi. Le jeton de l’URL protège les API capables de
piloter le MCP. Dans Safari, **Partager > Sur l’écran d’accueil** installe
Laster comme une web app plein écran.

## Développement

```powershell
npm install
npm run build
npm run lint
```

Le backend Python utilise `mcp`, `sqlite3` et la bibliothèque standard. Les données utilisateur sont conservées dans `laster/data/laster.db`, ignoré par Git.

## Architecture

- React + TypeScript : chat, modèles, projets, historique et guide en sept étapes.
- Python local : API HTTP, SQLite, Ollama et boucle d'outils.
- MCP stdio : fichiers, Git, terminal et opérations Unreal hors ligne.
- MCP HTTP Epic : outils de la scène Unreal ouverte sur `127.0.0.1:8000`.
- Ollama : modèles locaux uniquement, sans compte ni crédit externe.

Le sélecteur de modèles contient deux groupes : **Ollama local** et **GitHub
Copilot**. Le catalogue Copilot complet est découvert depuis la version du CLI
installée, au lieu d’être limité à une liste codée en dur. Les modèles Copilot
sont appelés avec `copilot --model` et utilisent la session Copilot CLI déjà
connectée. Les modèles locaux restent disponibles si le CLI Copilot n'est pas
installé.

Le mode **Chat** limite les outils à la lecture. Le mode **Agent** autorise les écritures et commandes protégées par les règles du serveur workspace.
