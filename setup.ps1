#Requires -Version 5.1
<#
.SYNOPSIS
    Universal Multi-Account Provisioner for Antigravity CLI, Codex CLI, and Grok CLI.
.DESCRIPTION
    Interactively provisions isolated environments, binary patches, launcher wrappers,
    and agent skills for agy, codex, and grok without fixed limits or personal presets.
#>

$ErrorActionPreference = "Stop"

Write-Host "=======================================================" -ForegroundColor Cyan
Write-Host "   Multi-Account Subagent Provisioner" -ForegroundColor Cyan
Write-Host "   (Antigravity CLI / Codex CLI / Grok CLI)" -ForegroundColor Cyan
Write-Host "=======================================================`n" -ForegroundColor Cyan

function Ask-Count {
    param(
        [string]$Question,
        [int]$Default = 1,
        [int]$Min = 1,
        [int]$Max = 9
    )
    while ($true) {
        $ans = Read-Host "$Question ($Min-$Max, default: $Default)"
        if ([string]::IsNullOrWhiteSpace($ans)) {
            return $Default
        }
        if ($ans -match '^\s*(\d+)\s*$') {
            $val = [int]$matches[1]
            if ($val -ge $Min -and $val -le $Max) {
                return $val
            }
        }
        Write-Host "  [!] Please enter a number between $Min and $Max (or press Enter for $Default)." -ForegroundColor Yellow
    }
}

$agyCount   = Ask-Count -Question "How many isolated agy CLIs do you need?"   -Default 1 -Min 1 -Max 9
$codexCount = Ask-Count -Question "How many isolated codex CLIs do you need?" -Default 1 -Min 1 -Max 9
$grokCount  = Ask-Count -Question "How many isolated grok CLIs do you need?"  -Default 1 -Min 1 -Max 9

Write-Host "`nConfiguration:" -ForegroundColor Cyan
Write-Host "  - Antigravity CLI (agy) : $agyCount environment(s)" -ForegroundColor White
Write-Host "  - OpenAI Codex CLI      : $codexCount environment(s)" -ForegroundColor White
Write-Host "  - Grok CLI              : $grokCount environment(s)`n" -ForegroundColor White

# Resolve common bin directory (guaranteed on PATH for agy users)
$binDir = "$env:LOCALAPPDATA\agy\bin"
if (-not (Test-Path $binDir)) {
    $foundAgy = Get-Command "agy.exe" -ErrorAction SilentlyContinue
    if ($foundAgy) {
        $binDir = Split-Path -Parent $foundAgy.Source
    } else {
        New-Item -ItemType Directory -Path $binDir -Force | Out-Null
    }
}

# ==============================================================================
# 1. Antigravity CLI Provisioning
# ==============================================================================
Write-Host "[1/4] Configuring Antigravity CLI (agy) environments..." -ForegroundColor Yellow

$baseAgyExe = Join-Path $binDir "agy.exe"
if (-not (Test-Path $baseAgyExe)) {
    $cmd = Get-Command "agy.exe" -ErrorAction SilentlyContinue
    if ($cmd) { $baseAgyExe = $cmd.Source }
}

