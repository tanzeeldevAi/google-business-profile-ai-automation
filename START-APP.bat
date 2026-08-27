@echo off
REM Starts both halves of the web app and opens it.
REM   API   http://127.0.0.1:8790   Python, does the work
REM   UI    http://localhost:3000   Next.js, what you look at
cd /d "%~dp0"

where node >nul 2>&1 || (
  echo Node.js is not installed. Get it from https://nodejs.org
  pause & exit /b 1
)

if not exist "app\node_modules" (
  echo Installing the app's dependencies, one time only...
  pushd app && call npm install && popd
)

echo Starting the API on 127.0.0.1:8790 ...
start "GBP Autopilot API" cmd /c "python -m uvicorn api.main:app --host 127.0.0.1 --port 8790"

echo Starting the app on localhost:3000 ...
start "GBP Autopilot UI" cmd /c "cd app && npm run dev"

echo.
echo   Opening http://localhost:3000
echo   Close the two windows this opened to stop it.
echo.
timeout /t 12 /nobreak >nul
start "" http://localhost:3000
