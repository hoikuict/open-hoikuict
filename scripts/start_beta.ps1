param(
    [int]$Port = 8001,
    [switch]$Reload
)

$repoRoot = Split-Path -Parent $PSScriptRoot
$envFile = Join-Path $repoRoot ".env.beta.local"
$python = Join-Path $repoRoot "venv\Scripts\python.exe"

if (-not (Test-Path -LiteralPath $envFile)) {
    throw ".env.beta.local がありません。.env.beta.example を基に作成してください。"
}
if (-not (Test-Path -LiteralPath $python)) {
    throw "仮想環境がありません: $python"
}

$uvicornArgs = @(
    "-m", "uvicorn", "main:app",
    "--host", "127.0.0.1",
    "--port", $Port.ToString(),
    "--env-file", $envFile
)
if ($Reload) {
    $uvicornArgs += "--reload"
}

Push-Location $repoRoot
try {
    & $python @uvicornArgs
}
finally {
    Pop-Location
}
