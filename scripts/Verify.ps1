[CmdletBinding()]
param()
$ErrorActionPreference='Stop'
$jenkinsLabRoot=Split-Path -Parent $PSScriptRoot
$jenkinsLabPython=(Get-Command python -ErrorAction Stop).Source
$jenkinsLabSavedEnv=@{}
foreach($jenkinsLabEnvName in @('TEMP','TMP','PYTHONPYCACHEPREFIX')){$jenkinsLabSavedEnv[$jenkinsLabEnvName]=[Environment]::GetEnvironmentVariable($jenkinsLabEnvName,'Process')}
Push-Location -LiteralPath $jenkinsLabRoot
try {
    New-Item -ItemType Directory -Path '.local\tmp' -Force | Out-Null
    $env:TEMP=Join-Path $jenkinsLabRoot '.local\tmp'
    $env:TMP=$env:TEMP
    $env:PYTHONPYCACHEPREFIX=Join-Path $jenkinsLabRoot '.local\pycache'
    & $jenkinsLabPython -m unittest discover -s tests -v
    if($LASTEXITCODE -ne 0){throw 'Release engine tests failed.'}
    & $jenkinsLabPython scripts/verify_jenkins.py --timeout 1800
    if($LASTEXITCODE -ne 0){throw 'The actual Jenkins scenario verification failed.'}
} finally {
    Pop-Location
    foreach($jenkinsLabEnvName in $jenkinsLabSavedEnv.Keys){[Environment]::SetEnvironmentVariable($jenkinsLabEnvName,$jenkinsLabSavedEnv[$jenkinsLabEnvName],'Process')}
}
