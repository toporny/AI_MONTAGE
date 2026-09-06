@echo off
chcp 65001 >nul
title AI Montage - Czyszczenie Projektu
echo ==============================================================================
echo       AI MONTAGE - CZYSZCZENIE PLIKOW TYMCZASOWYCH I WYNIKOWYCH
echo ==============================================================================
echo.
echo Ta operacja usunie zbedne pliki poprzedniego projektu:
echo   - Cache analizy wideo i muzyki (analysis/)
echo   - Storyboardy i projekty OpenShot (storyboard/)
echo   - Wyrenderowane podglady (preview/)
echo   - Wyrenderowane filmy koncowe 4K (output/)
echo   - Wyeksportowane klipy ujec (clips_480p/, clips_4k/)
echo   - Pliki dziennika (montage.log)
echo.
echo Twoje oryginalne materialy (kopie_robocze_480p, materialy_oryginalne,
echo sciezkadzwiekowa) NIE zostana usuniete!
echo.
set /p confirm="Czy na pewno chcesz wyczyscic projekt do zera? (T/N): "
if /i "%confirm%" neq "T" (
    echo Operacja anulowana.
    pause
    exit /b 0
)

echo.
echo Czyszczenie w toku...
.\venv\Scripts\python.exe main.py clean --yes
echo.
pause
