# AroundWorldNG - Fast One-Click Mod Installer for BeamNG.drive
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$Host.UI.RawUI.WindowTitle = "AroundWorldNG - Установка в BeamNG.drive"

Write-Host "======================================================================" -ForegroundColor Cyan
Write-Host "          AroundWorldNG — Установка мода в BeamNG.drive" -ForegroundColor Yellow
Write-Host "======================================================================" -ForegroundColor Cyan
Write-Host ""

# 1. Detect BeamNG mods folder
$modsCandidates = @(
    "$env:LOCALAPPDATA\BeamNG\BeamNG.drive\current\mods",
    "$env:LOCALAPPDATA\BeamNG\BeamNG.drive\0.33\mods",
    "$env:LOCALAPPDATA\BeamNG\BeamNG.drive\0.32\mods",
    "$env:LOCALAPPDATA\BeamNG\BeamNG.drive\0.31\mods",
    "$env:LOCALAPPDATA\BeamNG\BeamNG.drive\0.30\mods"
)

$targetMods = $null
foreach ($cand in $modsCandidates) {
    if (Test-Path $cand) {
        $targetMods = $cand
        break
    }
}

if (-not $targetMods) {
    $baseBeam = "$env:LOCALAPPDATA\BeamNG\BeamNG.drive"
    if (Test-Path $baseBeam) {
        $targetMods = "$baseBeam\current\mods"
        New-Item -ItemType Directory -Path $targetMods -Force | Out-Null
    }
}

if (-not $targetMods) {
    Write-Host "[!] Папка BeamNG.drive не найдена автоматически." -ForegroundColor Yellow
    $targetMods = Read-Host "Введите полный путь к вашей папке mods в BeamNG"
    if (-not (Test-Path $targetMods)) {
        New-Item -ItemType Directory -Path $targetMods -Force | Out-Null
    }
}

Write-Host "[1/3] Папка модов определена:" -ForegroundColor Green
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
    # Keep compatibility with earthng
    Copy-Item -Path $planetSrc -Destination "$targetMods\earthng_planet.zip" -Force -ErrorAction SilentlyContinue
    Write-Host "    [+] Ядро мода установлено (18 стилей новостроек, 3D-балконы, генератор)." -ForegroundColor Green
} else {
    Write-Host "  [!] Файл aroundworldng_planet.zip не найден рядом со скриптом." -ForegroundColor Red
}

if ($mapSrc) {
    Write-Host "  - Установка готовой карты ($([math]::Round((Get-Item $mapSrc).Length / 1MB, 1)) МБ)..." -ForegroundColor White
    Copy-Item -Path $mapSrc -Destination "$targetMods\aroundworldng_russia-saint-petersburg.zip" -Force
    Write-Host "    [+] Карта Санкт-Петербурга и Кудрово установлена." -ForegroundColor Green
} else {
    Write-Host "  [-] Готовая карта Санкт-Петербурга не найдена локально." -ForegroundColor Yellow
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
