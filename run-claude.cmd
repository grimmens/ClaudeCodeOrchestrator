@echo off
cd /d "%~dp0"
powershell -NoExit -Command "$env:CLAUDE_CODE_USE_POWERSHELL_TOOL='1'; claude --dangerously-skip-permissions"