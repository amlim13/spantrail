@echo off
REM SpanTrail release launcher for Windows PowerShell / cmd.
REM
REM Why this exists: PowerShell 5.1 does not accept '&&' as a command
REM separator, and the Git Bash path contains spaces. This file handles
REM both correctly.
REM
REM It runs publish_all.sh in Git Bash, which asks for the PyPI token and
REM the Stripe live key in hidden fields. Neither is printed back.

setlocal

set "REPO=C:\claude projects\spantrail"
set "BASH=C:\Program Files\Git\bin\bash.exe"

if not exist "%BASH%" set "BASH=C:\Program Files\Git\usr\bin\bash.exe"

if not exist "%REPO%\publish_all.sh" (
  echo.
  echo   ERROR: %REPO%\publish_all.sh not found.
  echo   Restore the repository with:
  echo     git clone https://github.com/amlim13/spantrail.git "%REPO%"
  echo.
  exit /b 1
)

if not exist "%BASH%" (
  echo.
  echo   ERROR: Git Bash not found. Expected "%BASH%".
  echo   Install Git for Windows, or run publish_all.sh from Git Bash.
  echo.
  exit /b 1
)

echo.
echo   SpanTrail release
echo   =================
echo   1. PyPI API token  - https://pypi.org/manage/account/token/
echo   2. Stripe LIVE key - toggle the Stripe dashboard to Live mode, then
echo                        Developers -^> API keys -^> Reveal
echo.
echo   Both prompts are hidden. Nothing is echoed back.
echo.

cd /d "%REPO%"
"%BASH%" -lc "cd '/c/claude/projects/spantrail' && bash publish_all.sh"
set "RC=%ERRORLEVEL%"

echo.
if "%RC%"=="0" (
  echo   Release complete.
) else (
  echo   Release did not complete - exit code %RC%.
  echo   The PyPI and Stripe steps are independent; see which one stopped.
)
echo.

exit /b %RC%
