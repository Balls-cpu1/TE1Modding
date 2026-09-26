@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"

rem === ОТКАТ: вернуть оригинальные предметы ===

net session >nul 2>&1
if %errorlevel% neq 0 (
    echo.
    echo  Нужны права администратора - перезапускаюсь...
    echo.
    powershell -NoProfile -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
    exit /b
)

where py >nul 2>&1
if %errorlevel% equ 0 (
    py te1_randomizer.py --restore
    goto :end
)

where python >nul 2>&1
if %errorlevel% equ 0 (
    python te1_randomizer.py --restore
    goto :end
)

echo.
echo  ! Python не найден. Установи его с https://www.python.org/downloads/
echo    и при установке ОБЯЗАТЕЛЬНО поставь галочку "Add Python to PATH".
echo.

:end
echo.
pause
