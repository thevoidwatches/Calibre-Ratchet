@echo off
setlocal

rem Start the Ratchet service.
rem
rem Double-click it, or run it from any directory - paths are resolved relative
rem to this file, not to the current one.
rem
rem For Task Scheduler, pass /noprompt so a failure exits instead of waiting at
rem a "Press any key" nobody is there to press:
rem     run.bat /noprompt

set "SERVER_DIR=%~dp0ficsync\server"
set "VENV_PY=%SERVER_DIR%\.venv\Scripts\python.exe"

if not exist "%VENV_PY%" (
    echo ERROR: no virtual environment found at
    echo     %VENV_PY%
    echo.
    echo Create it once with:
    echo     cd /d "%SERVER_DIR%"
    echo     python -m venv .venv
    echo     .venv\Scripts\python.exe -m pip install -r requirements.txt
    goto :failed
)

if not exist "%SERVER_DIR%\config.toml" (
    echo ERROR: config.toml is missing from
    echo     %SERVER_DIR%
    echo.
    echo Copy the template and edit it:
    echo     copy config.example.toml config.toml
    echo.
    echo Secrets ^(calibre login, API token^) belong in a .env file beside it.
    goto :failed
)

rem Run from the server directory: the service looks for config.toml in the
rem working directory, and reads .env from alongside that file.
cd /d "%SERVER_DIR%"

echo Starting Ratchet.  Close this window or press Ctrl+C to stop it.
echo.
"%VENV_PY%" -m ficsync
if errorlevel 1 (
    echo.
    echo Ratchet stopped with an error.
    echo.
    echo Common causes:
    echo   - Tailscale is not connected, so host = "tailscale" cannot resolve.
    echo   - Port 8484 is already in use, i.e. Ratchet is already running.
    echo   - config.toml or .env is incomplete.
    goto :failed
)

endlocal
exit /b 0

:failed
rem Keep the window open when someone is watching, so the message can be read.
if /i not "%~1"=="/noprompt" pause
endlocal
exit /b 1
