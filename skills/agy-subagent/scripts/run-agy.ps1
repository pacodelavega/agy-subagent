#Requires -Version 5.1
<#
.SYNOPSIS
    Unified launcher for Antigravity CLI pool (agy, agy2..agy5).
.PARAMETER Profile
    Profile index 1 to 5. 1=agy, 2=agy2, 3=agy3, 4=agy4, 5=agy5. Default is 1.
.PARAMETER Mode
    Execution mode: 'plan' (read-only review) or 'accept-edits' (code modifications). Default: 'plan'.
.PARAMETER Effort
    Reasoning effort: 'low', 'medium', 'high', 'xhigh', 'max'.
.PARAMETER Model
    Model slug (e.g. gemini-3.8-flash-high, claude-sonnet-4-6).
.PARAMETER Task
    Prompt / task text to run.
.PARAMETER ConversationId
    Resume conversation by ID.
.PARAMETER RawOutput
    Output raw JSON without ConvertFrom-Json.
#>
[CmdletBinding()]
param(
    [ValidateRange(1, 5)]
    [int]$Profile = 1,

    [ValidateSet('plan', 'accept-edits')]
    [string]$Mode = 'plan',

    [ValidateSet('low', 'medium', 'high', 'xhigh', 'max')]
    [string]$Effort,

    [string]$Model,

    [Parameter(Mandatory = $true)]
    [string]$Task,

    [string]$ConversationId,

    [switch]$RawOutput
)

$cmdName = if ($Profile -eq 1) { 'agy' } else { "agy$Profile" }

$argsList = @(
    '--mode', $Mode,
    '--dangerously-skip-permissions',
    '--output-format', 'json'
)

if ($Effort) {
    $argsList += @('--effort', $Effort)
}

if ($Model) {
    $argsList += @('--model', $Model)
}

if ($ConversationId) {
    $argsList += @('--conversation', $ConversationId)
}

$argsList += @('-p', $Task)

$raw = & $cmdName @argsList
if ($RawOutput) {
    return $raw
}

try {
    return ($raw | ConvertFrom-Json)
} catch {
    return $raw
}
