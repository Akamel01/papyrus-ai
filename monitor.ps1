while ($true) {
    $timestamp = Get-Date -Format 'yyyy-MM-dd HH:mm:ss'
    $stats = docker stats --no-stream --format "{{.Name}},{{.CPUPerc}},{{.MemUsage}}"
    foreach ($line in $stats) {
        if ($line -match "sme_") {
            "$timestamp,$line" | Out-File -Append -Encoding utf8 resource_monitor.log
        }
    }
    Start-Sleep -Seconds 1
}
