# AI Automatic Music Montage (Windows / GPU NVENC / CPU Fallback)

W pełni lokalny, inteligentny system w języku Python (uruchamiany w odizolowanym środowisku **VENV**) do profesjonalnego montażu filmowego synchronizowanego z podkładem muzycznym. Program automatycznie wykrywa wszystkie klipy wideo w katalogu - możesz wgrać dowolną liczbę nagrań z dowolnego wydarzenia (urodziny, wesele, koncert, konferencja, wyjazd integracyjny itp.).

---

## ⚡ Szybki start w pigułce

### 1. Gdzie wgrać materiały?
Wszystkie pliki wejściowe umieszczasz bezpośrednio w podkatalogach wewnątrz folderu `AI_MONTAGE/`:

* 🎬 **Oryginalne nagrania wideo (4K/HD):** wrzuć do `materialy_oryginalne/` (formaty `.mp4`, `.mov`, `.mkv` itp.)
* 🎵 **Podkład muzyczny:** wrzuć plik audio (np. `.mp3`) do `sciezkadzwiekowa/`
* 🖼️ *(Opcjonalnie)* **Statyczny obraz końcowy (outro):** np. plansza z logo/napisem JPG/PNG w folderze `outro_image/outro.jpg` lub w dowolnym innym miejscu wskazanym w `config.yaml`

> [!TIP]
> Nie musisz ręcznie przygotowywać plików o małej rozdzielczości - program przy pierwszym uruchomieniu sam utworzy lekkie kopie robocze 480p w folderze `kopie_robocze_480p/`, aby błyskawicznie przeanalizować obraz pod kątem AI!

### 2. Jak odpalać?
Do dyspozycji masz wygodne, gotowe skrypty `.bat` (uruchamiane dwuklikiem):

* 🚀 **`ZROB_PREVIEW.bat`** - wykonuje pełną automatyczną procedurę w 4 krokach:
  1. *Synchronizacja* kopii roboczych 480p z nowo dodanymi nagraniami
  2. *Analiza wideo i audio* (wykrywanie twarzy, ostrości, ruchu, rytmu i dropów w muzyce)
  3. *Generowanie storyboardu* (harmonogramu cięć)
  4. *Render roboczy 480p* (`preview/preview_montage_480p.mp4`) trwający zaledwie **~25–30 sekund**!
* 💎 **`ZROB_RENDER_4K.bat`** - po obejrzeniu i zaakceptowaniu podglądu, ten skrypt generuje docelowy film w pełnej jakości master **4K / 60 FPS** z kodowaniem sprzętowym GPU (NVIDIA NVENC, AMD AMF, Intel QSV lub CPU).
* 🧹 **`WYCZYSC_PROJEKT.bat`** - bezpiecznie usuwa pliki tymczasowe, cache i rendery poprzedniego projektu, czyszcząc foldery robocze do zera przed rozpoczęciem montażu nowego filmu.
* 🛠️ **`run.bat [komenda]`** - konsolowy dostęp do pojedynczych poleceń (`preview`, `render`, `analyze`, `sync-proxies`, `export-clips`, `clean`, `hardware`).

### 3. Jakie są możliwości konfiguracji (`config.yaml`)?
Wszystkimi aspektami montażu sterujesz z poziomu przejrzystego pliku konfiguracyjnego `config.yaml`:
* **Wybór utworu (`music_file`):** precyzyjnie wskazujesz nazwę pliku MP3 z folderu `sciezkadzwiekowa/` (wymagane ścisłe dopasowanie).
* **Wymuszone ujęcia (`forced_clips`):** zdefiniuj klipy, które **muszą** pojawić się w filmie, opcjonalnie podając dokładny moment rozpoczęcia (`clip_time_start`) lub zakończenia (`clip_time_end`).
* **Wagi scoringu sztucznej inteligencji:** zdecyduj, co jest ważniejsze w doborze ujęć - obecność ludzi i twarzy, dynamika ruchu (Optical Flow), czy perfekcyjna ostrość kadru.
* **Dynamika cięć:** ustaw minimalny czas ujęcia (domyślnie bezpieczne `1.20s`, zapobiegające efektowi stroboskopu) oraz częstotliwość cięć w zależności od energii muzyki (cięcie co 1, 2 lub 3 takty).
* **Ścisła chronologia:** włącz/wyłącz monotoniczne prowadzenie narracji na osi czasu.
* **Zakończenie filmu (Outro):** wybór pomiędzy statyczną planszą graficzną a wideo kończącym film (np. odjazd samochodu).
* **Jakość renderingu:** ustawienia rozdzielczości (4K/1080p), klatkażu (60/30 fps), bitrate audio oraz profili kodowania NVENC.

