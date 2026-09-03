@echo off
setlocal

cd /d "%~dp0"

if not exist "venv\Scripts\activate.bat" (
    echo BLAD: Srodowisko wirtualne VENV nie istnieje.
    echo Uruchom najpierw setup_venv.bat, aby utworzyc srodowisko.
    pause
    exit /b 1
)

call venv\Scripts\activate.bat

:: Komendy pomocnicze obslugiwane bezposrednio przez skrypty Python
if "%~1"=="sync-proxies" (
    python sync_proxies.py %2 %3 %4 %5
    goto :end
)
if "%~1"=="export-clips" (
    python export_clips.py %2 %3 %4 %5
    goto :end
)

:: Wszystkie pozostale komendy trafiaja do main.py
python main.py %*

:end
