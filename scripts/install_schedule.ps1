#requires -Version 5.1
<#
.SYNOPSIS
    Register IdeaScout daily poll/classify and weekly digest tasks in Windows Task Scheduler.

.DESCRIPTION
    Creates two scheduled tasks under \IdeaScout\:
      • Daily Poll And Classify -- runs every day at 06:00 local
      • Weekly Digest -- runs every Friday at 07:00 local (stub until Day 3)

    Tasks run as the current interactive user. The DB and Ollama both live
    in user space, so no admin elevation is required at runtime.

    Idempotent: re-running replaces existing tasks of the same name.

.PARAMETER PollHour
    Hour of day (0-23) for the daily poll/classify run. Default 6.

.PARAMETER DigestHour
    Hour of day (0-23) for the Friday digest run. Default 7.

.PARAMETER DigestDayOfWeek
    Day of the week for the digest run. Default Friday.

.EXAMPLE
    .\scripts\install_schedule.ps1
    .\scripts\install_schedule.ps1 -PollHour 7 -DigestHour 8

.NOTES
    Run from PowerShell (does not require admin). To uninstall, use
    scripts\uninstall_schedule.ps1.
#>
[CmdletBinding()]
param(
    [int]   $PollHour       = 6,
    [int]   $DigestHour     = 7,
    [string]$DigestDayOfWeek = "Friday"
)

$ErrorActionPreference = "Stop"

$scriptDir   = Split-Path -Parent $MyInvocation.MyCommand.Path
$projectRoot = Resolve-Path (Join-Path $scriptDir "..")
$pollBat     = Join-Path $scriptDir "run_poll_classify.bat"
$digestBat   = Join-Path $scriptDir "run_digest.bat"

if (-not (Test-Path $pollBat))   { throw "Missing $pollBat" }
if (-not (Test-Path $digestBat)) { throw "Missing $digestBat" }

# Identify current user in the form the scheduler expects.
$user = "$env:USERDOMAIN\$env:USERNAME"

function Register-IdeaScoutTask {
    param(
        [Parameter(Mandatory)] [string]                   $TaskName,
        [Parameter(Mandatory)] [string]                   $Description,
        [Parameter(Mandatory)] [string]                   $BatPath,
        [Parameter(Mandatory)] $Trigger
    )

    $action = New-ScheduledTaskAction `
        -Execute $BatPath `
        -WorkingDirectory $projectRoot

    $principal = New-ScheduledTaskPrincipal `
        -UserId      $user `
        -LogonType   Interactive `
        -RunLevel    Limited

    $settings = New-ScheduledTaskSettingsSet `
        -AllowStartIfOnBatteries `
        -DontStopIfGoingOnBatteries `
        -StartWhenAvailable `
        -ExecutionTimeLimit (New-TimeSpan -Hours 1) `
        -MultipleInstances IgnoreNew `
        -RestartCount 2 `
        -RestartInterval (New-TimeSpan -Minutes 5)

    Register-ScheduledTask `
        -TaskName    $TaskName `
        -TaskPath    "\IdeaScout\" `
        -Action      $action `
        -Trigger     $Trigger `
        -Principal   $principal `
        -Settings    $settings `
        -Description $Description `
        -Force | Out-Null

    Write-Host "Registered: \IdeaScout\$TaskName"
}

# --- Task 1: daily poll + classify ---
$pollTime    = (Get-Date -Hour $PollHour -Minute 0 -Second 0)
$pollTrigger = New-ScheduledTaskTrigger -Daily -At $pollTime

Register-IdeaScoutTask `
    -TaskName    "Daily Poll And Classify" `
    -Description "IdeaScout -- polls every enabled source, then classifies new posts via local Ollama (qwen2.5:14b). Logs in data\logs\." `
    -BatPath     $pollBat `
    -Trigger     $pollTrigger

# --- Task 2: weekly digest (stub until Day 3) ---
$digestTime    = (Get-Date -Hour $DigestHour -Minute 0 -Second 0)
$digestTrigger = New-ScheduledTaskTrigger -Weekly -DaysOfWeek $DigestDayOfWeek -At $digestTime

Register-IdeaScoutTask `
    -TaskName    "Weekly Digest" `
    -Description "IdeaScout -- generates Friday digest of top demand signals. STUB until Day 3." `
    -BatPath     $digestBat `
    -Trigger     $digestTrigger

Write-Host ""
Write-Host "Done. View tasks:"
Write-Host "  Get-ScheduledTask -TaskPath '\IdeaScout\'"
Write-Host ""
Write-Host "Run a task immediately for verification:"
Write-Host "  Start-ScheduledTask -TaskPath '\IdeaScout\' -TaskName 'Daily Poll And Classify'"
Write-Host ""
Write-Host "Logs land in:"
Write-Host "  $projectRoot\data\logs\"