### 4. Co można dzięki temu osiągnąć?
* ⏱️ **Oszczędność kilkunastu godzin ręcznego montażu:** zamiast przeglądać setki plików i ręcznie ciąć je na osi czasu pod rytm perkusji, AI robi to automatycznie.
* 🎵 **Montaż idealnie pod rytm:** cięcia wypadają dokładnie na beatach i dropach utworu muzycznego.
* 🎯 **Tylko najlepsze momenty:** algorytmy eliminują nieostre, prześwietlone lub trzęsące się ujęcia, eksponując dobrze skadrowane osoby i dynamiczne akcje.
* 📖 **Logiczna i spójna historia:** film rozwija się chronologicznie od początku imprezy do jej finału.

## 🚀 Architektura i Zasada Działania

Program działa jak profesjonalny montażysta filmowy, realizując montaż w 6 etapach:

1. **Etap 1: Błyskawiczna analiza proxy (480p / 15 fps)**
   - **Ostrość i blur:** wariancja Laplasjana, ocena motion blur.
   - **Ekspozycja:** wykrywanie prześwietleń (>245 luma) i niedoświetleń (<15 luma), dynamika tonalna.
   - **Stabilność kadru:** estymacja ruchu afinicznego i eliminacja przypadkowych szarpnięć kamerą.
   - **Detekcja ludzi (YOLO):** liczba osób, wielkość postaci w kadrze, wyśrodkowanie, klasyfikacja planów (*Close-up, Medium, Wide, Crowd*).
   - **Dynamika ruchu (Optical Flow):** estymacja wielkości wektorów ruchu i spójności kierunkowej.
   - **Detekcja scen (PySceneDetect):** znajdowanie naturalnych cięć kamerowych.
   - **Highlighty:** wyznaczanie najlepszych fragmentów czasowych z zachowaniem NMS (Non-Maximum Suppression).
   - **Cache:** Zapis wyników do `analysis/<plik>.json` na bieżąco. Możliwość wznowienia w dowolnym momencie.

2. **Etap 2: Zaawansowana analiza muzyczna (MP3)**
   - Detekcja tempa **BPM** oraz czasów wszystkich beatów z dokładnością do milisekund.
   - Wyznaczanie taktów (downbeats, 4/4) oraz fraz muzycznych (4-taktowe i 8-taktowe).
   - Ciągła krzywa energii (RMS + Spectral Centroid), podział na sekcje (*Calm, Medium, High, Drop/Climax*).
   - Automatyczne wykrywanie punktów kulminacyjnych (dropów i nagłych build-upów).

3. **Etap 3 & 4: Storyboard i algorytm montażysty**
   - **Dynamiczny rytm:** długość ujęcia dopasowywana do energii (od 0.35s w dropach do 6.0s w partiach spokojnych).
   - **Zasada Dropu:** najlepsze ujęcia z materiału (top 15%) są rezerwowane na kulminacje i dropy muzyczne.
   - **Wymuszone ujęcia (`forced_clips`):** możliwość zdefiniowania klipów, które bezwzględnie muszą znaleźć się w filmie, w tym z opcją precyzyjnego punktu startowego (`clip_time_start`) lub końcowego (`clip_time_end`).
   - **Różnorodność planów:** algorytm unika monotonii (kara za powtórzenie tego samego typu kadru pod rząd).
   - **Kara za powtórzenia:** zapobiega wielokrotnemu użyciu tego samego materiału źródłowego.
   - **Ścisła chronologia:** algorytm Monotonic Sliding Window zapewnia, że ujęcia układają się w czasie imprezy od pierwszego do ostatniego ujęcia (zero skoków wstecz).
   - **Zapis storyboardu:** generuje `storyboard.json` oraz czytelny `storyboard.txt` do wglądu przed renderem.

