import { useEffect, useState } from 'react'
import {
    FileSearch, Download, Cpu, Database, AlertTriangle, Activity,
    Zap, Thermometer
} from 'lucide-react'
import { db, qdrant, run, metrics } from '../lib/api'
import { dashboardWS } from '../lib/websocket'

/* =================== Metric Tile =================== */
function MetricTile({ label, value, icon: Icon, status = 'ok' }: {
    label: string; value: string | number; icon: React.ElementType; status?: string
}) {
    const borderColor = status === 'warn' ? 'var(--color-warning)'
        : status === 'crit' ? 'var(--color-error)' : 'var(--color-border)'
    return (
        <div className="card-compact flex items-center gap-3 min-w-0" style={{ borderColor }}>
            <div className="w-9 h-9 rounded-lg flex items-center justify-center shrink-0"
                style={{ background: 'var(--color-bg-elevated)' }}>
                <Icon size={16} style={{ color: 'var(--color-accent)' }} />
            </div>
            <div className="min-w-0">
                <div className="text-xs truncate" style={{ color: 'var(--color-text-secondary)' }}>{label}</div>
                <div className="text-lg font-semibold tabular-nums">{typeof value === 'number' ? value.toLocaleString() : value}</div>
            </div>
        </div>
    )
}

/* =================== Gauge =================== */
function Gauge({ label, value, max, unit, warn, crit }: {
    label: string; value: number; max: number; unit: string; warn: number; crit: number
}) {
    const pct = Math.min(value / max * 100, 100)
    const color = pct >= crit ? 'var(--color-error)' : pct >= warn ? 'var(--color-warning)' : 'var(--color-accent)'
    const r = 36; const c = 2 * Math.PI * r; const offset = c * (1 - pct / 100)

    return (
        <div className="flex flex-col items-center gap-1">
            <svg width="86" height="86" viewBox="0 0 86 86">
                <circle cx="43" cy="43" r={r} fill="none" stroke="var(--color-bg-elevated)" strokeWidth="7" />
                <circle cx="43" cy="43" r={r} fill="none" stroke={color} strokeWidth="7"
                    strokeDasharray={c} strokeDashoffset={offset}
                    strokeLinecap="round" transform="rotate(-90 43 43)"
                    style={{ transition: 'stroke-dashoffset 0.6s ease' }} />
                <text x="43" y="40" textAnchor="middle" fill="var(--color-text-primary)" fontSize="15" fontWeight="600">
                    {Math.round(pct)}%
                </text>
                <text x="43" y="54" textAnchor="middle" fill="var(--color-text-muted)" fontSize="9">
                    {unit}
                </text>
            </svg>
            <span className="text-xs" style={{ color: 'var(--color-text-secondary)' }}>{label}</span>
        </div>
    )
}

