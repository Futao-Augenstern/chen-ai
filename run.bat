@echo off
cd /d "%~dp0"

REM Try py launcher first (bypasses Microsoft Store alias)
where py >nul 2>&1
if %ERRORLEVEL% EQU 0 (
    echo [OK] Using py launcher...
    py main.py
    goto :end
)

REM Try python3
where python3 >nul 2>&1
if %ERRORLEVEL% EQU 0 (
    echo [OK] Using python3...
    python3 main.py
    goto :end
)

REM Try full path to common Python installations
for %%p in (
    "C:\Users\tx\AppData\Local\Programs\Python\Python313\python.exe"
    "C:\Users\tx\AppData\Local\Programs\Python\Python312\python.exe"
    "C:\Users\tx\AppData\Local\Programs\Python\Python311\python.exe"
    "C:\Python313\python.exe"
    "C:\Python312\python.exe"
    "C:\Python311\python.exe"
) do (
    if exist %%p (
        echo [OK] Using %%p
        %%p main.py
        goto :end
    )
)

REM Try python
where python >nul 2>&1
if %ERRORLEVEL% EQU 0 (
    python main.py
    goto :end
)

echo.
echo [ERROR] Python not found!
echo.
echo Please install Python from https://www.python.org/downloads/
echo OR disable Microsoft Store alias:
echo   Settings ^> Apps ^> Advanced app settings ^> App execution aliases
echo   Turn OFF "python.exe" and "python3.exe"
echo.

:end
pause