4. **Etap 5: Szybki podgląd (Preview 480p)**
   - Generuje plik `preview/preview_montage_480p.mp4` z proxy 480p z nałożoną muzyką MP3.
   - Czas renderowania ~28 sekund, rozmiar ~10 MB.

5. **Etap 6: Final Master Render 4K / 60 FPS (NVIDIA NVENC / CPU)**
   - Render z oryginalnych plików w `materialy_oryginalne/` w pełnym 4K 60 fps.
   - Całkowite odcięcie oryginalnego audio (`-an`).
   - Wklejenie ścieżki MP3 (`AAC 320 kbps`).
   - Sprzętowe kodowanie `hevc_nvenc` / `h264_nvenc` na GPU NVIDIA (lub automatyczny fallback na CPU).
   - Pełna niewrażliwość na wielkość liter (case-insensitive) przy dopasowywaniu nazw plików z kamery (np. `.MP4`, `_B.mp4`).


---

## 🛠️ Wymagania systemowe & Dobór Sprzętu

* **System operacyjny:** Windows 10 / Windows 11
* **Karta graficzna (GPU):**
  * **Stacja robocza (zalecana):** karta NVIDIA z obsługą CUDA i NVENC (np. seria RTX 30xx / 40xx, min. 6–8 GB VRAM, optymalnie 24 GB VRAM jak RTX 3090) – pozwala na uruchomienie flagowego modelu AI **YOLO11x** oraz błyskawiczny render NVENC 4K/60fps w kilka minut.
  * **Laptop / Komputer biurowy:** procesory mobilne (np. AMD Ryzen 7 7730U, Intel Core) lub układy zintegrowane – w pełni wspierane przy użyciu zoptymalizowanych pod procesor modeli AI (**`yolo11n.pt`** / **`yolov8n.pt`**).
* **Automatyczny Strażnik Sprzętu (Hardware Guard):**
  System automatycznie bada podzespoły (GPU, VRAM, procesor CPU). W razie próby uruchomienia ciężkiego modelu Extra Large na komputerze ze zbyt małą pamięcią VRAM lub samym CPU, program natychmiast przerwie pracę z czytelnym komunikatem i wskaże dokładnie, co wpisać w `config.yaml`, zapobiegając przegrzaniu laptopa i zamrożeniu systemu.
* **Procesor:** 4-rdzeniowy lub szybszy (Intel Core i5/i7/i9 lub AMD Ryzen).
* **Pamięć RAM:** 16 GB (zalecane 32 GB dla płynnej obróbki materiałów 4K).
* **Python:** 3.10+ / 3.11 / 3.12 (z obsługą PyTorch CUDA na maszynach z kartą NVIDIA).
* **FFmpeg:** zainstalowany w systemie i dodany do zmiennej środowiskowej PATH (z opcją NVENC dla kart NVIDIA / AMF dla AMD).

---

## 📦 Instalacja w środowisku VENV (1-kliknięcie)

W katalogu `AI_MONTAGE` znajduje się skrypt automatyczny:

1. Uruchom dwuklikiem plik:
   ```cmd
   setup_venv.bat
   ```
   Skrypt utworzy wirtualne środowisko `venv`, zaktualizuje `pip` i zainstaluje wszystkie wymagane biblioteki z `requirements.txt`.

2. Opcjonalnie (ręcznie w wierszu poleceń cmd/powershell):
   ```cmd
   cd AI_MONTAGE
   python -m venv venv
   call venv\Scripts\activate
   pip install -r requirements.txt
   ```

---

## 🎮 Instrukcja Użycia (CLI)

Możesz używać bezpośrednich poleceń Pythona `python main.py <komenda>` (w aktywnym środowisku `venv`) lub przygotowanego skryptu `run.bat`, który automatycznie aktywuje środowisko:

