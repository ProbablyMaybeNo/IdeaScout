#requires -Version 5.1
<#
.SYNOPSIS
    Remove IdeaScout scheduled tasks.
#>
[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"

$tasks = @("Daily Poll And Classify", "Weekly Digest")
$path  = "\IdeaScout\"

foreach ($t in $tasks) {
    $existing = Get-ScheduledTask -TaskPath $path -TaskName $t -ErrorAction SilentlyContinue
    if ($existing) {
        Unregister-ScheduledTask -TaskPath $path -TaskName $t -Confirm:$false
        Write-Host "Unregistered: $path$t"
    } else {
        Write-Host "Not found:    $path$t"
    }
}

# Try to remove the empty IdeaScout folder if no other tasks remain.
try {
    $sched = New-Object -ComObject "Schedule.Service"
    $sched.Connect()
    $folder = $sched.GetFolder("\")
    $folder.DeleteFolder("IdeaScout", 0)
    Write-Host "Removed task folder: \IdeaScout\"
} catch {
    # Folder not empty or doesn't exist — ignore.
}
