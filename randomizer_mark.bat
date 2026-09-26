@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"

rem === МЕТКА: проверка, читает ли игра файл ===
rem Меняет имена предметов местами. Если в игре названия перепутались -
rem файл читается и рандомайзер работает. Если обычные - не читается.
rem Ничего не портит: размер файла не меняется, имена возвращаются
rem через randomizer_restore.bat

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
    py te1_randomizer.py --mark
    goto :end
)

where python >nul 2>&1
if %errorlevel% equ 0 (
    python te1_randomizer.py --mark
    goto :end
)

echo.
echo  ! Python не найден. Установи его с https://www.python.org/downloads/
echo    и при установке ОБЯЗАТЕЛЬНО поставь галочку "Add Python to PATH".
echo.

:end
echo.
pause