/* =================== Dashboard Page =================== */
export default function Dashboard() {
    const [counts, setCounts] = useState<Record<string, number>>({})
    const [qStats, setQStats] = useState<{ vectors_count: number; status: string; stale: boolean }>({ vectors_count: 0, status: 'unknown', stale: false })
    const [runStatus, setRunStatus] = useState<{ running: boolean; mode?: string; uptime_sec?: number }>({ running: false })
    const [sysMetrics, setSysMetrics] = useState<{ cpu_pct: number; ram_pct: number; disk_free_gb: number; disk_total_gb?: number; gpu?: { util_pct: number; vram_used_mb: number; vram_total_mb: number; temp_c: number } }>({ cpu_pct: 0, ram_pct: 0, disk_free_gb: 0 })
    const [proj, setProj] = useState<{ mean_per_day: number; rate_per_hr: number }>({ mean_per_day: 0, rate_per_hr: 0 })

    useEffect(() => {
        // Initial fetch
        db.counts().then(setCounts).catch(() => { })
        qdrant.stats().then(setQStats).catch(() => { })
        run.status().then(setRunStatus).catch(() => { })
        metrics.system().then(setSysMetrics).catch(() => { })
        metrics.projection().then(setProj).catch(() => { })

        // WebSocket push
        const unsubs = [
            dashboardWS.on('metrics.update', (p: unknown) => {
                const data = p as any;
                setSysMetrics(data);
                if (data.counts) setCounts(data.counts);
            }),
            dashboardWS.on('counts.update', (p: unknown) => setCounts(p as typeof counts)),
        ]

        // Poll less-frequent data (Reduced to 3s per user request)
        const interval = setInterval(() => {
            db.counts().then(setCounts).catch(() => { })
            qdrant.stats().then(setQStats).catch(() => { })
            run.status().then(setRunStatus).catch(() => { })
            metrics.projection().then(setProj).catch(() => { })
        }, 3000)

        return () => { unsubs.forEach(fn => fn()); clearInterval(interval) }
    }, [])

    const uptime = runStatus.uptime_sec
        ? `${Math.floor(runStatus.uptime_sec / 3600)}h ${Math.floor((runStatus.uptime_sec % 3600) / 60)}m`
        : '—'

    const errorCount = (counts.failed_download || 0) + (counts.failed_parse || 0) + (counts.failed_storage || 0)
    const totalProcessed = (counts.discovered || 0) + (counts.embedded || 0)
    const errorRate = totalProcessed > 0 ? ((errorCount / totalProcessed) * 100).toFixed(1) : '0.0'

    return (
        <div className="space-y-4">
            {/* Status Bar */}
            <div className="card-compact flex items-center justify-between">
                <div className="flex items-center gap-4">
                    <span className={`status-badge ${runStatus.running ? 'status-running' : 'status-stopped'}`}>
                        <span className={`w-2 h-2 rounded-full ${runStatus.running ? 'bg-emerald-500 pulse-dot' : 'bg-slate-500'}`} />
                        {runStatus.running ? 'Running' : 'Stopped'}
                    </span>
                    {runStatus.running && (
                        <>
                            <span className="text-xs" style={{ color: 'var(--color-text-secondary)' }}>
                                Mode: <span className="font-mono">{runStatus.mode || '—'}</span>
                            </span>
                            <span className="text-xs" style={{ color: 'var(--color-text-secondary)' }}>
                                Uptime: {uptime}
                            </span>
                        </>
                    )}
                </div>
                <span className="text-xs" style={{ color: 'var(--color-text-muted)' }}>
                    Qdrant: <span style={{ color: qStats.status === 'green' ? 'var(--color-success)' : 'var(--color-warning)' }}>
                        {qStats.status}
                    </span>
                    {qStats.stale && <span style={{ color: 'var(--color-warning)' }}> (stale)</span>}
                </span>
            </div>

            {/* KPI Tiles */}
            <div className="grid grid-cols-2 lg:grid-cols-4 xl:grid-cols-6 gap-3">
                <MetricTile label="Discovered" value={counts.discovered || 0} icon={FileSearch} />
                <MetricTile label="Downloaded" value={counts.downloaded || 0} icon={Download} />
                <MetricTile label="Embedded" value={counts.embedded || 0} icon={Cpu} />
                <MetricTile label="Vectors" value={qStats.vectors_count} icon={Database} />
                <MetricTile label="Papers/Day" value={proj.mean_per_day} icon={Zap} />
                <MetricTile label="Error Rate" value={`${errorRate}%`} icon={AlertTriangle}
                    status={parseFloat(errorRate) > 5 ? 'crit' : parseFloat(errorRate) > 1 ? 'warn' : 'ok'} />
            </div>

            {/* Gauges */}
            <div className="card-compact">
                <div className="text-xs font-medium mb-3" style={{ color: 'var(--color-text-secondary)' }}>System Resources</div>
                <div className="flex items-center justify-around flex-wrap gap-4">
                    <Gauge label="CPU" value={sysMetrics.cpu_pct} max={100} unit="%" warn={85} crit={95} />
                    <Gauge label="RAM" value={sysMetrics.ram_pct} max={100} unit="%" warn={90} crit={95} />
                    <Gauge label="Disk" value={sysMetrics.disk_total_gb ? ((sysMetrics.disk_total_gb - sysMetrics.disk_free_gb) / sysMetrics.disk_total_gb * 100) : 0} max={100} unit="%" warn={80} crit={90} />
                    {sysMetrics.gpu && (
                        <Gauge
                            label="VRAM"
                            value={sysMetrics.gpu.vram_used_mb}
                            max={sysMetrics.gpu.vram_total_mb}
                            unit={`${Math.round(sysMetrics.gpu.vram_used_mb / 1024)}/${Math.round(sysMetrics.gpu.vram_total_mb / 1024)} GB`}
                            warn={80} crit={95}
                        />
                    )}
                    {sysMetrics.gpu && (
                        <Gauge label="GPU Util" value={sysMetrics.gpu.util_pct} max={100} unit="%" warn={85} crit={95} />
                    )}
                    {sysMetrics.gpu && (() => {
                        const temp = sysMetrics.gpu.temp_c;
                        const pct = Math.max(0, Math.min(1, (temp - 30) / 50));
                        const hue = (1 - pct) * 240;
                        const color = `hsl(${Math.round(hue)}, 90%, 60%)`;
                        return (
                            <div className="flex flex-col items-center gap-1">
                                <div className="w-[86px] h-[86px] rounded-full flex items-center justify-center"
                                    style={{ background: 'var(--color-bg-elevated)', border: `2px solid ${color}`, boxShadow: `0 0 10px ${color}33`, transition: 'all 0.5s ease' }}>
                                    <div className="text-center">
                                        <Thermometer size={18} style={{ color: color, margin: '0 auto', transition: 'color 0.5s ease' }} />
                                        <div className="text-sm font-semibold mt-1" style={{ color: color, transition: 'color 0.5s ease' }}>{temp}°C</div>
                                    </div>
                                </div>
                                <span className="text-xs" style={{ color: 'var(--color-text-secondary)' }}>GPU Temp</span>
                            </div>
                        );
                    })()}
                </div>
            </div>

            {/* Projection + Rate */}
            <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                <div className="card-compact">
                    <div className="text-xs mb-2" style={{ color: 'var(--color-text-secondary)' }}>Throughput</div>
                    <div className="text-2xl font-semibold">{proj.rate_per_hr.toLocaleString()} <span className="text-sm font-normal" style={{ color: 'var(--color-text-muted)' }}>papers/hr</span></div>
                    <div className="text-sm mt-1" style={{ color: 'var(--color-text-secondary)' }}>
                        ≈ {proj.mean_per_day.toLocaleString()} papers/day
                    </div>
                </div>
                <div className="card-compact">
                    <div className="text-xs mb-2" style={{ color: 'var(--color-text-secondary)' }}>Pipeline Activity</div>
                    <div className="flex items-center gap-3">
                        <Activity size={20} style={{ color: runStatus.running ? 'var(--color-success)' : 'var(--color-text-muted)' }} />
                        <span className="text-sm" style={{ color: 'var(--color-text-secondary)' }}>
                            {runStatus.running ? `Mode: ${runStatus.mode} • Uptime: ${uptime}` : 'Pipeline is idle'}
                        </span>
                    </div>
                </div>
            </div>
        </div>
    )
}
