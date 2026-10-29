@echo off
rem One-command start for Windows: double-click start.bat (or run it from a terminal).
rem First run creates .\venv and installs the Python packages; later runs start straight away.
setlocal
cd /d "%~dp0"
if "%PORT%"=="" set PORT=8000

if not exist venv\Scripts\python.exe (
  echo Creating a virtual environment...
  py -3 -m venv venv 2>nul || python -m venv venv
  if not exist venv\Scripts\python.exe (
    echo.
    echo Python 3.11 or newer is needed. Install it from https://www.python.org/downloads/
    echo and tick "Add python.exe to PATH" during setup. Then run start.bat again.
    pause
    exit /b 1
  )
)

rem re-install packages only when requirements.txt changes
for /f %%h in ('certutil -hashfile requirements.txt SHA1 ^| findstr /v ":"') do set WANT=%%h
set HAVE=
if exist venv\.requirements.sha set /p HAVE=<venv\.requirements.sha
if not "%HAVE%"=="%WANT%" (
  echo Installing Python packages ^(first run takes a few minutes^)...
  venv\Scripts\python -m pip install --upgrade pip >nul
  venv\Scripts\python -m pip install -r requirements.txt || (pause & exit /b 1)
  > venv\.requirements.sha echo %WANT%
)

echo.
echo Starting MoMo Fraud Detection on http://localhost:%PORT%  (press Ctrl+C to stop)
if not "%NO_BROWSER%"=="1" start "" /b cmd /c "timeout /t 3 >nul & start http://localhost:%PORT%"
venv\Scripts\python -m uvicorn backend.main:app --host 127.0.0.1 --port %PORT%