if (-not (Test-Path $baseAgyExe)) {
    Write-Host "      [-] agy.exe not found in '$binDir' or PATH. Skipping binary patch." -ForegroundColor DarkGray
} else {
    Write-Host "      [+] Base binary: $baseAgyExe" -ForegroundColor Green

    # Stop running agy background processes
    Get-Process -Name "agy*" -ErrorAction SilentlyContinue | ForEach-Object {
        Stop-Process -Id $_.Id -Force -ErrorAction SilentlyContinue
    }
    Start-Sleep -Milliseconds 250

    if ($agyCount -gt 1) {
        Add-Type -TypeDefinition @"
using System;
public static class AgyPatcher {
    public static int FindBytes(byte[] src, byte[] pattern, int startIdx = 0) {
        int max = src.Length - pattern.Length;
        for (int i = startIdx; i <= max; i++) {
            if (src[i] == pattern[0]) {
                bool match = true;
                for (int j = 1; j < pattern.Length; j++) {
                    if (src[i + j] != pattern[j]) { match = false; break; }
                }
                if (match) return i;
            }
        }
        return -1;
    }
}
"@ -ErrorAction SilentlyContinue

        $bytes = [System.IO.File]::ReadAllBytes($baseAgyExe)
        $marker = [System.Text.Encoding]::ASCII.GetBytes("stream-jsonantigravity")
        $idx = [AgyPatcher]::FindBytes($bytes, $marker)

        if ($idx -eq -1) {
            Write-Host "      [!] Keyring marker not found in $baseAgyExe. Skipping binary patch." -ForegroundColor Yellow
        } else {
            $keyOffset = $idx + 11
            for ($i = 2; $i -le $agyCount; $i++) {
                $destExe = Join-Path $binDir "agy$i.exe"
                $newKey = [System.Text.Encoding]::ASCII.GetBytes("antigravit$i")
                $patchedBytes = [byte[]]$bytes.Clone()
                for ($k = 0; $k -lt 11; $k++) {
                    $patchedBytes[$keyOffset + $k] = $newKey[$k]
                }
                [System.IO.File]::WriteAllBytes($destExe, $patchedBytes)
                Write-Host "      [+] Created binary: agy$i.exe (Credential target: gemini:antigravit$i)" -ForegroundColor Green

                # Launcher wrapper
                $cmdPath = Join-Path $binDir "agy$i.cmd"
                $cmdContent = @"
@echo off
setlocal
set "AG_LS_PROXY="
set "AGY${i}_EXE=%LOCALAPPDATA%\agy\bin\agy${i}.exe"
set "AGY_CLI_DISABLE_AUTO_UPDATE=1"
set "AGY${i}_HOME=%USERPROFILE%\.profiles\agy${i}"
if not exist "%AGY${i}_HOME%" mkdir "%AGY${i}_HOME%"
if not exist "%AGY${i}_HOME%\AppData\Local" mkdir "%AGY${i}_HOME%\AppData\Local"
if not exist "%AGY${i}_HOME%\AppData\Roaming" mkdir "%AGY${i}_HOME%\AppData\Roaming"
set "USERPROFILE=%AGY${i}_HOME%"
set "HOME=%AGY${i}_HOME%"
set "HOMEDRIVE=%AGY${i}_HOME:~0,2%"
set "HOMEPATH=%AGY${i}_HOME:~2%"
set "APPDATA=%AGY${i}_HOME%\AppData\Roaming"
set "LOCALAPPDATA=%AGY${i}_HOME%\AppData\Local"
set "ANTIGRAVITY_GEMINI_DIR=%AGY${i}_HOME%\.gemini"
"%AGY${i}_EXE%" %*
endlocal
"@
                Set-Content -Path $cmdPath -Value $cmdContent -Encoding ASCII
                Write-Host "      [+] Created launcher: agy$i.cmd" -ForegroundColor Green

                # Home directory tree
                $p = "$env:USERPROFILE\.profiles\agy$i"
                New-Item -ItemType Directory -Path (Join-Path $p "AppData\Local") -Force | Out-Null
                New-Item -ItemType Directory -Path (Join-Path $p "AppData\Roaming") -Force | Out-Null
                New-Item -ItemType Directory -Path (Join-Path $p ".gemini") -Force | Out-Null
            }
        }
    }
}

# ==============================================================================
# 2. OpenAI Codex CLI Provisioning
# ==============================================================================
Write-Host "`n[2/4] Configuring Codex CLI environments..." -ForegroundColor Yellow

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path

# Always create main codex-runtime launcher
$codexRuntimeCmd = Join-Path $binDir "codex-runtime.cmd"
$codexRuntimeContent = @"
@echo off
setlocal
python "%USERPROFILE%\.gemini\config\skills\codex-runtime\scripts\cli.py" %*
set "RUNTIME_EXIT=%ERRORLEVEL%"
endlocal & exit /b %RUNTIME_EXIT%
"@
Set-Content -Path $codexRuntimeCmd -Value $codexRuntimeContent -Encoding ASCII
Write-Host "      [+] Created launcher: codex-runtime.cmd" -ForegroundColor Green

# Default account ~/.codex
$defaultCodexDir = "$env:USERPROFILE\.codex"
if (-not (Test-Path $defaultCodexDir)) {
    New-Item -ItemType Directory -Path $defaultCodexDir -Force | Out-Null
}

if ($codexCount -gt 1) {
    for ($i = 2; $i -le $codexCount; $i++) {
        $codexHome = "$env:USERPROFILE\.codex$i"
        if (-not (Test-Path $codexHome)) {
            New-Item -ItemType Directory -Path $codexHome -Force | Out-Null
        }
        $cmdPath = Join-Path $binDir "codex$i.cmd"
        $cmdContent = @"
@echo off
setlocal
python "%USERPROFILE%\.gemini\config\skills\codex-runtime\scripts\cli.py" --account codex${i} %*
set "RUNTIME_EXIT=%ERRORLEVEL%"
endlocal & exit /b %RUNTIME_EXIT%
"@
        Set-Content -Path $cmdPath -Value $cmdContent -Encoding ASCII
        Write-Host "      [+] Created launcher: codex$i.cmd (storage: ~/.codex$i)" -ForegroundColor Green
    }
}

# ==============================================================================
# 3. Grok CLI Provisioning
# ==============================================================================
Write-Host "`n[3/4] Configuring Grok CLI environments..." -ForegroundColor Yellow

