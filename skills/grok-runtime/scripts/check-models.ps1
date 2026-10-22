#Requires -Version 5.1
[CmdletBinding()]
param(
    [string]$Account='grok',
    [string]$Model,
    [switch]$Json,
    [switch]$AutoUpdate,
    [switch]$Refresh
)
$ErrorActionPreference='Stop'
$cmd = Get-Command python -ErrorAction SilentlyContinue
$pythonExe = if ($cmd) { $cmd.Source } else { Join-Path $env:LOCALAPPDATA 'Programs\Python\Python314\python.exe' }
$arguments=@((Join-Path $PSScriptRoot 'runtime.py'),'--account',$Account,'--models')
if ($Model) {
    $arguments+=@('--model',$Model)
    # Only routing, all validation remains in runtime.py.
    if ($Model -match '^grok-\d+(?:\.\d+)?-(.+)$') { $arguments+=@('--family',$Matches[1]) }
}
if ($Refresh -or $AutoUpdate) { $arguments+='--refresh' }
# Json is accepted for old callers; canonical output is always JSON.
& $pythonExe @arguments
exit $LASTEXITCODE
