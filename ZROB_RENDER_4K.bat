@echo off
setlocal

cd /d "%~dp0"

echo.
echo ============================================================
echo   AI MONTAGE -- FINALNY RENDER 4K / 60 FPS  (NVENC / CPU)
echo ============================================================
echo.
echo   Szacowany czas: ~5-15 minut (zaleznie od karty GPU / CPU)
echo   Plik wyjsciowy: output\final_montage_4K60.mp4
echo.
echo   Nacisnij dowolny klawisz aby rozpoczac...
pause >nul

if not exist "venv\Scripts\activate.bat" (
    echo BLAD: Srodowisko venv nie istnieje.
    echo Uruchom najpierw setup_venv.bat
    pause
    exit /b 1
)

call venv\Scripts\activate.bat

echo [1/4] Synchronizacja proxy 480p z oryginalami...
python sync_proxies.py
if errorlevel 1 (
    echo.
    echo BLAD: Synchronizacja proxy nie powiodla sie!
    pause
    exit /b 1
)

echo.
echo [2/4] Analiza klipow (aktualizacja JSON)...
python main.py analyze
if errorlevel 1 (
    echo.
    echo BLAD: Analiza klipow nie powiodla sie!
    pause
    exit /b 1
)

echo.
echo [3/4] Generowanie storyboardu...
python main.py create-storyboard
if errorlevel 1 (
    echo.
    echo BLAD: Nie udalo sie wygenerowac storyboardu!
    pause
    exit /b 1
)

echo.
echo [4/4] Finalny render 4K / 60 FPS (NVIDIA NVENC)...
python main.py render
if errorlevel 1 (
    echo.
    echo BLAD: Nie udalo sie wyrenderowac finalnego filmu!
    pause
    exit /b 1
)

echo.
echo ============================================================
echo   RENDER GOTOWY!
echo   Plik: output\final_montage_4K60.mp4
echo ============================================================
echo.

pause
