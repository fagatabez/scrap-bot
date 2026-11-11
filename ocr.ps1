param([string]$Path, [string]$Out)
$ErrorActionPreference = "Stop"
Add-Type -AssemblyName System.Runtime.WindowsRuntime
$null = [Windows.Media.Ocr.OcrEngine, Windows.Foundation, ContentType=WindowsRuntime]
$null = [Windows.Graphics.Imaging.BitmapDecoder, Windows.Foundation, ContentType=WindowsRuntime]
$null = [Windows.Storage.StorageFile, Windows.Foundation, ContentType=WindowsRuntime]

$asTaskGeneric = ([System.WindowsRuntimeSystemExtensions].GetMethods() | Where-Object {
    $_.Name -eq 'AsTask' -and $_.GetParameters().Count -eq 1 -and $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncOperation`1'
})[0]

function Await($WinRtTask, $ResultType) {
    $asTask = $asTaskGeneric.MakeGenericMethod($ResultType)
    $netTask = $asTask.Invoke($null, @($WinRtTask))
    $netTask.Wait(-1) | Out-Null
    $netTask.Result
}

$file = Await ([Windows.Storage.StorageFile]::GetFileFromPathAsync($Path)) ([Windows.Storage.StorageFile])
$stream = Await ($file.OpenAsync([Windows.Storage.FileAccessMode]::Read)) ([Windows.Storage.Streams.IRandomAccessStream])
$decoder = Await ([Windows.Graphics.Imaging.BitmapDecoder]::CreateAsync($stream)) ([Windows.Graphics.Imaging.BitmapDecoder])
$bitmap = Await ($decoder.GetSoftwareBitmapAsync()) ([Windows.Graphics.Imaging.SoftwareBitmap])
$engine = [Windows.Media.Ocr.OcrEngine]::TryCreateFromUserProfileLanguages()
if ($null -eq $engine) {
    [pscustomobject]@{ text = ""; lines = @(); error = "no OCR engine" } | ConvertTo-Json -Depth 5 | Out-File -FilePath $Out -Encoding utf8
    exit 0
}
$result = Await ($engine.RecognizeAsync($bitmap)) ([Windows.Media.Ocr.OcrResult])

$lines = @()
foreach ($line in $result.Lines) {
    $minx = [double]::MaxValue
    $miny = [double]::MaxValue
    $maxx = [double]::MinValue
    $maxy = [double]::MinValue
    foreach ($word in $line.Words) {
        $r = $word.BoundingRect
        if ($r.X -lt $minx) { $minx = $r.X }
        if ($r.Y -lt $miny) { $miny = $r.Y }
        if (($r.X + $r.Width) -gt $maxx) { $maxx = $r.X + $r.Width }
        if (($r.Y + $r.Height) -gt $maxy) { $maxy = $r.Y + $r.Height }
    }
    if ($minx -ne [double]::MaxValue) {
        $lines += [pscustomobject]@{
            text = $line.Text
            x = [int]$minx
            y = [int]$miny
            w = [int]($maxx - $minx)
            h = [int]($maxy - $miny)
        }
    }
}

[pscustomobject]@{ text = $result.Text; lines = $lines; error = "" } |
    ConvertTo-Json -Depth 6 | Out-File -FilePath $Out -Encoding utf8
