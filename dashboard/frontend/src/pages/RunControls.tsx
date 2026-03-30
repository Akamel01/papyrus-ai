import { useEffect, useState, useRef } from 'react'
import { Play, Square, FlaskConical, SkipForward, RotateCcw, Pause, ClipboardCopy, Info } from 'lucide-react'
import { run, dlq, getRole } from '../lib/api'
import { dashboardWS } from '../lib/websocket'

interface LogLine { ts: string; level: string; stage: string; msg: string }
interface DLQItem { id: number; paper_id: string; stage: string; error: string; retry_count: number; status: string }

export default function RunControls() {
    const userRole = getRole()
    const isAdmin = userRole === 'admin'
    const [status, setStatus] = useState<{ running: boolean; pid?: number; mode?: string; uptime_sec?: number }>({ running: false })
    const [logs, setLogs] = useState<LogLine[]>([])
    const [paused, setPaused] = useState(false)
    const [dlqItems, setDlqItems] = useState<DLQItem[]>([])
    const [filter, setFilter] = useState('')
    const logRef = useRef<HTMLDivElement>(null)

    useEffect(() => {
        run.status().then(setStatus).catch(() => { })
        dlq.list().then(setDlqItems).catch(() => { })

        const unsubs = [
            dashboardWS.on('log.line', (p: unknown) => {
                const line = p as LogLine
                setLogs(prev => [...prev.slice(-499), { ...line, _new: true } as LogLine & { _new?: boolean }])
            }),
            dashboardWS.on('run.status', (p: unknown) => setStatus(p as typeof status)),
            // Real-time pipeline state change notifications (no polling needed)
            dashboardWS.on('pipeline.state_change', (p: unknown) => {
                const state = p as { running: boolean; pid?: number; mode?: string; uptime_sec?: number }
                setStatus(state)
            }),
        ]
        // Reduced polling interval since we have real-time state updates
        const poll = setInterval(() => {
            run.status().then(setStatus).catch(() => { })
            dlq.list().then(setDlqItems).catch(() => { })
        }, 10000)

        return () => { unsubs.forEach(fn => fn()); clearInterval(poll) }
    }, [])

    useEffect(() => {
        if (!paused && logRef.current) {
            logRef.current.scrollTop = logRef.current.scrollHeight
        }
    }, [logs, paused])

    // Send filter criteria to the backend websocket so it stops transmitting unmatched 
    // logs that otherwise instantly overflow the 500-item frontend scrolling buffer.
    useEffect(() => {
        dashboardWS.send('log.filter', { search: filter })
    }, [filter])

    const handleStart = async (mode: string) => {
        try { await run.start(mode); run.status().then(setStatus) }
        catch (e: unknown) { alert(e instanceof Error ? e.message : 'Start failed') }
    }
    const handleStop = async (force = false) => {
        try { await run.stop(force); run.status().then(setStatus) }
        catch (e: unknown) { alert(e instanceof Error ? e.message : 'Stop failed') }
    }
    const handleRetry = async (id: number) => {
        await dlq.retry(id); dlq.list().then(setDlqItems)
    }
    const handleSkip = async (id: number) => {
        await dlq.skip(id); dlq.list().then(setDlqItems)
    }
    const copyLogs = () => {
        const text = filteredLogs.map(l => `${l.ts} ${l.level} ${l.msg}`).join('\n')
        navigator.clipboard.writeText(text)
    }

    const filteredLogs = filter
        ? logs.filter(l => l.level.includes(filter.toUpperCase()) || l.msg.toLowerCase().includes(filter.toLowerCase()))
        : logs

    const uptime = status.uptime_sec
        ? `${Math.floor(status.uptime_sec / 3600)}h ${Math.floor((status.uptime_sec % 3600) / 60)}m`
        : '—'

    const levelColor = (lvl: string) => lvl === 'ERROR' ? 'var(--color-error)' : lvl === 'WARN' ? 'var(--color-warning)' : 'var(--color-text-secondary)'

    return (
        <div className="space-y-3 h-full flex flex-col">
            {/* Read-only banner for non-admins */}
            {!isAdmin && (
                <div className="flex items-center gap-2 px-4 py-3 rounded-lg"
                    style={{ background: 'var(--color-bg-elevated)', border: '1px solid var(--color-border)' }}>
                    <Info size={16} style={{ color: 'var(--color-accent)' }} />
                    <span className="text-sm" style={{ color: 'var(--color-text-secondary)' }}>
                        This page is read-only. Only administrators can control the pipeline.
                    </span>
                </div>
            )}
            {/* Controls */}
            <div className="card-compact flex flex-wrap items-center gap-3">
                <button onClick={() => handleStart('stream')} disabled={status.running || !isAdmin}
                    className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium cursor-pointer disabled:opacity-40 disabled:cursor-not-allowed"
                    style={{ background: 'var(--color-success)', color: '#fff' }}>
                    <Play size={14} /> Start Stream
                </button>
                <button onClick={() => handleStart('embed-only')} disabled={status.running || !isAdmin}
                    className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium cursor-pointer disabled:opacity-40 disabled:cursor-not-allowed"
                    style={{ background: 'var(--color-accent)', color: '#fff' }}>
                    <Play size={14} /> Embed Only
                </button>
                <button onClick={() => handleStart('test')} disabled={status.running || !isAdmin}
                    className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium cursor-pointer disabled:opacity-40 disabled:cursor-not-allowed"
                    style={{ background: 'var(--color-warning)', color: '#000' }}>
                    <FlaskConical size={14} /> Test Run
                </button>
                <div className="w-px h-6" style={{ background: 'var(--color-border)' }} />
                <button onClick={() => handleStop(false)} disabled={!status.running || !isAdmin}
                    className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium cursor-pointer disabled:opacity-40 disabled:cursor-not-allowed"
                    style={{ background: 'var(--color-bg-elevated)', color: 'var(--color-text-primary)' }}>
                    <Square size={14} /> Stop
                </button>
                <button onClick={() => handleStop(true)} disabled={!status.running || !isAdmin}
                    className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium cursor-pointer disabled:opacity-40 disabled:cursor-not-allowed"
                    style={{ background: 'var(--color-error)', color: '#fff' }}>
                    <Square size={14} /> Force Stop
                </button>

                <div className="flex-1" />

                <span className={`status-badge ${status.running ? 'status-running' : 'status-stopped'}`}>
                    <span className={`w-2 h-2 rounded-full ${status.running ? 'bg-emerald-500 pulse-dot' : 'bg-slate-500'}`} />
                    {status.running ? `Running (PID: ${status.pid})` : 'Stopped'}
                </span>
                {status.running && (
                    <span className="text-xs" style={{ color: 'var(--color-text-secondary)' }}>
                        {uptime} • {status.mode}
                    </span>
                )}
            </div>

            {/* Live Logs */}
            <div className="card-compact flex-1 flex flex-col min-h-0">
                <div className="flex items-center justify-between mb-2">
                    <span className="text-xs font-medium" style={{ color: 'var(--color-text-secondary)' }}>Live Logs</span>
                    <div className="flex items-center gap-2">
                        <input type="text" value={filter} onChange={e => setFilter(e.target.value)}
                            placeholder="Filter..." className="text-xs px-2 py-1 rounded"
                            style={{ background: 'var(--color-bg-primary)', border: '1px solid var(--color-border)', color: 'var(--color-text-primary)', width: 120 }} />
                        <button onClick={() => setPaused(!paused)} className="p-1 cursor-pointer"
                            style={{ color: paused ? 'var(--color-warning)' : 'var(--color-text-muted)' }}>
                            <Pause size={14} />
                        </button>
                        <button onClick={copyLogs} className="p-1 cursor-pointer" style={{ color: 'var(--color-text-muted)' }}>
                            <ClipboardCopy size={14} />
                        </button>
                    </div>
                </div>
                <div ref={logRef} className="flex-1 overflow-y-auto font-mono text-xs leading-5 min-h-0"
                    style={{ background: 'var(--color-bg-primary)', borderRadius: 6, padding: 8 }}>
                    {filteredLogs.map((l, i) => (
                        <div key={i} className={i === filteredLogs.length - 1 ? 'log-line-new' : ''}>
                            <span style={{ color: 'var(--color-text-muted)' }}>{l.ts}</span>{' '}
                            <span style={{ color: levelColor(l.level), fontWeight: 600 }}>{l.level.padEnd(5)}</span>{' '}
                            <span style={{ color: 'var(--color-text-primary)' }}>{l.msg}</span>
                        </div>
                    ))}
                    {filteredLogs.length === 0 && (
                        <div style={{ color: 'var(--color-text-muted)' }}>No log lines yet. Start the pipeline to see output.</div>
                    )}
                </div>
            </div>

            {/* DLQ Table */}
            {dlqItems.length > 0 && (
                <div className="card-compact shrink-0 max-h-48 overflow-y-auto">
                    <div className="text-xs font-medium mb-2" style={{ color: 'var(--color-text-secondary)' }}>
                        Dead Letter Queue ({dlqItems.length})
                    </div>
                    <table className="w-full text-xs">
                        <thead>
                            <tr style={{ color: 'var(--color-text-muted)' }}>
                                <th className="text-left py-1">Paper</th>
                                <th className="text-left py-1">Stage</th>
                                <th className="text-left py-1">Error</th>
                                {isAdmin && <th className="text-right py-1">Actions</th>}
                            </tr>
                        </thead>
                        <tbody>
                            {dlqItems.map(item => (
                                <tr key={item.id} style={{ borderTop: '1px solid var(--color-border-subtle)' }}>
                                    <td className="py-1.5 truncate max-w-[200px]" style={{ color: 'var(--color-text-primary)' }}>{item.paper_id}</td>
                                    <td className="py-1.5" style={{ color: 'var(--color-text-secondary)' }}>{item.stage}</td>
                                    <td className="py-1.5 truncate max-w-[200px]" style={{ color: 'var(--color-error)' }}>{item.error}</td>
                                    {isAdmin && (
                                        <td className="py-1.5 text-right">
                                            <button onClick={() => handleRetry(item.id)} className="p-1 cursor-pointer" style={{ color: 'var(--color-accent)' }}><RotateCcw size={12} /></button>
                                            <button onClick={() => handleSkip(item.id)} className="p-1 cursor-pointer" style={{ color: 'var(--color-text-muted)' }}><SkipForward size={12} /></button>
                                        </td>
                                    )}
                                </tr>
                            ))}
                        </tbody>
                    </table>
                </div>
            )}
        </div>
    )
}
