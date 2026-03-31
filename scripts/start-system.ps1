<#
.SYNOPSIS
    Robust Startup Script for SME Research Assistant
.DESCRIPTION
    Bootstraps the Docker containers while aggressively pruning old caches
    to prevent WSL memory corruption, and securely forces Cloudflare edge
    synchronization to eliminate Ghost Tunnels.
#>

Write-Host "=== SME Application Launcher ===" -ForegroundColor Cyan
Write-Host "1. Pruning stale Docker images to prevent WSL Ext4 Corruption..." -ForegroundColor Yellow
docker builder prune -a -f --filter "until=168h"

Write-Host "`n2. Starting Docker Services safely..." -ForegroundColor Yellow
docker-compose up -d --remove-orphans

Write-Host "`n3. Forcing Cloudflare DNS Route Synchronization for papyrus-ai.net..." -ForegroundColor Yellow
# Overwrite any DNS CNAMEs dynamically with our local Tunnel UUID
.\cloudflared.exe tunnel route dns -f papyrus-tunnel papyrus-ai.net
.\cloudflared.exe tunnel route dns -f papyrus-tunnel "*.papyrus-ai.net"

Write-Host "`n=== System Online and fully synchronized ===" -ForegroundColor Green
Write-Host "Local UI: http://localhost:8080/chat"
Write-Host "Public UI: https://papyrus-ai.net/chat"
