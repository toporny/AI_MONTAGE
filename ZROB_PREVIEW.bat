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

echo [1/5] Synchronizacja proxy 480p z oryginalami...
python sync_proxies.py
if errorlevel 1 (
    echo.
    echo BLAD: Synchronizacja proxy nie powiodla sie!
    pause
    exit /b 1
)

echo.
echo [2/5] Analiza klipow (aktualizacja JSON)...
python main.py analyze
if errorlevel 1 (
    echo.
    echo BLAD: Analiza klipow nie powiodla sie!
    pause
    exit /b 1
)

echo.
echo [3/5] Analiza muzyki i rytmu (music_analysis.json)...
python main.py analyze-music
if errorlevel 1 (
    echo.
    echo BLAD: Analiza muzyki nie powiodla sie!
    pause
    exit /b 1
)

echo.
echo [4/5] Generowanie storyboardu...
python main.py create-storyboard
if errorlevel 1 (
    echo.
    echo BLAD: Nie udalo sie wygenerowac storyboardu!
    pause
    exit /b 1
)

echo.
echo [5/5] Renderowanie preview 480p...
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
echo   Plik wideo:        preview\preview_montage_480p.mp4
echo   OpenShot (4K):     storyboard\montage_openshot_4K.osp
echo   OpenShot (480p):   storyboard\montage_openshot_480p.osp
echo ============================================================
echo.

pause
