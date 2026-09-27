@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"

rem === РАНДОМИЗАЦИЯ ===
rem Открыл - перетасовалось - закрылось. Окно закрывается само.
rem Хочешь другой набор - открой ещё раз.
rem Вернуть оригинал - restore.bat

net session >nul 2>&1
if %errorlevel% neq 0 (
    powershell -NoProfile -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
    exit /b
)

where py >nul 2>&1
if %errorlevel% equ 0 (
    py te1_randomizer.py --quick
    if errorlevel 1 pause
    exit /b
)

where python >nul 2>&1
if %errorlevel% equ 0 (
    python te1_randomizer.py --quick
    if errorlevel 1 pause
    exit /b
)

echo.
echo  ! Python ne najden. Ustanoi s https://www.python.org/downloads/
echo    i pri ustanovke POSTAV' galochku "Add Python to PATH".
echo.
pause