### 1. Analiza klipów proxy
```cmd
run.bat analyze
```
*lub bezpośrednio w Pythonie:*
```cmd
python main.py analyze
```
*Program wyświetli pasek postępu z czasem pozostałym do końca (ETA). Jeśli proces zostanie przerwany, ponowne uruchomienie podejmie pracę od ostatniego nieskończonego pliku (cache JSON).*

### 2. Analiza muzyki
```cmd
python main.py analyze-music
```
*Możesz wskazać inny plik muzyczny:*
```cmd
python main.py analyze-music --music "moja_muzyka.mp3"
```
*(lub przez `run.bat analyze-music`)*

### 3. Generowanie Storyboardu (Błyskawiczne ~2s)
```cmd
python main.py create-storyboard
```
*lub za pomocą skryptu:*
```cmd
run.bat create-storyboard
```
*W zaledwie ~2 sekundy (bez konieczności renderowania wideo) wygeneruje lub zaktualizuje:*
- `storyboard/storyboard.txt` *(czytelna dla człowieka lista ujęć, czasów, punktów cięcia i powodów wyboru)*
- `storyboard/storyboard.json` *(dane dla wbudowanego silnika renderującego)*
- `storyboard/montage_openshot_4K.osp` *(projekt OpenShot 4.0.0 podpięty pod oryginalne pliki 4K)*
- `storyboard/montage_openshot_480p.osp` *(projekt OpenShot 4.0.0 podpięty pod lekkie proxy 480p)*

### 4. Generowanie szybkiego podglądu 480p
```cmd
run.bat preview
```
*Wyrenderuje `preview/preview_montage_480p.mp4` w ~28 sekund (rozmiar ~10 MB).*

### 5. Finalny Master Render 4K / 60 FPS
```cmd
run.bat render
```
*Renderuje film w jakości 4K / 60 FPS z katalogu `materialy_oryginalne` z nałożoną muzyką i usuniętym oryginalnym audio (~7–10 min).*

### 6. Uruchomienie całości na raz (Etapy 1–5)
```cmd
run.bat all
```

---

## 🔧 Narzędzia pomocnicze

### 7. Synchronizacja proxy 480p z oryginałami
```cmd
run.bat sync-proxies
```
Skrypt sprawdza katalog `kopie_robocze_480p` względem `materialy_oryginalne`:
- **Brakujące proxy** → automatycznie kompresuje oryginał do 480p/15fps
- **Nadmiarowe proxy (orphan)** → usuwa pliki bez odpowiednika w oryginałach

**Tryb podglądu (bez zmian):**
```cmd
run.bat sync-proxies --dry-run
```

*Przydatne gdy dodasz nowe nagrania do katalogu materialy_oryginalne - skrypt uzupełni kopie_robocze_480p automatycznie.*

---

### 8. Eksport poszczególnych ujęć z montażu
```cmd
run.bat export-clips
```
Wycina fragmenty dokładnie zgodne ze storyboardem i zapisuje je do:
- `clips_4k/`   - fragmenty z oryginalnych plików 4K (wideo bez audio, numerowane `001_<nazwa>.mp4`)
- `clips_480p/` - fragmenty z proxy 480p (do szybkiego podglądu)

**Eksport tylko wersji 480p (szybko):**
```cmd
run.bat export-clips --only-proxy
```

**Eksport tylko wersji 4K:**
```cmd
run.bat export-clips --only-4k
```

---

### 9. Audyt sprzętu i silnika FFmpeg
```cmd
run.bat hardware
```
Szybki test i diagnostyka konfiguracji sprzętowej:
- Wykrywa karty graficzne (NVIDIA, AMD Radeon, Intel Arc/Iris, CPU) oraz pamięć VRAM.
- Skanuje silnik FFmpeg pod kątem wspieranych enkoderów sprzętowych (`NVENC`, `AMF`, `QSV`).
- Wyświetla inteligentne wskazówki (np. jak pobrać pełną wersję FFmpeg z obsługą AMF pod kartę Radeon RX 580).

---

### 10. Czyszczenie projektu i reset do zera
```cmd
run.bat clean
```
*Program wyświetli podsumowanie katalogów do wyczyszczenia i zapyta o potwierdzenie.*