# Always create main grok-runtime launcher
$grokRuntimeCmd = Join-Path $binDir "grok-runtime.cmd"
$grokRuntimeContent = @"
@echo off
setlocal
python "%USERPROFILE%\.gemini\config\skills\grok-runtime\scripts\cli.py" %*
set "RUNTIME_EXIT=%ERRORLEVEL%"
endlocal & exit /b %RUNTIME_EXIT%
"@
Set-Content -Path $grokRuntimeCmd -Value $grokRuntimeContent -Encoding ASCII
Write-Host "      [+] Created launcher: grok-runtime.cmd" -ForegroundColor Green

# Default account ~/.grok
$defaultGrokDir = "$env:USERPROFILE\.grok"
if (-not (Test-Path $defaultGrokDir)) {
    New-Item -ItemType Directory -Path $defaultGrokDir -Force | Out-Null
}

if ($grokCount -gt 1) {
    for ($i = 2; $i -le $grokCount; $i++) {
        $grokHome = "$env:USERPROFILE\.grok$i"
        if (-not (Test-Path $grokHome)) {
            New-Item -ItemType Directory -Path $grokHome -Force | Out-Null
        }
        $cmdPath = Join-Path $binDir "grok$i.cmd"
        $cmdContent = @"
@echo off
setlocal
python "%USERPROFILE%\.gemini\config\skills\grok-runtime\scripts\cli.py" --account grok${i} %*
set "RUNTIME_EXIT=%ERRORLEVEL%"
endlocal & exit /b %RUNTIME_EXIT%
"@
        Set-Content -Path $cmdPath -Value $cmdContent -Encoding ASCII
        Write-Host "      [+] Created launcher: grok$i.cmd (storage: ~/.grok$i)" -ForegroundColor Green
    }
}

# ==============================================================================
# 4. Deploy Skills to ~/.gemini/config/skills/
# ==============================================================================
Write-Host "`n[4/4] Deploying skills to ~/.gemini/config/skills/..." -ForegroundColor Yellow
$skillsSourceDir = Join-Path $scriptDir "skills"
$skillsDestBase = "$env:USERPROFILE\.gemini\config\skills"

if (Test-Path $skillsSourceDir) {
    if (Test-Path "$skillsDestBase\grok") {
        Remove-Item -Path "$skillsDestBase\grok" -Recurse -Force -ErrorAction SilentlyContinue
    }
    Get-ChildItem -Path $skillsSourceDir -Directory | ForEach-Object {
        $skillName = $_.Name
        $targetDir = Join-Path $skillsDestBase $skillName
        New-Item -ItemType Directory -Path $targetDir -Force | Out-Null
        Copy-Item -Path "$($_.FullName)\*" -Destination $targetDir -Recurse -Force
        Write-Host "      [+] Skill '$skillName' deployed to $targetDir" -ForegroundColor Green
    }
} else {
    Write-Host "      [-] Skills directory not found locally; skipping skill deployment." -ForegroundColor DarkGray
}

# ==============================================================================
# Status Report & Next Steps
# ==============================================================================
Write-Host "`n=======================================================" -ForegroundColor Cyan
Write-Host "   Environment Status & Authentication" -ForegroundColor Cyan
Write-Host "=======================================================" -ForegroundColor Cyan

# Windows Credential Manager check for agy
$wcmEntries = cmdkey /list 2>&1 | Out-String
$p1Auth = $wcmEntries -match "gemini:antigravity"
$p1Text = if ($p1Auth) { "[READY] Authenticated (gemini:antigravity)" } else { "[PENDING] Requires login: run 'agy'" }
$p1Color = if ($p1Auth) { "Green" } else { "Yellow" }
Write-Host "  - agy (Primary)     : $p1Text" -ForegroundColor $p1Color

if ($agyCount -gt 1) {
    for ($i = 2; $i -le $agyCount; $i++) {
        $targetName = "gemini:antigravit$i"
        $isAuth = $wcmEntries -match $targetName
        $statusText = if ($isAuth) { "[READY] Authenticated ($targetName)" } else { "[PENDING] Requires login: run 'agy$i'" }
        $statusColor = if ($isAuth) { "Green" } else { "Yellow" }
        Write-Host "  - agy$i               : $statusText" -ForegroundColor $statusColor
    }
}

if ($codexCount -gt 1) {
    Write-Host "`n  Codex CLI environments (~/.codex2 .. ~/.codex$codexCount):" -ForegroundColor White
    for ($i = 2; $i -le $codexCount; $i++) {
        Write-Host "    Launcher: codex$i  (to authenticate: codex$i login)" -ForegroundColor DarkGray
    }
}

if ($grokCount -gt 1) {
    Write-Host "`n  Grok CLI environments (~/.grok2 .. ~/.grok$grokCount):" -ForegroundColor White
    for ($i = 2; $i -le $grokCount; $i++) {
        Write-Host "    Launcher: grok$i   (to authenticate: grok$i login)" -ForegroundColor DarkGray
    }
}

Write-Host "`n[DONE] All requested environments successfully configured.`n" -ForegroundColor Green
