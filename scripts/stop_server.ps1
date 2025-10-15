$ErrorActionPreference = 'SilentlyContinue'
try {
  $conns = Get-NetTCPConnection -LocalPort 8000 -ErrorAction SilentlyContinue
  if ($conns) {
    $pids = $conns | Select-Object -ExpandProperty OwningProcess -Unique
    foreach ($pid in $pids) {
      Stop-Process -Id $pid -Force -ErrorAction SilentlyContinue
    }
  }
} catch {}

Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -match 'uvicorn' } | ForEach-Object {
  try { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue } catch {}
}

'stopped'

