@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"

rem === ОТКАТ: вернуть оригинальные предметы ===
rem Окно закрывается само, если всё прошло без ошибок.

net session >nul 2>&1
if %errorlevel% neq 0 (
    powershell -NoProfile -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
    exit /b
)

where py >nul 2>&1
if %errorlevel% equ 0 (
    py te1_randomizer.py --restore
    if errorlevel 1 pause
    exit /b
)

where python >nul 2>&1
if %errorlevel% equ 0 (
    python te1_randomizer.py --restore
    if errorlevel 1 pause
    exit /b
)

echo.
echo  ! Python ne najden. Ustanoi s https://www.python.org/downloads/
echo    i pri ustanovke POSTAV' galochku "Add Python to PATH".
echo.
pause