Automatyczne potwierdzenie (bez pytania):
```cmd
run.bat clean --yes
```

---

## 🧹 Rozpoczynanie nowego projektu od zera (Reset danych)

Gdy skończysz montaż jednego filmu i chcesz zmontować materiały z zupełnie innego wydarzenia (np. nowe wesele, wyjazd, urodziny), musisz pozbyć się starych plików tymczasowych, cache analizy oraz wyrenderowanych podglądów.

### Jak wyczyścić dane 1-kliknięciem?
Wystarczy uruchomić dwuklikiem plik w głównym katalogu `AI_MONTAGE/`:
👉 **`WYCZYSC_PROJEKT.bat`**

Skrypt poprosi o potwierdzenie `(T/N)`, a następnie bezpiecznie opróżni katalogi robocze. Alternatywnie możesz użyć konsoli:
```cmd
run.bat clean --yes
```

### Co zostaje usunięte, a co zachowane?

| Folder / Plik | Status | Opis |
|---------------|--------|------|
| `analysis/` | 🗑️ Czyszczony | Stary cache analizy wideo i muzyki (`*.json`) |
| `storyboard/` | 🗑️ Czyszczony | Scenariusze `storyboard.json`, `storyboard.txt` oraz projekty `.osp` |
| `preview/` | 🗑️ Czyszczony | Wyrenderowany film podglądowy 480p i listy concat |
| `output/` | 🗑️ Czyszczony | Wyrenderowany film master 4K i tymczasowe segmenty |
| `clips_480p/`, `clips_4k/` | 🗑️ Czyszczony | Wycięte klipy ze starego storyboardu |
| `montage.log` | 🗑️ Resetowany | Stary dziennik zdarzeń |
| `materialy_oryginalne/` | 🔒 **NIENARUSZONE** | Twoje oryginalne pliki wideo |
| `kopie_robocze_480p/` | 🔒 **NIENARUSZONE** | Twoje kopie robocze proxy |
| `sciezkadzwiekowa/` | 🔒 **NIENARUSZONE** | Twoje pliki muzyczne MP3 |

> [!NOTE]
> Same katalogi robocze (`analysis/`, `storyboard/`, itp.) **pozostają na dysku puste**, dzięki czemu system jest od razu gotowy do pracy bez konieczności ich ponownego tworzenia.

### Checklista: Rozpoczęcie nowego montażu krok po kroku:
1. **Wyczyść projekt:** Uruchom `WYCZYSC_PROJEKT.bat` (lub `run.bat clean --yes`).
2. **Podmień pliki wideo:**
   - Wyczyść folder `materialy_oryginalne/` i wrzuć nagrania 4K z nowego wydarzenia.
   - Wyczyść folder `kopie_robocze_480p/` (program sam je utworzy za pomocą `run.bat sync-proxies` lub `ZROB_PREVIEW.bat`).
3. **Podmień muzykę:** Wrzuć nowy plik MP3 do `sciezkadzwiekowa/` (domyślnie `sciezka_dzwiekowa.mp3`).
4. **Zaktualizuj konfigurację:**
   - W [`config.yaml`](config.yaml) upewnij się, że `music_file` odpowiada Twojemu plikowi MP3 (domyślnie: `"sciezka_dzwiekowa.mp3"`).
   - W dedykowanym pliku [`forced_clips.yaml`](forced_clips.yaml) podaj ujęcia, które koniecznie mają się znaleźć w montażu (lub zostaw `forced_clips: []`).
5. **Uruchom montaż nowego filmu:**
   Dwukliknij `ZROB_PREVIEW.bat` lub uruchom `run.bat all`.

---

## ⚙️ Konfiguracja (`config.yaml`)

W pliku `config.yaml` możesz w łatwy sposób dostosować:
- Ścieżki katalogów (`proxy_dir`, `original_dir`, `music_dir`, `output_dir`)
- Wagi scoringu (ostrość, osoby, ruch, kompozycja, kary za rozmycie/szarpanie)
- Długości ujęć dla poszczególnych energii muzycznych (drop, high, medium, calm)
- Preferencje doboru (kary za powtórzenie typu kadru, kary za ponowne użycie pliku)
- Jakość kodowania GPU (NVENC / AMF / QSV lub CPU)

