[CmdletBinding()]
param([switch]$NoBuild)
$ErrorActionPreference='Stop'
$jenkinsLabRoot = Split-Path -Parent $PSScriptRoot
$jenkinsLabPython = (Get-Command python -ErrorAction Stop).Source
$jenkinsLabSavedEnv=@{}
foreach($jenkinsLabEnvName in @('TEMP','TMP','PYTHONPYCACHEPREFIX')) { $jenkinsLabSavedEnv[$jenkinsLabEnvName]=[Environment]::GetEnvironmentVariable($jenkinsLabEnvName,'Process') }
Push-Location -LiteralPath $jenkinsLabRoot
try {
    New-Item -ItemType Directory -Path '.local\tmp' -Force | Out-Null
    $env:TEMP=Join-Path $jenkinsLabRoot '.local\tmp'
    $env:TMP=$env:TEMP
    $env:PYTHONPYCACHEPREFIX=Join-Path $jenkinsLabRoot '.local\pycache'
    & $jenkinsLabPython scripts/init_env.py
    if($LASTEXITCODE -ne 0){throw 'Private lab initialization failed.'}
    docker info --format '{{.ServerVersion}}'
    if($LASTEXITCODE -ne 0){throw 'Start Docker Desktop with Linux containers first.'}
    if(-not $NoBuild){
        foreach($jenkinsLabService in @('controller','agent','engine')){
            docker compose -p jenkins-release-lab build $jenkinsLabService
            if($LASTEXITCODE -ne 0){throw "Image build failed: $jenkinsLabService"}
        }
    }
    docker compose -p jenkins-release-lab up -d engine controller
    if($LASTEXITCODE -ne 0){throw 'Controller/engine startup failed.'}
    & $jenkinsLabPython scripts/bootstrap.py --timeout 600
    if($LASTEXITCODE -ne 0){throw 'Jenkins bootstrap failed.'}
    docker compose -p jenkins-release-lab up -d --no-deps agent
    if($LASTEXITCODE -ne 0){throw 'Agent startup failed.'}
    & $jenkinsLabPython scripts/bootstrap.py --wait-agent --timeout 300
    if($LASTEXITCODE -ne 0){throw 'The dedicated build agent did not connect.'}
    Write-Output 'Jenkins: http://127.0.0.1:8110/ | API gateway after a deployment: http://127.0.0.1:8111'
    Write-Output 'Read .local/LOCAL-CREDENTIALS.txt privately. Open the reserveflow-release job and choose Build with Parameters.'
} finally {
    Pop-Location
    foreach($jenkinsLabEnvName in $jenkinsLabSavedEnv.Keys){[Environment]::SetEnvironmentVariable($jenkinsLabEnvName,$jenkinsLabSavedEnv[$jenkinsLabEnvName],'Process')}
}
