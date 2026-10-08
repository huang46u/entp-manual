@echo off
setlocal
cd /d "%~dp0"
call "%~dp0workspace-env.cmd"
if not exist ".venv\Scripts\python.exe" (
  python -m venv .venv
  if errorlevel 1 exit /b 1
)
".venv\Scripts\python.exe" -m pip install -r requirements-flet.txt
if errorlevel 1 exit /b 1
".venv\Scripts\python.exe" -c "from workspace_runtime import configure_workspace; configure_workspace(); import flet_desktop; print(flet_desktop.ensure_client_cached())"
if errorlevel 1 exit /b 1
".venv\Scripts\python.exe" -m pip check
exit /b %ERRORLEVEL%