### Wybór modelu AI (`video_analysis` w config.yaml)

Wybór modelu decyduje o precyzji wykrywania osób, twarzy i planów filmowych:

| Model | Rozmiar | Wymagany sprzęt | Kiedy stosować |
|---|---|---|---|
| **`yolo11x.pt`** | Extra Large (~109 MB) | Dedykowana karta NVIDIA (CUDA, min. 4–6 GB VRAM) | **Rekomendowany dla stacji roboczych (np. RTX 3090)**. Maksymalna precyzja detekcji małych postaci w tłumie i trudnym oświetleniu. |
| **`yolov8x.pt`** | Extra Large (~130 MB) | Dedykowana karta NVIDIA (CUDA, min. 4–6 GB VRAM) | Sprawdzony model flagowy poprzedniej generacji. |
| **`yolo11s.pt`** | Small (~22 MB) | GPU z 2 GB VRAM lub mocny procesor CPU | Kompromis na starsze karty graficzne. |
| **`yolo11n.pt`** | Nano (~6 MB) | Dowolny procesor CPU / zintegrowana grafika | **Rekomendowany dla laptopów (np. AMD Ryzen 7 7730U, Intel Iris)**. Szybka analiza na CPU bez przegrzewania komputera. |

#### Rekomendowane ustawienia w `config.yaml`:
* **Dla stacji roboczej z kartą NVIDIA (np. RTX 3090 24GB):**
  ```yaml
  video_analysis:
    yolo_model: "yolo11x.pt"
    device: "cuda"
    batch_size: 32
  ```
* **Dla laptopa lub komputera bez dedykowanego GPU (np. Ryzen 7 7730U):**
  ```yaml
  video_analysis:
    yolo_model: "yolo11n.pt"
    device: "cpu"
    batch_size: 4
  ```

---

## 📂 Struktura katalogów projektu

```
AI_MONTAGE/
├── venv/                       # Wirtualne środowisko Python
├── main.py                     # Główny interfejs CLI
├── config.yaml                 # Plik konfiguracyjny
├── requirements.txt            # Zależności Python
├── setup_venv.bat              # Instalator środowiska venv
├── run.bat                     # Uruchamianie komend w venv
├── ZROB_PREVIEW.bat            # 1-klik: synchronizacja, analiza, storyboard i preview 480p
├── ZROB_RENDER_4K.bat          # 1-klik: render finalnego filmu 4K/60fps
├── WYCZYSC_PROJEKT.bat         # 1-klik: czyszczenie cache, storyboardów i renderów do zera
├── README.md                   # Niniejsza dokumentacja
├── sync_proxies.py             # Synchronizacja kopie_robocze_480p ↔ materialy_oryginalne
├── export_clips.py             # Eksport poszczególnych ujęć do clips_4k/ i clips_480p/
│
├── materialy_oryginalne/       # Oryginalne pliki 4K/60fps (źródło renderowania)
├── kopie_robocze_480p/         # Skompresowane proxy 480p/15fps (źródło analizy AI)
├── sciezkadzwiekowa/           # Pliki muzyczne MP3
│
├── analyzer/                   # Moduły analizy wideo
│   ├── video_analyzer.py       # Orkiestrator analizy z cache i paskiem postępu
│   ├── scene_detector.py       # PySceneDetect / OpenCV
│   ├── quality_analyzer.py     # Ostrość, blur, ekspozycja, stabilność
│   ├── people_detector.py      # Detekcja ludzi YOLO, plany filmowe
│   ├── motion_analyzer.py      # Optical Flow, dynamika ruchu
│   └── highlight_detector.py   # Wyłanianie najlepszych fragmentów (NMS)
│
├── music/                      # Moduły analizy muzyki
│   ├── music_analyzer.py       # Główna analiza audio i eksport
│   ├── beat_detector.py        # BPM, beaty, takty, frazy
│   └── energy_analyzer.py      # Krzywa energii RMS, dropy i kulminacje
│
├── montage/                    # Silnik montażowy
│   ├── scoring.py              # Funkcja scoringu dopasowania do muzyki
│   ├── timeline.py             # Matematyczny podział osi czasu
│   ├── selector.py             # Algorytm montażysty (chronologia, różnorodność)
│   └── storyboard.py           # Eksporter storyboard.json i storyboard.txt
│
├── render/                     # Renderowanie wideo
│   ├── preview.py              # Generator podglądu 480p (~28s)
│   └── final_render.py         # Master render 4K/60 NVENC z oryginałów
│
├── utils/                      # Moduły pomocnicze
│   ├── logger.py               # Logowanie Rich + plikowe
│   ├── helpers.py              # Czas, I/O, obsługa FFmpeg, dopasowanie plików
│   └── config_loader.py        # Parser i walidator config.yaml
│
├── analysis/                   # Pliki cache JSON dla każdego klipu
├── storyboard/                 # storyboard.json i storyboard.txt
├── preview/                    # Wyrenderowany podgląd 480p
├── output/                     # Finalny master render 4K/60fps
├── clips_4k/                   # Wycięte ujęcia 4K (eksport ze storyboardu)
└── clips_480p/                 # Wycięte ujęcia 480p (eksport ze storyboardu)
```

