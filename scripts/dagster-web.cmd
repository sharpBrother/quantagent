@echo off
setlocal
cd /d "%~dp0.." || exit /b 1

if not defined DAGSTER_HOME set "DAGSTER_HOME=%CD%\var\dagster"
if not exist ".venv\Scripts\dagster-webserver.exe" (
    echo Dagster webserver is missing. Run: uv sync --all-extras --dev
    exit /b 1
)
if not exist "%DAGSTER_HOME%\dagster.yaml" (
    echo Missing Dagster configuration: "%DAGSTER_HOME%\dagster.yaml"
    echo Start the configured Dagster daemon first, or set DAGSTER_HOME.
    exit /b 1
)
if not exist "%DAGSTER_HOME%\workspace.yaml" (
    echo Missing Dagster workspace: "%DAGSTER_HOME%\workspace.yaml"
    echo Start the configured Dagster daemon first, or set DAGSTER_HOME.
    exit /b 1
)

echo Dagster home: %DAGSTER_HOME%
echo Dagster UI: http://127.0.0.1:3000/
echo Keep this window open while using the UI.
".venv\Scripts\dagster-webserver.exe" --host 127.0.0.1 --port 3000 --workspace "%DAGSTER_HOME%\workspace.yaml"
exit /b %ERRORLEVEL%
