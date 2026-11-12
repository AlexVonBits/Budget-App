@echo off
title Budget App - Build Setup
echo ============================================
echo  Budget App - one-time build
echo  This installs what it needs and creates
echo  Budget.exe. No typing required.
echo ============================================
echo.

where py >nul 2>nul
if %errorlevel%==0 (set PY=py) else (set PY=python)

echo [1/3] Installing requirements (one time)...
%PY% -m pip install --quiet flet flet-charts fpdf2 pyinstaller
if errorlevel 1 goto failed

echo [2/3] Building Budget.exe (takes a few minutes)...
%PY% -m flet.cli pack budget_app.py -n Budget -y
if errorlevel 1 goto failed

echo [3/3] Finishing up...
if exist Budget.exe del Budget.exe
copy /y dist\Budget.exe Budget.exe >nul
rd /s /q build 2>nul
rd /s /q dist 2>nul
if exist Budget.spec del Budget.spec

echo.
echo ============================================
echo  DONE! Double-click Budget.exe to use it.
echo  Your budget data saves to budget_data.json
echo  right next to the exe.
echo ============================================
pause
exit /b 0

:failed
echo.
echo Build failed - send the error text above to Zo.
pause
exit /b 1
