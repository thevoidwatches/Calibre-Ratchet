@echo off
setlocal

rem Set Ratchet up, or change how it is set up.
rem
rem Double-click this. It installs the Python packages Ratchet needs into a
rem folder of its own (server\.venv - nothing is installed system-wide), then
rem opens the setup wizard in your browser. The wizard is a page served to
rem this PC only; this window is the program behind it, so leave it open
rem until you are done.
rem
rem It does not ask for administrator rights, and neither does the wizard.
rem Safe to run again at any time: it keeps what is already there.

set "SERVER_DIR=%~dp0server"
set "VENV_PY=%SERVER_DIR%\.venv\Scripts\python.exe"

echo.
echo   Ratchet setup
echo   -------------
echo.

if exist "%VENV_PY%" goto :packages

rem ---- find a Python new enough (3.11, for the TOML reader it ships with) ----
set "PY="
py -3 -c "import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)" >nul 2>&1
if not errorlevel 1 set "PY=py -3"
if not defined PY (
    python -c "import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)" >nul 2>&1
    if not errorlevel 1 set "PY=python"
)
if not defined PY (
    echo   Python 3.11 or newer is needed, and was not found.
    echo.
    echo   Get it from  https://www.python.org/downloads/
    echo   ^(tick "Add python.exe to PATH" in its installer^), then run this again.
    echo.
    echo   Or, from this window:   winget install Python.Python.3.12
    goto :failed
)

echo   Making Ratchet a Python environment of its own...
%PY% -m venv "%SERVER_DIR%\.venv"
if errorlevel 1 (
    echo.
    echo   That failed - the message above should say why.
    goto :failed
)

:packages
echo   Installing what Ratchet needs.  The first time takes a minute or two.
echo.
"%VENV_PY%" -m pip install --quiet --disable-pip-version-check -r "%SERVER_DIR%\requirements.txt"
if errorlevel 1 (
    echo.
    echo   The packages could not be installed - the message above should say
    echo   why.  Being offline is the usual reason.
    goto :failed
)

rem Cosmetic, so never fatal: makes Task Manager list the service as "Ratchet"
rem rather than "Python".
"%VENV_PY%" "%SERVER_DIR%\scripts\make_launcher_exe.py" >nul 2>&1

cd /d "%SERVER_DIR%"
"%VENV_PY%" -m ratchet.wizard
endlocal
exit /b 0

:failed
echo.
pause
endlocal
exit /b 1
