@echo off
setlocal
cd /d "%~dp0"
if exist .venv\Scripts\python.exe goto dependencies
if exist .python312\python.exe (
    .python312\python.exe -m venv .venv
    goto created
)
py -3.12 -m venv .venv
:created
if errorlevel 1 goto fail
:dependencies
.venv\Scripts\python.exe -c "import PySide6, pyqtgraph, numpy, serial" >nul 2>&1
if not errorlevel 1 goto run
.venv\Scripts\python.exe -m pip install -r requirements.txt
if errorlevel 1 goto fail
:run
.venv\Scripts\python.exe main.py %*
if errorlevel 1 goto fail
exit /b 0
:fail
echo Confira Python 3.12 x64, dependencias e as mensagens acima.
pause
exit /b 1
