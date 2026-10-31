[CmdletBinding()]
param()
$ErrorActionPreference='Stop'
$jenkinsLabRoot=Split-Path -Parent $PSScriptRoot
Push-Location -LiteralPath $jenkinsLabRoot
try {
    docker compose -p jenkins-release-lab down
    if($LASTEXITCODE -ne 0){throw 'Stopping the lab failed.'}
    Write-Output 'Jenkins lab stopped. Controller history, engine images, release state and database volumes are preserved.'
} finally { Pop-Location }
