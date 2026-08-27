@echo off
setlocal enabledelayedexpansion
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
    pause
    exit /b 1
)

:menu
cls
echo.
echo   ==========================================
echo     GBP AUTOPILOT
echo   ==========================================
echo.
echo     1.  Audit the profile   (writes a report)
echo     2.  What changed        (watch)
echo     3.  Show fixes          (nothing is written)
echo     4.  APPLY fixes
echo     5.  Draft review replies
echo     6.  SEND review replies
echo     7.  Draft a post
echo     8.  PUBLISH a post
echo.
echo     9.  Check setup         (doctor)
echo     0.  Sign in to Google
echo.
echo     Q.  Quit
echo.
set "choice="
set /p choice="   Choose [1]: "
if not defined choice set choice=1

if /i "%choice%"=="1" ("%PY%" run.py audit & goto done)
if /i "%choice%"=="2" ("%PY%" run.py watch & goto done)
if /i "%choice%"=="3" ("%PY%" run.py fix & goto done)
if /i "%choice%"=="4" goto applyfix
if /i "%choice%"=="5" ("%PY%" run.py reviews & goto done)
if /i "%choice%"=="6" goto sendreplies
if /i "%choice%"=="7" ("%PY%" run.py post & goto done)
if /i "%choice%"=="8" goto publishpost
if /i "%choice%"=="9" ("%PY%" run.py doctor & goto done)
if /i "%choice%"=="0" ("%PY%" run.py login & goto done)
if /i "%choice%"=="Q" exit /b 0
goto menu

:applyfix
echo.
echo   This WRITES to the live Google profile.
set /p sure="   Type YES to continue: "
if /i not "%sure%"=="YES" goto menu
"%PY%" run.py fix --apply
goto done

:sendreplies
echo.
echo   This POSTS replies publicly on Google.
set /p sure="   Type YES to continue: "
if /i not "%sure%"=="YES" goto menu
"%PY%" run.py reviews --apply
goto done

:publishpost
echo.
echo   This PUBLISHES a post on the live Google profile.
set /p sure="   Type YES to continue: "
if /i not "%sure%"=="YES" goto menu
"%PY%" run.py post --apply
goto done

:done
echo.
pause
goto menu
