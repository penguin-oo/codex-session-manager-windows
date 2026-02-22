# Codex Session Manager for Windows

Desktop manager for Codex sessions on Windows: browse sessions, launch terminals with per-run options, and inspect MCP/Skills in one UI.

![Codex Session Manager UI](assets/ui-overview.png)

## Highlights
- Session list with details (`Time`, `Session ID`, `CWD`, `Model`, `Approval`, `Sandbox`)
- Open selected session in terminal with one click (supports admin + UTF-8 console setup)
- Built-in MCP tab and Skills tab with selectable row details
- Safe session deletion from local Codex history files
- UI quality improvements: adaptive columns, zebra rows, Ctrl+mouse-wheel zoom

## Run
```bat
D:\codex\manger\run.bat
```

Or:
```powershell
python D:\codex\manger\app.py
```

## Requirements
- Windows
- Python 3.11+ (Tkinter included in standard installer)

## Project Files
- `app.py`: main desktop application
- `run.bat`: launcher
- `assets/ui-overview.png`: UI screenshot
