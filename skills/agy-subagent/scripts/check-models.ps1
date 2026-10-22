#Requires -Version 5.1
<#
.SYNOPSIS
    Zero-token model checker and dynamic policy validator for agy CLI.
.DESCRIPTION
    Enforces project policy:
      - Flash: strictly the latest active release (currently 3.8).
      - Pro: current 3.1 is blocked. Only future releases strictly newer than current are permitted.
      - Claude: current 4.6 is blocked. Only future releases strictly newer than current (e.g. 5.x) are permitted.
      - Argon / Next-gen: permitted upon release.
#>
[CmdletBinding()]
param(
    [string]$Model,
    [switch]$Json
)

# Explicitly banned current and legacy generations
$deprecatedPatterns = @(
    '^gemini-3\.[0-7]-flash',
    '^gemini-3\.1-pro',
    '^claude-.*-4-[0-6]',
    '^gpt-oss'
)

# Active baseline permitted models
$activePatterns = @(
    '^gemini-3\.8-flash'
)

# Future generation patterns (strictly newer than current)
$newFrontierPatterns = @(
    'gemini-4',
    'argon',
    'gemini-3\.[9]',
    'gemini-[5-9]',
    'claude-.*-([5-9]|\d{2,})',
    'claude-[5-9]'
)

$raw = & agy models 2>$null
if (-not $raw) {
    Write-Error "Failed to execute 'agy models'. Ensure agy is installed and in PATH."
    exit 1
}

$catalog = @()
foreach ($line in ($raw -split "`r?`n")) {
    if ($line -match '^\s*([a-zA-Z0-9\._\-]+)\s+(.+)$' -and $line -notmatch 'Fetching available models') {
        $slug = $matches[1].Trim()
        $name = $matches[2].Trim()

        $isDeprecated = $false
        foreach ($dp in $deprecatedPatterns) {
            if ($slug -match $dp -or $name -match $dp) { $isDeprecated = $true; break }
        }

        $isActive = $false
        if (-not $isDeprecated) {
            foreach ($ap in $activePatterns) {
                if ($slug -match $ap -or $name -match $ap) { $isActive = $true; break }
            }
        }

        $isNew = $false
        if (-not $isDeprecated -and -not $isActive) {
            foreach ($np in $newFrontierPatterns) {
                if ($slug -match $np -or $name -match $np) { $isNew = $true; break }
            }
        }

        $status = if ($isDeprecated) {
            'BLOCKED'
        } elseif ($isActive) {
            'ACTIVE'
        } elseif ($isNew) {
            'NEW_FRONTIER'
        } else {
            'BLOCKED'
        }

        $catalog += [PSCustomObject]@{
            Slug        = $slug
            DisplayName = $name
            Status      = $status
        }
    }
}

if ($Model) {
    $target = $catalog | Where-Object { $_.Slug -eq $Model -or $_.DisplayName -eq $Model }
    if (-not $target) {
        Write-Host "[WARNING] Model '$Model' not found in current agy models catalog." -ForegroundColor Yellow
        exit 2
    }
    if ($target.Status -eq 'BLOCKED') {
        Write-Host "[BLOCKED] Model '$($target.DisplayName)' ($($target.Slug)) is prohibited by policy." -ForegroundColor Red
        Write-Host "Policy rule: Current Claude (<=4.6) and Pro (<=3.1) are banned. Use latest Flash or wait for strictly newer releases." -ForegroundColor Yellow
        exit 1
    }
    Write-Host "[OK] Model '$($target.DisplayName)' ($($target.Slug)) is permitted (Status: $($target.Status))." -ForegroundColor Green
    exit 0
}

$newModels = $catalog | Where-Object { $_.Status -eq 'NEW_FRONTIER' }
$activeModels = $catalog | Where-Object { $_.Status -eq 'ACTIVE' }
$blockedModels = $catalog | Where-Object { $_.Status -eq 'BLOCKED' }

$result = [PSCustomObject]@{
    Timestamp     = (Get-Date).ToString("yyyy-MM-ddTHH:mm:ssZ")
    ActiveModels  = $activeModels
    BlockedModels = $blockedModels
    NewFrontiers  = $newModels
    HasNewModels  = ($newModels.Count -gt 0)
}

if ($Json) {
    $result | ConvertTo-Json -Depth 4
    exit 0
}

Write-Host "=== AGY CLI MODEL CATALOG & DYNAMIC POLICY AUDIT (0 TOKENS) ===" -ForegroundColor Cyan
Write-Host "Audited at: $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')`n"

Write-Host "Active & Permitted Models (Latest in Family):" -ForegroundColor Green
foreach ($m in $activeModels) {
    Write-Host "  [OK]      $($m.Slug.PadRight(26)) - $($m.DisplayName)" -ForegroundColor Green
}

Write-Host "`nBlocked Models (Legacy / Current 4.6 Claude / Current 3.1 Pro):" -ForegroundColor Red
foreach ($m in $blockedModels) {
    Write-Host "  [BLOCKED] $($m.Slug.PadRight(26)) - $($m.DisplayName)" -ForegroundColor DarkGray
}

if ($result.HasNewModels) {
    Write-Host "`n[!] NEW GENERATION MODELS DETECTED (STRICTLY NEWER):" -ForegroundColor Yellow
    foreach ($m in $newModels) {
        Write-Host "  [NEW]     $($m.Slug.PadRight(26)) - $($m.DisplayName)" -ForegroundColor Yellow
    }
} else {
    Write-Host "`n[OK] No unclassified newer models. Active workhorse is Gemini 3.8 Flash." -ForegroundColor Green
}