---

## 🎯 Typowy scenariusz użycia - krok po kroku

> **Pierwszy raz / po dodaniu nowych nagrań:**

```cmd
:: 1. Upewnij się, że proxy są zsynchronizowane z oryginałami
run.bat sync-proxies

:: 2. Przeanalizuj klipy proxy (pomija już przeanalizowane - cache)
run.bat analyze

:: 3. Wygeneruj storyboard (~2s, tworzy też projekty OpenShot .osp)
python main.py create-storyboard
:: lub: run.bat create-storyboard

:: 4. Sprawdź szybki podgląd (~28s render, ~10MB)
run.bat preview

:: 5. Jeśli OK - wyrenderuj finalny master 4K (~7-10min)
run.bat render

:: 6. Opcjonalnie - wyeksportuj poszczególne ujęcia do podglądu
run.bat export-clips --only-proxy
```

> **Zmiana muzyki:**

```cmd
:: Wystarczy wygenerować nowy storyboard (~2s) i render - analiza wideo jest w cache
python main.py create-storyboard
run.bat preview
run.bat render
```

---

## 📁 Materiały źródłowe (wewnątrz AI_MONTAGE)

```
AI_MONTAGE/
├── materialy_oryginalne/       # Oryginalne pliki 4K/60fps (źródło renderowania)
├── kopie_robocze_480p/         # Skompresowane proxy 480p/15fps (źródło analizy AI)
├── sciezkadzwiekowa/           # Pliki muzyczne MP3
└── outro_image/                # (opcjonalne) Statyczny obraz outro (outro.jpg)
```

> [!IMPORTANT]
> Jeśli dodasz nowe pliki do `materialy_oryginalne/`, uruchom `run.bat sync-proxies` żeby automatycznie uzupełnić `kopie_robocze_480p/` i uruchom `run.bat analyze` żeby przeanalizować nowe klipy.

---

## ⭐ Gwarancja konkretnych ujęć - forced_clips.yaml

Możesz wskazać klipy, które **ZAWSZE** mają się znaleźć w finalnym montażu.
Wszystkie wymuszone ujęcia definiuje się w dedykowanym pliku [`forced_clips.yaml`](forced_clips.yaml).
Program wybierze z nich najlepszy fragment (ostrość, osoby, ruch) i przytnie do odpowiedniej długości dopasowanej do rytmu muzyki.

### Jak dodać wymuszone ujęcie

**Krok 1** - Otwórz katalog `kopie_robocze_480p/` i znajdź plik który cię interesuje, np.:
```
29_125240_piata_mowczyni_na_scenie_b_480p15.mp4
```

**Krok 2** - Wpisz jego nazwę do [`forced_clips.yaml`](forced_clips.yaml) **bez `_480p15` i bez `.mp4`**:

