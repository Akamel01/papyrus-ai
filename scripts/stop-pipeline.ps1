<#
.SYNOPSIS
    Safe Pipeline Stop Script for SME Research Assistant
.DESCRIPTION
    Sends a graceful stop request to the internal Pipeline API inside the 
    sme_app container. Prevents cascading container failures caused by 
    abrupt process termination (pkill).
#>

param(
    [switch]$Force = $false
)

Write-Host "=== SME Pipeline Shutdown ===" -ForegroundColor Cyan

$payload = @{
    force = $Force
    user_id = "admin_cli"
} | ConvertTo-Json

Write-Host "Sending stop request to sme_app:8000 (Force: $Force)..." -ForegroundColor Yellow

# Use docker exec to hit the internal API
docker exec sme_app curl -s -X POST http://localhost:8000/stop `
    -H "Content-Type: application/json" `
    -d "$($payload -replace '"', '\"')"

Write-Host "`nStop request sent. The pipeline watchdog will now reconcile the state." -ForegroundColor Green
Write-Host "Use 'docker logs -f sme_app' to monitor the shutdown progress."
