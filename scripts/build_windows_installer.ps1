param(
    [Parameter(Mandatory=$true)][string]$Runtime,
    [Parameter(Mandatory=$true)][string]$BuildPython,
    [Parameter(Mandatory=$true)][string]$SitePackages,
    [Parameter(Mandatory=$true)][string]$Output,
    [Parameter(Mandatory=$true)][string]$VerificationWorkspace,
    [Parameter(Mandatory=$true)][ValidatePattern('^v[0-9][0-9A-Za-z.-]{0,79}$')][string]$ReleaseTag
)
$ErrorActionPreference='Stop'
$taskRoot=Split-Path -Parent $PSScriptRoot
$taskOutput=[IO.Path]::GetFullPath($Output)
if (Test-Path -LiteralPath $taskOutput) { throw 'Use a new output directory for each build.' }
Push-Location $taskRoot
try {
    & $BuildPython -m unittest test_beta_setup test_beta_releases
    if ($LASTEXITCODE -ne 0) { throw 'Installer tests failed.' }
    & $BuildPython -m PyInstaller --noconfirm --onefile --windowed --name OpenHoikuICT --paths $taskRoot --add-data "$taskRoot/beta_setup/ui:beta_setup/ui" --distpath "$taskOutput/launcher" --workpath "$taskOutput/work" --specpath "$taskOutput/spec" beta_setup/launcher.py
    if ($LASTEXITCODE -ne 0) { throw 'Launcher build failed.' }
    & $BuildPython scripts/build_beta_bundle.py --runtime $Runtime --site-packages $SitePackages --launcher "$taskOutput/launcher/OpenHoikuICT.exe" --output "$taskOutput/bundle" --release-tag $ReleaseTag
    if ($LASTEXITCODE -ne 0) { throw 'Bundle build failed.' }
    & $BuildPython scripts/verify_beta_bundle.py --bundle "$taskOutput/bundle" --workspace $VerificationWorkspace
    if ($LASTEXITCODE -ne 0) { throw 'New installation verification failed. Do not publish.' }
    Write-Output "Verified release files: $taskOutput/bundle"
}
finally { Pop-Location }
