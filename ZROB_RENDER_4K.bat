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

if not exist "storyboard\storyboard.json" (
    echo.
    echo BLAD: Brak pliku storyboard\storyboard.json!
    echo Uruchom najpierw ZROB_PREVIEW.bat, aby wygenerowac storyboard i sprawdzic podglad.
    echo.
    pause
    exit /b 1
)

echo.
echo Uruchamianie finalnego renderu 4K / 60 FPS na podstawie istniejacego storyboard.json...
echo (Nie modyfikuje analizy muzyki ani storyboardu)
echo.
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
