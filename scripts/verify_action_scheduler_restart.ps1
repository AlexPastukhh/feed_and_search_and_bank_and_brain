# Requires Windows PowerShell 5.1+ with Docker Compose and local Feedbrain API.
# This is an opt-in live test: it schedules a real Feedbrain sync.
param(
    [int]$ActionId = 1
)

$ErrorActionPreference = "Stop"
Set-Location (Split-Path -Parent $PSScriptRoot)
$base = "http://127.0.0.1:8000"
$cleanupRequired = $false

# Refuse to take over a user-managed schedule or active ActionRun.
$original = Invoke-RestMethod -Uri "$base/actions/$ActionId/schedule"
if ($original.enabled) {
    throw "Action $ActionId schedule is already enabled; refusing to modify it"
}
$before = Invoke-RestMethod -Uri "$base/actions/$ActionId/runs"
$previousIds = @{}
foreach ($run in $before) {
    if ($run.status -in @("queued", "running")) {
        throw "Action $ActionId already has an active Run"
    }
    $previousIds[[string]$run.id] = $true
}

try {
    $enableBody = @{ enabled = $true; every_minutes = 1 } | ConvertTo-Json
    # Set the flag before PUT: the server may commit even if the response fails.
    $cleanupRequired = $true
    $started = Invoke-RestMethod -Method Put -Uri "$base/actions/$ActionId/schedule" -ContentType "application/json" -Body $enableBody
    Write-Host "Enabled: next_run_at=$($started.next_run_at)"

    docker compose restart action-worker
    if ($LASTEXITCODE -ne 0) {
        throw "docker compose restart action-worker failed ($LASTEXITCODE)"
    }

    $afterRestart = Invoke-RestMethod -Uri "$base/actions/$ActionId/schedule"
    if (-not $afterRestart.enabled -or
        $afterRestart.next_run_at -ne $started.next_run_at) {
        throw "Schedule did not persist unchanged after worker restart"
    }
    Write-Host "Schedule persisted across worker restart"

    $deadline = (Get-Date).AddMinutes(3)
    $completed = $false
    do {
        Start-Sleep -Seconds 3
        # Do not wrap Invoke-RestMethod in @(...): on Windows PowerShell,
        # JSON arrays may be presented to the pipeline as one nested item.
        # foreach on the returned value enumerates runs correctly.
        $runs = Invoke-RestMethod -Uri "$base/actions/$ActionId/runs"
        $newScheduledRun = $null
        foreach ($run in $runs) {
            if ($run.initiated_by -eq "schedule" -and
                -not $previousIds.ContainsKey([string]$run.id)) {
                $newScheduledRun = $run
                break
            }
        }
        if ($null -eq $newScheduledRun) { continue }

        $runId = [int]$newScheduledRun.id
        $detail = Invoke-RestMethod -Uri "$base/action-runs/$runId"
        if ($detail.status -in @("queued", "running")) { continue }

        Write-Host "Scheduled Run=$runId, status=$($detail.status)"
        $detail.steps |
            Select-Object step_id, status, external_run_ref |
            Format-Table | Out-Host
        if ($detail.status -ne "completed") {
            throw "Scheduled Run $runId ended with status $($detail.status)"
        }
        $completed = $true
        break
    } while ((Get-Date) -lt $deadline)

    if (-not $completed) {
        throw "Scheduled Run did not complete within three minutes"
    }
    Write-Host "RESTART TEST PASSED"
}
finally {
    if ($cleanupRequired) {
        try {
            $disableBody = @{ enabled = $false } | ConvertTo-Json
            $disabled = Invoke-RestMethod -Method Put -Uri "$base/actions/$ActionId/schedule" -ContentType "application/json" -Body $disableBody
            if ($disabled.enabled -or $null -ne $disabled.next_run_at) {
                throw "Schedule still appears enabled after cleanup"
            }
            Write-Host "Cleanup: schedule disabled, next_run_at is null"
        }
        catch {
            Write-Warning "Could not confirm schedule disabled for Action $ActionId."
            Write-Warning "When API is reachable, PUT /actions/$ActionId/schedule with { enabled: false }."
            throw
        }
    }
}
