# Сборка кадров из render/out в видеофайлы.
#
#   powershell -File render\encode.ps1
#   powershell -File render\encode.ps1 -Fps 24 -Name okno-film
#
# На выходе три файла:
#   .mp4  — H.264, для сайта, презентаций и рекламных кабинетов
#   .webm — VP9, легче на 30-40% там, где поддерживается
#   .jpg  — постер, он же плакат для видео на сайте

param(
  [int]$Fps = 24,
  [string]$In = "render\out",
  [string]$Out = "render\video",
  [string]$Name = "okonniy-zavod-film",
  [int]$Crf = 18
)

$ErrorActionPreference = "Stop"

# ffmpeg не всегда попадает в PATH текущей сессии — ищем его сами
$ff = (Get-Command ffmpeg -ErrorAction SilentlyContinue).Source
if (-not $ff) {
  foreach ($c in @("C:\tools\ffmpeg\bin\ffmpeg.exe",
                   "$env:LOCALAPPDATA\Microsoft\WinGet\Links\ffmpeg.exe")) {
    if (Test-Path $c) { $ff = $c; break }
  }
}
if (-not $ff) { Write-Error "ffmpeg не найден"; exit 1 }
Write-Host "ffmpeg: $ff"

# Зерно и лёгкое размытие по времени: цифровой рендер выдаёт себя
# идеально чистым кадром, у плёнки такого не бывает.
$grain = "noise=alls=5:allf=t+u,unsharp=5:5:0.5:5:5:0.0"

$frames = Get-ChildItem $In -Filter "*.png" -ErrorAction SilentlyContinue
if (-not $frames) { Write-Error "В $In нет кадров. Сначала запусти рендер."; exit 1 }
Write-Host "Кадров найдено: $($frames.Count)"

New-Item -ItemType Directory -Path $Out -Force | Out-Null

# Blender нумерует файлы как «кадр_0001.png»
$pattern = Join-Path $In "кадр_%04d.png"

Write-Host "`nH.264 (MP4)..."
& $ff -y -hide_banner -loglevel warning `
  -framerate $Fps -i $pattern `
  -vf $grain `
  -c:v libx264 -preset slow -crf $Crf -pix_fmt yuv420p `
  -movflags +faststart `
  (Join-Path $Out "$Name.mp4")

Write-Host "VP9 (WebM)..."
& $ff -y -hide_banner -loglevel warning `
  -framerate $Fps -i $pattern `
  -vf $grain `
  -c:v libvpx-vp9 -crf 32 -b:v 0 -row-mt 1 -pix_fmt yuv420p `
  (Join-Path $Out "$Name.webm")

Write-Host "Постер..."
$poster = Join-Path $Out "$Name-poster.jpg"
& $ff -y -hide_banner -loglevel warning `
  -i (Join-Path $Out "$Name.mp4") -vf "select=eq(n\,12)" -frames:v 1 -update 1 -q:v 2 $poster

Write-Host "`nГотово:"
Get-ChildItem $Out | ForEach-Object {
  "{0,-40} {1,8:N1} МБ" -f $_.Name, ($_.Length / 1MB)
}

Write-Host @"

Как вставить в первый экран сайта — вместо трёхмерной сцены:

  <video autoplay muted loop playsinline preload="metadata"
         poster="/video/$Name-poster.jpg" class="hero__video">
    <source src="/video/$Name.webm" type="video/webm">
    <source src="/video/$Name.mp4"  type="video/mp4">
  </video>

Файлы положить в public/video/. Атрибуты muted и playsinline обязательны:
без них автовоспроизведение не сработает на iPhone.
"@
