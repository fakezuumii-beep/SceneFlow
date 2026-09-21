@echo off
setlocal
cd /d "%~dp0.."
if exist ".venv\Scripts\python.exe" (
  ".venv\Scripts\python.exe" -m ai_morning_editor
) else (
  python -m ai_morning_editor
)
echo.
pause
