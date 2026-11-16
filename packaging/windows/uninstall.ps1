# Removes Rep Book (the app) for this Windows user (Settings > Apps > Rep Book > Uninstall).
# Your data folder (%LOCALAPPDATA%\RepBook) is never deleted. ASCII only (see install.ps1).

$ErrorActionPreference = 'Continue'
$Root = Join-Path $env:LOCALAPPDATA 'RepBook-app'
$App = Join-Path $Root 'app'
$Py = Join-Path $App '.pixi\envs\default\python.exe'

Write-Host 'Uninstall Rep Book'
Write-Host '--------------------'
$Unattended = [bool]$env:REPBOOK_UNATTENDED  # automated tests: no questions
$yes = if ($Unattended) { 'y' } else { Read-Host 'Remove Rep Book from this computer? Your data is kept. [y/N]' }
if ($yes -notmatch '^[Yy]') { Write-Host 'Nothing was changed.'; Start-Sleep 2; exit 0 }

$Data = ''
if (Test-Path $Py) {
    Push-Location $App
    $Data = (& $Py -X utf8 -c 'from repbook.paths import data_dir; print(data_dir())' 2>$null | Select-Object -First 1)
    Pop-Location
}
if (-not $Data) { $Data = Join-Path $env:LOCALAPPDATA 'RepBook' }

# This installation's running Rep Book (matched by path), so its files can be deleted.
Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
    Where-Object { $_.ExecutablePath -and $_.ExecutablePath.StartsWith($App + '\', [StringComparison]::OrdinalIgnoreCase) } |
    ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
Start-Sleep -Seconds 1

foreach ($dir in @([Environment]::GetFolderPath('Programs'), [Environment]::GetFolderPath('Desktop'))) {
    Remove-Item -Force -ErrorAction SilentlyContinue (Join-Path $dir 'Rep Book.lnk')
}
Remove-Item -Recurse -Force -Path 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\RepBookApp' -ErrorAction SilentlyContinue
Set-Location $env:USERPROFILE
Remove-Item -Recurse -Force -Path $Root -ErrorAction SilentlyContinue
if (Test-Path $Root) {
    Write-Host "Some of Rep Book's files are in use; delete $Root after restarting." -ForegroundColor Yellow
} else {
    Write-Host "Removed Rep Book's files and shortcuts." -ForegroundColor Green
}

Write-Host ''
Write-Host 'Your data (workout log, backups) is kept in:'
Write-Host "  $Data"
Write-Host 'Installing Rep Book again picks it up. Delete that folder yourself only if you are sure.'
if (-not $Unattended) { Read-Host 'Press Enter to close this window' | Out-Null }
