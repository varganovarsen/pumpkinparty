# Удалённые команды на ноутбуке с Windows-ПК (обёртка над ssh).
#   tools\remote.ps1 laptop check|status|log|restart|stop
param(
  [Parameter(Mandatory = $true)][string]$SshHost,
  [ValidateSet("check", "status", "log", "restart", "stop")][string]$Cmd = "status",
  [string]$Dest = "pumpkin"
)
$stop = "cd '$Dest' && if [ -f data/server.pid ]; then kill `$(cat data/server.pid) 2>/dev/null || true; sleep 2; fi"
switch ($Cmd) {
  "check"   { ssh $SshHost "cd '$Dest' && .venv/bin/python tools/check_env.py --webcam" }
  "status"  { ssh $SshHost "cd '$Dest' && .venv/bin/python -c `"import urllib.request;print(urllib.request.urlopen('http://localhost:8000/api/health',timeout=2).read().decode())`"" }
  "log"     { ssh -t $SshHost "tail -n 200 -F '$Dest/data/logs/server.log'" }
  "stop"    { ssh $SshHost $stop }
  "restart" { ssh $SshHost "$stop; cd '$Dest' && (setsid nohup ./start.sh --no-browser >data/logs/start.log 2>&1 &); sleep 4; tail -n 3 data/logs/start.log" }
}
