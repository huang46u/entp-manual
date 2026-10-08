@echo off
setlocal
cd /d "%~dp0"
call "%~dp0workspace-env.cmd"
if not exist ".venv\Scripts\pythonw.exe" (
  echo Project runtime is missing. See LOCAL_DEPLOYMENT.md.
  pause
  exit /b 1
)
start "" ".venv\Scripts\pythonw.exe" "launcher_flet.pyw" %*
exit /b 0
