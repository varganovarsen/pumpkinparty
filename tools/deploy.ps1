# Перенос проекта с Windows-ПК на ноутбук по ssh (data/, .git и .venv не переносятся).
#   powershell -ExecutionPolicy Bypass -File tools\deploy.ps1 laptop [папка, по умолчанию pumpkin]
# Нужны встроенные в Windows 10+ ssh, scp и tar. Удалённые на ПК файлы на ноутбуке не удаляются.
param(
  [Parameter(Mandatory = $true)][string]$SshHost,
  [string]$Dest = "pumpkin"
)
$ErrorActionPreference = "Stop"
Set-Location (Join-Path $PSScriptRoot "..")
$archive = Join-Path $env:TEMP "pumpkin-deploy.tgz"
tar -czf $archive --exclude ./data --exclude ./.git --exclude ./.venv --exclude __pycache__ --exclude .pytest_cache .
if ($LASTEXITCODE -ne 0) { throw "tar не смог собрать архив" }
ssh $SshHost "mkdir -p '$Dest'"
scp $archive "${SshHost}:/tmp/pumpkin-deploy.tgz"
ssh $SshHost "tar -xzf /tmp/pumpkin-deploy.tgz -C '$Dest' && rm /tmp/pumpkin-deploy.tgz && chmod +x '$Dest/start.sh' '$Dest'/tools/*.sh"
Remove-Item $archive
Write-Host "Готово: ${SshHost}:$Dest. Перезапуск: tools\remote.ps1 $SshHost restart"
