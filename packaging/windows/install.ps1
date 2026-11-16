# Installs, or updates, Rep Book for this Windows user. Run by "Install Rep Book.cmd".
#
#   %LOCALAPPDATA%\RepBook-app\   app\ (the app and its environment), bin\pixi.exe, uninstall.ps1
#   Start menu + Desktop shortcut   opens Rep Book (starts it if needed)
#   %LOCALAPPDATA%\RepBook\       your data: never touched here
#
# No administrator rights; listed under Settings > Apps for uninstalling. Built by packaging/build_release.py.
# ASCII only: Windows PowerShell 5.1 misreads UTF-8 scripts without a BOM.
param([Parameter(Mandatory = $true)][string]$Source)

$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'  # Invoke-WebRequest is very slow with its progress bar
$PixiVersion = '__PIXI_VERSION__'
$AppVersion = '__APP_VERSION__'
$Root = Join-Path $env:LOCALAPPDATA 'RepBook-app'
$App = Join-Path $Root 'app'
$Bin = Join-Path $Root 'bin'
$Pixi = Join-Path $Bin 'pixi.exe'
$EnvDir = Join-Path $App '.pixi\envs\default'
$Py = Join-Path $EnvDir 'python.exe'
$Pyw = Join-Path $EnvDir 'pythonw.exe'
$Icon = Join-Path $App 'packaging\windows\icon.ico'

# REPBOOK_UNATTENDED=1: no prompts and no browser (automated tests, and a future self-update)
$Unattended = [bool]$env:REPBOOK_UNATTENDED
function Finish {
    if ($Unattended) { return }
    Write-Host ''; Read-Host 'Press Enter to close this window' | Out-Null
}
function Fail([string]$Message) {
    Write-Host ''
    Write-Host "X $Message" -ForegroundColor Red
    Write-Host '  Your workout log were not changed.'
    Finish
    exit 1
}
function Stop-ThisInstallation {
    # Python processes started from this installation's environment (matched by path, so nothing else).
    $procs = @(Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
        Where-Object { $_.ExecutablePath -and $_.ExecutablePath.StartsWith($App + '\', [StringComparison]::OrdinalIgnoreCase) })
    if ($procs.Count -eq 0) { return }
    Write-Host '-> Stopping the Rep Book that is running...'
    foreach ($p in $procs) { Stop-Process -Id $p.ProcessId -Force -ErrorAction SilentlyContinue }
    Start-Sleep -Seconds 2  # let Windows release the files before they are replaced
}

try {
    Clear-Host
    Write-Host "Rep Book $AppVersion ($(Get-Date))"
    Write-Host '------------------------------'
    $Source = $Source.TrimEnd('\')
    if (-not (Test-Path (Join-Path $Source 'pixi.toml'))) { Fail 'Open this from the unzipped Rep Book folder (its app folder is missing).' }
    New-Item -ItemType Directory -Force -Path $Bin | Out-Null

    # 1. pixi: installs the Python and packages Rep Book uses.
    $have = ''
    if (Test-Path $Pixi) { $have = (& $Pixi --version) 2>$null }
    if ($have -ne "pixi $PixiVersion") {
        Write-Host "-> Downloading pixi $PixiVersion (installs the Python packages Rep Book uses)..."
        [Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12
        $zip = Join-Path $env:TEMP "pixi-$PixiVersion.zip"
        Invoke-WebRequest -UseBasicParsing -Uri "https://github.com/prefix-dev/pixi/releases/download/v$PixiVersion/pixi-x86_64-pc-windows-msvc.zip" -OutFile $zip
        Expand-Archive -Force -Path $zip -DestinationPath $Bin
        Remove-Item $zip
    }

    # 2. An update: stop this installation's Rep Book if it's running.
    if (Test-Path $App) { Stop-ThisInstallation }

    # 3. The app's files (its environment, .pixi, is kept so an update is quick).
    Write-Host '-> Copying Rep Book...'
    robocopy $Source $App /MIR /XD (Join-Path $App '.pixi') /NFL /NDL /NJH /NJS /NP | Out-Null
    if ($LASTEXITCODE -ge 8) { Fail "Copying Rep Book's files failed (robocopy code $LASTEXITCODE)." }

    # 4. Its Python and packages.
    Write-Host "-> Installing Rep Book's Python and packages (a few minutes the first time)..."
    & $Pixi install --manifest-path (Join-Path $App 'pixi.toml') --frozen
    if ($LASTEXITCODE -ne 0) { Fail 'Installing the packages failed (see above). Check your internet connection and try again.' }

    # 5. Shortcuts: Start menu and Desktop.
    Write-Host '-> Adding Rep Book to the Start menu and Desktop...'
    $shell = New-Object -ComObject WScript.Shell
    # The shortcuts run launch.ps1 (no window), which reinstalls the packages first if they went missing
    Copy-Item -Force (Join-Path $App 'packaging\windows\launch.ps1') (Join-Path $Root 'launch.ps1')
    foreach ($dir in @([Environment]::GetFolderPath('Programs'), [Environment]::GetFolderPath('Desktop'))) {
        $link = $shell.CreateShortcut((Join-Path $dir 'Rep Book.lnk'))
        $link.TargetPath = 'powershell.exe'
        $link.Arguments = '-NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File "' + (Join-Path $Root 'launch.ps1') + '"'
        $link.WindowStyle = 7  # minimised: no console window flashes up
        $link.WorkingDirectory = $App
        $link.IconLocation = $Icon
        $link.Description = 'Open Rep Book'
        $link.Save()
    }

    # 6. Settings > Apps: an entry to uninstall it.
    Copy-Item -Force (Join-Path $App 'packaging\windows\uninstall.ps1') (Join-Path $Root 'uninstall.ps1')
    $key = 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\RepBookApp'
    New-Item -Force -Path $key | Out-Null
    $uninstall = 'powershell.exe -NoProfile -ExecutionPolicy Bypass -File "' + (Join-Path $Root 'uninstall.ps1') + '"'
    $values = @{
        DisplayName = 'Rep Book'; DisplayVersion = $AppVersion; Publisher = 'Rep Book'; InstallLocation = $Root
        DisplayIcon = $Icon; UninstallString = $uninstall
    }
    foreach ($name in $values.Keys) { Set-ItemProperty -Path $key -Name $name -Value $values[$name] }
    Set-ItemProperty -Path $key -Name NoModify -Value 1 -Type DWord
    Set-ItemProperty -Path $key -Name NoRepair -Value 1 -Type DWord

    Write-Host ''
    Write-Host "Rep Book $AppVersion is installed. Opening it in your browser..." -ForegroundColor Green
    Write-Host '  Next time, open Rep Book from the Start menu or the Desktop.'
    $launchArgs = @('-X', 'utf8', '-m', 'repbook.launch')
    if ($Unattended) { $launchArgs += '--no-browser' }
    Start-Process -FilePath $Pyw -ArgumentList $launchArgs -WorkingDirectory $App
    Start-Sleep -Seconds 3
    Finish
}
catch {
    Fail ("The installation stopped: " + $_.Exception.Message)
}
