@echo off
setlocal enabledelayedexpansion
cd /d "%~dp0"

REM =========================================================================
REM ArcGIS Data Lock Releaser Launcher
REM =========================================================================

REM 1. Custom Python executable path (leave blank for auto-detection)
set "PYTHON_EXE="

REM 2. Auto-detect pythonw.exe or python.exe from PATH
if "%PYTHON_EXE%"=="" (
    for /f "delims=" %%I in ('where pythonw.exe 2^>nul') do (
        if not defined PYTHON_EXE if exist "%%I" set "PYTHON_EXE=%%I"
    )
)

if "%PYTHON_EXE%"=="" (
    for /f "delims=" %%I in ('where python.exe 2^>nul') do (
        if not defined PYTHON_EXE (
            set "DIR=%%~dpI"
            if exist "!DIR!pythonw.exe" (
                set "PYTHON_EXE=!DIR!pythonw.exe"
            ) else (
                set "PYTHON_EXE=%%I"
            )
        )
    )
)

if "%PYTHON_EXE%"=="" (
    for /f "tokens=*" %%I in ('py -c "import sys; print(sys.executable)" 2^>nul') do (
        set "PYPATH=%%I"
        set "PYDIR=%%~dpI"
        if exist "!PYDIR!pythonw.exe" (
            set "PYTHON_EXE=!PYDIR!pythonw.exe"
        ) else (
            set "PYTHON_EXE=!PYPATH!"
        )
    )
)

if "%PYTHON_EXE%"=="" (
    echo [ERROR] No Python environment detected!
    echo Please install Python 3.8+ and ensure it is added to PATH.
    pause
    exit /b 1
)

REM Check Administrator privileges
net session >nul 2>&1
if %errorlevel% neq 0 (
    powershell -NoProfile -WindowStyle Hidden -Command "Start-Process '%PYTHON_EXE%' -ArgumentList '\"%~dp0gdb_lock_resolver.py\"' -Verb RunAs -WindowStyle Hidden"
    exit /b 0
)

REM Launch GUI application and exit CMD immediately
start "" "%PYTHON_EXE%" "%~dp0gdb_lock_resolver.py"
exit /b 0