```yaml
forced_clips:
  - file: "29_125240_piata_mowczyni_na_scenie_b"
    clip_time_start: "0:03"     # zacznij wycinać od 3. sekundy tego klipu (pomiń początek)

  - file: "29_130535_ludzie_zbieraja_sie_na_sciance_c"

  - file: "28_193407_kolacja_wieczorna"
    clip_time_end: "0:12"       # ujęcie w montażu skończy się dokładnie w 12. sekundzie
```

> [!IMPORTANT]
> **Dopasowanie jest ścisłe (exact match).** Jeśli wpiszesz nazwę której nie ma w `kopie_robocze_480p/`, program **przerwie działanie** z listą brakujących plików:
> ```
> ═══════════════════════════════════════════════════════
>   BŁĄD KRYTYCZNY - wymuszone ujęcia nie zostały znalezione:
> ═══════════════════════════════════════════════════════
>   ✗  'nieistniejacy_plik'
>   Sprawdź nazwy w forced_clips.yaml → forced_clips
>   Wpisz dokładną nazwę pliku (bez rozszerzenia i bez _480p15)
>   Dostępne proxy znajdziesz w katalogu kopie_robocze_480p/
> ═══════════════════════════════════════════════════════
> ```

### Zasady działania

| Parametr | Wymagany? | Opis |
|----------|-----------|------|
| `file` | **TAK** | Dokładna nazwa pliku z `kopie_robocze_480p/` — bez `_480p15` i bez `.mp4`. Możesz też wpisać z sufiksem — program sam go odtnie. |
| `clip_time_start` | Opcjonalny | Punkt startowy wewnątrz nagrania (np. `"0:03"` lub `"15"`). Pomija wszystko co przed nim! Algorytm sam dobierze odpowiednią długość trwania sceny w rytm muzyki. |
| `clip_time_end` | Opcjonalny | Punkt końcowy wewnątrz nagrania (np. `"0:10"`). Algorytm dobiera początek wstecz w rytm muzyki, tak aby ujęcie w filmie docelowym skończyło się dokładnie w tej sekundzie. |

> [!WARNING]
> **Wzajemne wykluczanie:** Parametry `clip_time_start` oraz `clip_time_end` **nie mogą** występować jednocześnie dla tego samego klipu. Podanie obu spowoduje przerwanie działania z błędem wyjaśniającym.

* **Gdy podasz tylko `file` (bez `clip_time_start` ani `clip_time_end`):**
  * Ujęcie trafi na oś czasu **automatycznie i chronologicznie** (zgodnie z datą/godziną nagrania).
  * Algorytm AI **samodzielnie przeskanuje klip i wybierze z niego najlepszy moment** (najwyższy score: ostrość, twarze, stabilność).
* **Długość wycinka:** Zawsze dobierana jest automatycznie w rytm muzyki (~1.2–6s zależnie od energii) — nie musisz ręcznie wyliczać klatki końcowej!
* **Kolizje czasowe:** Jeśli dwa wymuszone ujęcia trafią na ten sam slot, drugie zostanie przesunięte do najbliższego wolnego miejsca na osi czasu.

> [!TIP]
> **Jak przetestować zmiany po edycji `forced_clips`?**
> - **Opcja 1 (Błyskawiczna ~2 sekundy - Storyboard & OpenShot):**
>   ```cmd
>   python main.py create-storyboard
>   ```
>   *(lub `run.bat create-storyboard`)*
>   Przelicza wyłącznie dopasowanie klipów na osi czasu i natychmiast aktualizuje `storyboard/storyboard.json`, `storyboard/storyboard.txt` oraz oba projekty OpenShot (`montage_openshot_4K.osp` i `montage_openshot_480p.osp`) bez konieczności czekania na renderowanie wideo.
> - **Opcja 2 (Wyrenderowanie podglądu MP4 ~25–30 sekund):**
>   Uruchom dwuklikiem `ZROB_PREVIEW.bat` (lub `python main.py preview` / `run.bat preview`). Wygeneruje zaktualizowany storyboard i od razu wyrenderuje plik wideo `preview/preview_montage_480p.mp4`.
>
> *(W obu przypadkach nie trzeba ponownie analizować klipów – cała analiza AI wideo jest bezpiecznie zachowana w cache).*
