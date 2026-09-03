@echo off
setlocal EnableDelayedExpansion

echo ================================================================================
echo           TWORZENIE I KONFIGURACJA SRODOWISKA WIRTUALNEGO PYTHON (VENV)
echo                    DLA AI AUTOMATIC MONTAGE (RTX 3090 / CUDA)
echo ================================================================================
echo.

cd /d "%~dp0"

REM 1. Sprawdzenie Pythona
where python >nul 2>&1
if errorlevel 1 (
    echo BLAD: Python nie zostal znaleziony w systemie PATH.
    pause
    exit /b 1
)

echo Wykryto Python w systemie.
python --version
echo.

REM 2. Tworzenie venv
if not exist "venv" (
    echo Tworzenie srodowiska venv w katalogu "%~dp0venv"...
    python -m venv venv
    if errorlevel 1 (
        echo BLAD podczas tworzenia srodowiska venv.
        pause
        exit /b 1
    )
    echo Venv zostal utworzony pomyslnie.
) else (
    echo Srodowisko venv juz istnieje.
)
echo.

REM 3. Aktywacja i instalacja pakietow
echo Aktywacja venv...
call venv\Scripts\activate.bat

echo Aktualizacja pip...
python -m pip install --upgrade pip

echo.
echo ================================================================================
echo Instalacja bibliotek z requirements.txt oraz PyTorch CUDA dla RTX 3090...
echo ================================================================================
pip install torch torchvision --index-url https://download.pytorch.org/whl/cu124
pip install -r requirements.txt

echo.
echo ================================================================================
echo Weryfikacja instalacji i wsparcia CUDA...
echo ================================================================================
python -c "import torch; print('PyTorch Version:', torch.__version__, '| CUDA Dostepne:', torch.cuda.is_available(), '| GPU:', torch.cuda.get_device_name(0) if torch.cuda.is_available() else 'Brak CUDA')"

echo.
echo ================================================================================
echo                        KONFIGURACJA ZAKONCZONA POMYSLNIE!
echo   Mozesz teraz uruchamiac montaz poleceniem: run.bat all
echo ================================================================================
echo.
pause
