# Opens Rep Book (what the Start menu and Desktop shortcuts run, without a window): starts it in the
# background if needed, then opens it in the browser. If its Python went missing (an interrupted update, a
# clean-up tool), the packages are reinstalled first, in a window that shows the progress.
$ErrorActionPreference = 'Stop'
$Root = Join-Path $env:LOCALAPPDATA 'RepBook-app'
$App = Join-Path $Root 'app'
$Pixi = Join-Path $Root 'bin\pixi.exe'
$Pyw = Join-Path $App '.pixi\envs\default\pythonw.exe'

if (-not (Test-Path $Pyw)) {
    $repair = "Write-Host 'Rep Book: finishing the installation (a few minutes)...'; " +
              "& '$Pixi' install --manifest-path '$(Join-Path $App 'pixi.toml')' --frozen"
    Start-Process powershell.exe -ArgumentList '-NoProfile', '-Command', $repair -Wait
    if (-not (Test-Path $Pyw)) {
        Add-Type -AssemblyName PresentationFramework
        [System.Windows.MessageBox]::Show("Rep Book couldn't finish installing. Check your internet connection, " +
            "then run the installer again.", 'Rep Book') | Out-Null
        exit 1
    }
}
$launchArgs = @('-X', 'utf8', '-m', 'repbook.launch') + $args
Start-Process -FilePath $Pyw -ArgumentList $launchArgs -WorkingDirectory $App
