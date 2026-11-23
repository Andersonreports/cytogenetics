@echo off
rem Build dist\CMCCytogeneticsReport.exe (one file; opens the tool in the browser).
cd /d "%~dp0"
python -m PyInstaller build.spec --noconfirm --clean
if errorlevel 1 (
    echo Build failed.
    pause
    exit /b 1
)
echo.
echo Built: dist\CMCCytogeneticsReport.exe
