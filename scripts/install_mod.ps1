# AroundWorldNG - Fast One-Click Mod Installer for BeamNG.drive
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$Host.UI.RawUI.WindowTitle = "AroundWorldNG - Установка в BeamNG.drive"

Write-Host "======================================================================" -ForegroundColor Cyan
Write-Host "          AroundWorldNG — Установка мода в BeamNG.drive" -ForegroundColor Yellow
Write-Host "======================================================================" -ForegroundColor Cyan
Write-Host ""

# 1. Detect candidate BeamNG mods folders
$modsCandidates = @(
    "$env:LOCALAPPDATA\BeamNG\BeamNG.drive\current\mods",
    "$env:LOCALAPPDATA\BeamNG\BeamNG.drive\0.33\mods",
    "$env:LOCALAPPDATA\BeamNG\BeamNG.drive\0.32\mods",
    "$env:LOCALAPPDATA\BeamNG\BeamNG.drive\0.31\mods",
    "$env:LOCALAPPDATA\BeamNG\BeamNG.drive\0.30\mods",
    "D:\SteamLibrary\steamapps\common\BeamNG.drive\mods",
    "D:\Games\BeamNG.drive\mods",
    "D:\BeamNG.drive\mods",
    "D:\BeamNG\mods"
)

$autoFound = $null
foreach ($cand in $modsCandidates) {
    if (Test-Path $cand) {
        $autoFound = $cand
        break
    }
}

function Pick-Folder([string]$initial) {
    try {
        Add-Type -AssemblyName System.Windows.Forms
        $fbd = New-Object System.Windows.Forms.FolderBrowserDialog
        $fbd.Description = "Выберите папку mods игры BeamNG.drive (например, на диске D:)"
        $fbd.ShowNewFolderButton = $true
        if ($initial -and (Test-Path $initial)) {
            $fbd.SelectedPath = $initial
        }
        $topForm = New-Object System.Windows.Forms.Form
        $topForm.TopMost = $true
        $res = $fbd.ShowDialog($topForm)
        if ($res -eq [System.Windows.Forms.DialogResult]::OK -and $fbd.SelectedPath) {
            return $fbd.SelectedPath
        }
    } catch {
        # Fallback if forms not supported
    }
    return $null
}

$targetMods = $null

if ([Environment]::UserInteractive -and -not [Console]::IsInputRedirected) {
    Write-Host "[1/3] Выбор папки установки мода:" -ForegroundColor Cyan
    if ($autoFound) {
        Write-Host "  Найдена стандартная папка: $autoFound" -ForegroundColor Gray
    }
    Write-Host ""
    Write-Host "  [1] Выбрать папку через проводник (откроется окно - диск D:\ и т.д.)" -ForegroundColor Yellow
    Write-Host "  [2] Ввести путь вручную (например: D:\BeamNG\mods)" -ForegroundColor White
    if ($autoFound) {
        Write-Host "  [3] Использовать авто-определённую папку: $autoFound" -ForegroundColor White
    }
    Write-Host ""

    $choice = Read-Host "Выберите вариант [1, 2" + $(if ($autoFound) { ", 3" } else { "" }) + "] (по умолчанию 1)"
    if (-not $choice) { $choice = "1" }

    if ($choice -eq "2") {
        $manual = Read-Host "Введите полный путь к папке mods"
        if ($manual) { $targetMods = $manual.Trim('"`''') }
    } elseif ($choice -eq "3" -and $autoFound) {
        $targetMods = $autoFound
    } else {
        Write-Host "Открывается окно проводника для выбора папки..." -ForegroundColor Cyan
        $picked = Pick-Folder $autoFound
        if ($picked) {
            $targetMods = $picked
        } else {
            Write-Host "Окно было закрыто без выбора." -ForegroundColor Yellow
            $manual = Read-Host "Введите путь вручную (или нажмите Enter для $autoFound)"
            if ($manual) { $targetMods = $manual.Trim('"`''') } else { $targetMods = $autoFound }
        }
    }
} else {
    $targetMods = $autoFound
}

if (-not $targetMods) {
    if ($autoFound) {
        $targetMods = $autoFound
    } else {
        $targetMods = "$env:LOCALAPPDATA\BeamNG\BeamNG.drive\current\mods"
    }
}

# Auto-correct if user selected BeamNG root without \mods
if ($targetMods -and (Split-Path -Leaf $targetMods).ToLower() -ne "mods") {
    if (Test-Path "$targetMods\mods") {
        $targetMods = "$targetMods\mods"
    } elseif (Test-Path "$targetMods\BeamNG.drive.exe" -or (Test-Path "$targetMods\Bin64")) {
        $targetMods = "$targetMods\mods"
    }
}

if (-not (Test-Path $targetMods)) {
    New-Item -ItemType Directory -Path $targetMods -Force | Out-Null
}

Write-Host "Выбрана папка установки:" -ForegroundColor Green
Write-Host "      $targetMods" -ForegroundColor White
Write-Host ""

# 2. Locate mod files
$root = $PSScriptRoot
if (-not $root) { $root = Get-Location }
$parent = Split-Path -Path $root -Parent

