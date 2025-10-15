param(
  [string]$BindHost = '127.0.0.1',
  [int]$Port = 8000
)

$ErrorActionPreference = 'SilentlyContinue'
if (!(Test-Path logs)) { New-Item -ItemType Directory -Path logs | Out-Null }
$out = 'logs\uvicorn.out.log'
$err = 'logs\uvicorn.err.log'
if (Test-Path $out) { Remove-Item $out -Force }
if (Test-Path $err) { Remove-Item $err -Force }

$py = if (Test-Path .\.venv\Scripts\python.exe) { '.\.venv\Scripts\python.exe' } elseif (Test-Path .\venv\Scripts\python.exe) { '.\venv\Scripts\python.exe' } else { 'python' }
$args = @('-m','uvicorn','main:app','--host',$BindHost,'--port',"$Port")
$p = Start-Process -FilePath $py -ArgumentList $args -RedirectStandardOutput $out -RedirectStandardError $err -PassThru -WindowStyle Hidden
Start-Sleep -Seconds 3
"PID $($p.Id)"
if (Test-Path $err) { Get-Content $err }
