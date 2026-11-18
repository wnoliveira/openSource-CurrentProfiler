@echo off
setlocal
pushd "%~dp0"
if errorlevel 1 exit /b 1

rem Prefer the project interpreter; test it before reusing a copied/broken venv.
if not exist ".venv\Scripts\python.exe" goto local_python
".venv\Scripts\python.exe" -c "import struct,sys; sys.exit(not (sys.version_info[:2] == (3,12) and struct.calcsize('P') == 8))" >nul 2>&1
if errorlevel 1 goto local_python
set "BUILD_PYTHON=.venv\Scripts\python.exe"
goto build

:local_python
if not exist ".python312\python.exe" goto launcher
".python312\python.exe" -c "import struct,sys; sys.exit(not (sys.version_info[:2] == (3,12) and struct.calcsize('P') == 8))" >nul 2>&1
if errorlevel 1 goto launcher
set "BUILD_PYTHON=.python312\python.exe"
goto build

:launcher
py -3.12 -c "import struct,sys; sys.exit(struct.calcsize('P') != 8)" >nul 2>&1
if errorlevel 1 goto path_python
py -3.12 build_windows.py %*
set "BUILD_EXIT=%ERRORLEVEL%"
goto finished

:path_python
python -c "import struct,sys; sys.exit(not (sys.version_info[:2] == (3,12) and struct.calcsize('P') == 8))" >nul 2>&1
if errorlevel 1 goto fail
set "BUILD_PYTHON=python"

:build
"%BUILD_PYTHON%" build_windows.py %*
set "BUILD_EXIT=%ERRORLEVEL%"
goto finished

:fail
echo Python 3.12 de 64 bits nao encontrado. Instale-o ou restaure a pasta .python312.
set "BUILD_EXIT=1"

:finished
popd
if /i not "%~1"=="--no-pause" pause
exit /b %BUILD_EXIT%