$planetCandidates = @(
    "$root\mod\aroundworldng_planet.zip",
    "$root\aroundworldng_planet.zip",
    "$parent\mod\aroundworldng_planet.zip",
    "$parent\aroundworldng_planet.zip"
)

$mapCandidates = @(
    "$root\mod\aroundworldng_russia-saint-petersburg.zip",
    "$root\out\country-setup\aroundworldng_russia-saint-petersburg.zip",
    "$root\aroundworldng_russia-saint-petersburg.zip",
    "$parent\mod\aroundworldng_russia-saint-petersburg.zip",
    "$parent\out\country-setup\aroundworldng_russia-saint-petersburg.zip"
)

$planetSrc = $null
foreach ($c in $planetCandidates) {
    if (Test-Path $c) { $planetSrc = $c; break }
}

$mapSrc = $null
foreach ($c in $mapCandidates) {
    if (Test-Path $c) { $mapSrc = $c; break }
}

Write-Host "[2/3] Копирование файлов в BeamNG.drive..." -ForegroundColor Green

if ($planetSrc) {
    Write-Host "  - Установка ядра AroundWorldNG ($([math]::Round((Get-Item $planetSrc).Length / 1MB, 1)) МБ)..." -ForegroundColor White
    Copy-Item -Path $planetSrc -Destination "$targetMods\aroundworldng_planet.zip" -Force
    Copy-Item -Path $planetSrc -Destination "$targetMods\earthng_planet.zip" -Force -ErrorAction SilentlyContinue
    Write-Host "    [+] Ядро мода установлено (18 стилей новостроек, 3D-балконы, генератор)." -ForegroundColor Green
} else {
    Write-Host "  [-] Локальный файл ядра не найден. Скачивание с GitHub Release v2.1.0 (260 МБ)..." -ForegroundColor Yellow
    $planetUrl = "https://github.com/wilszzz/aroundworldng/releases/download/v2.1.0/aroundworldng_planet.zip"
    curl.exe -L --progress-bar -o "$targetMods\aroundworldng_planet.zip" $planetUrl
    Copy-Item -Path "$targetMods\aroundworldng_planet.zip" -Destination "$targetMods\earthng_planet.zip" -Force -ErrorAction SilentlyContinue
    if (Test-Path "$targetMods\aroundworldng_planet.zip") {
        Write-Host "    [+] Ядро мода успешно скачано и установлено!" -ForegroundColor Green
    }
}

if ($mapSrc) {
    Write-Host "  - Установка готовой карты ($([math]::Round((Get-Item $mapSrc).Length / 1MB, 1)) МБ)..." -ForegroundColor White
    Copy-Item -Path $mapSrc -Destination "$targetMods\aroundworldng_russia-saint-petersburg.zip" -Force
    Write-Host "    [+] Карта Санкт-Петербурга и Кудрово установлена." -ForegroundColor Green
} else {
    Write-Host "  [-] Локальная карта не найдена. Скачивание с GitHub Release v2.1.0 (25 МБ)..." -ForegroundColor Yellow
    $mapUrl = "https://github.com/wilszzz/aroundworldng/releases/download/v2.1.0/aroundworldng_russia-saint-petersburg.zip"
    curl.exe -L --progress-bar -o "$targetMods\aroundworldng_russia-saint-petersburg.zip" $mapUrl
    if (Test-Path "$targetMods\aroundworldng_russia-saint-petersburg.zip") {
        Write-Host "    [+] Карта Санкт-Петербурга и Кудрово успешно скачана!" -ForegroundColor Green
    }
}

Write-Host ""
Write-Host "[3/3] Проверка..." -ForegroundColor Green

if (Test-Path "$targetMods\aroundworldng_planet.zip") {
    Write-Host "======================================================================" -ForegroundColor Green
    Write-Host "   [УСПЕХ] Мод AroundWorldNG успешно установлен в BeamNG.drive!" -ForegroundColor Yellow
    Write-Host "======================================================================" -ForegroundColor Green
    Write-Host ""
    Write-Host "   Инструкция для запуска:" -ForegroundColor Cyan
    Write-Host "   1. Запустите игру BeamNG.drive." -ForegroundColor White
    Write-Host "   2. Перейдите в меню выбора карт (Свободная езда)." -ForegroundColor White
    Write-Host "   3. Выберите уровень «Вокруг Света NG - Планета» (AroundWorldNG)." -ForegroundColor White
    Write-Host "   4. Нажмите «Запустить» и исследуйте реалистичное Кудрово и новостройки!" -ForegroundColor White
    Write-Host ""
} else {
    Write-Host "======================================================================" -ForegroundColor Red
    Write-Host "   [ОШИБКА] Не удалось завершить установку мода!" -ForegroundColor Red
    Write-Host "======================================================================" -ForegroundColor Red
}

if ([Environment]::UserInteractive -and -not [Console]::IsInputRedirected) {
    Write-Host "Нажмите любую клавишу для завершения..."
    try {
        $null = $Host.UI.RawUI.ReadKey("NoEcho,IncludeKeyDown")
    } catch {
        $null = Read-Host
    }
}
