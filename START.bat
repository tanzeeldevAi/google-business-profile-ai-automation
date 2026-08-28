@echo off
REM ===========================================================================
REM  GBP Autopilot -- the only file you need to start it.
REM
REM    API   http://127.0.0.1:8790   Python, does the work
REM    App   http://localhost:3000   what you look at
REM
REM  Everything the tool does lives in the app. The command line still works
REM  if you want it: python run.py audit, python run.py fix, and so on.
REM ===========================================================================
setlocal
title GBP Autopilot
cd /d "%~dp0"

set "PY="
if exist ".venv\Scripts\python.exe" set "PY=.venv\Scripts\python.exe"
if not defined PY (where python >nul 2>&1 && set "PY=python")
if not defined PY (where py >nul 2>&1 && set "PY=py")
if not defined PY (
    echo.
    echo   Python was not found.
    echo   Install it from https://python.org and tick "Add Python to PATH".
    echo.
    pause & exit /b 1
)

where node >nul 2>&1 || (
    echo.
    echo   Node.js was not found. Get it from https://nodejs.org
    echo.
    pause & exit /b 1
)

if not exist "app\node_modules" (
    echo   Installing the app's dependencies. This happens once and takes a few minutes...
    pushd app && call npm install && popd
)

REM A production build and the dev server share the app\.next folder, and the
REM dev server cannot read a production one -- it fails with "Cannot find
REM module ./627.js", which looks like broken code and is not. BUILD_ID only
REM exists in a production build, so it is the reliable tell.
if exist "app\.next\BUILD_ID" (
    echo   Clearing a stale production build so the app can start...
    rmdir /s /q "app\.next"
)

REM Free the ports if a previous run was closed with the X rather than Ctrl+C,
REM otherwise the new server silently loses the port to the old one.
for /f "tokens=5" %%p in ('netstat -ano ^| findstr ":8790 .*LISTENING"') do taskkill /f /pid %%p >nul 2>&1
for /f "tokens=5" %%p in ('netstat -ano ^| findstr ":3000 .*LISTENING"') do taskkill /f /pid %%p >nul 2>&1

echo.
echo   Starting...
start "GBP Autopilot API" /min cmd /c ""%PY%" -m uvicorn api.main:app --host 127.0.0.1 --port 8790"
start "GBP Autopilot App" /min cmd /c "cd app && npm run dev"

REM Wait for the app to answer rather than guessing at a fixed delay -- a cold
REM first compile takes far longer than a warm one.
echo   Waiting for it to come up...
set /a tries=0
:wait
set /a tries+=1
if %tries% gtr 90 (
    echo.
    echo   It is taking longer than expected. Open http://localhost:3000 yourself,
    echo   or look at the two windows this opened for the reason.
    echo.
    pause & exit /b 1
)
timeout /t 1 /nobreak >nul
curl -s -o nul http://localhost:3000 || goto wait

echo.
echo   Ready:  http://localhost:3000
echo.
echo   Close the two minimised windows to stop it.
echo.
start "" http://localhost:3000
