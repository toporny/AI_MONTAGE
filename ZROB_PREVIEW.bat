@echo off
setlocal

cd /d "%~dp0"

echo.
echo ============================================================
echo   AI MONTAGE -- PREVIEW 480p
echo ============================================================
echo.

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
echo [4/4] Renderowanie preview 480p...
python main.py preview
if errorlevel 1 (
    echo.
    echo BLAD: Nie udalo sie wyrenderowac preview!
    pause
    exit /b 1
)

echo.
echo ============================================================
echo   PREVIEW GOTOWY!
echo   Plik: preview\preview_montage_480p.mp4
echo ============================================================
echo.

pause
