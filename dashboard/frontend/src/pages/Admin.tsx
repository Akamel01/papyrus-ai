import { useEffect, useState } from 'react'
import { audit } from '../lib/api'
import { Download } from 'lucide-react'

interface AuditEntry {
    timestamp: string; user_id: string; action: string; detail: Record<string, unknown>
}

export default function Admin() {
    const [entries, setEntries] = useState<AuditEntry[]>([])
    const [total, setTotal] = useState(0)
    const [page, setPage] = useState(1)
    const [actionFilter, setActionFilter] = useState('')
    const [userFilter, setUserFilter] = useState('')

    useEffect(() => {
        const params: Record<string, string | number> = { page }
        if (actionFilter) params.action = actionFilter
        if (userFilter) params.user = userFilter
        audit.list(params as { user?: string; action?: string; page?: number })
            .then(res => { setEntries(res.items); setTotal(res.total) })
            .catch(() => { })
    }, [page, actionFilter, userFilter])

    const exportCsv = () => {
        const header = 'Timestamp,User,Action,Detail\n'
        const rows = entries.map(e =>
            `"${e.timestamp}","${e.user_id}","${e.action}","${JSON.stringify(e.detail).replace(/"/g, '""')}"`
        ).join('\n')
        const blob = new Blob([header + rows], { type: 'text/csv' })
        const url = URL.createObjectURL(blob)
        const a = document.createElement('a')
        a.href = url; a.download = 'audit_log.csv'; a.click()
        URL.revokeObjectURL(url)
    }

    const actionColor = (action: string) => {
        if (action.includes('start')) return 'var(--color-success)'
        if (action.includes('stop')) return 'var(--color-error)'
        if (action.includes('config')) return 'var(--color-accent)'
        if (action.includes('snapshot')) return 'var(--color-info)'
        return 'var(--color-text-secondary)'
    }

    return (
        <div className="space-y-3">
            {/* Header */}
            <div className="card-compact flex items-center justify-between">
                <h2 className="text-sm font-semibold">Audit Log</h2>
                <div className="flex items-center gap-2">
                    <input type="text" placeholder="Filter user…" value={userFilter} onChange={e => setUserFilter(e.target.value)}
                        className="text-xs px-2 py-1 rounded" style={{ background: 'var(--color-bg-primary)', border: '1px solid var(--color-border)', color: 'var(--color-text-primary)', width: 100 }} />
                    <select value={actionFilter} onChange={e => setActionFilter(e.target.value)}
                        className="text-xs px-2 py-1 rounded cursor-pointer"
                        style={{ background: 'var(--color-bg-primary)', border: '1px solid var(--color-border)', color: 'var(--color-text-primary)' }}>
                        <option value="">All actions</option>
                        <option value="pipeline.start">pipeline.start</option>
                        <option value="pipeline.stop">pipeline.stop</option>
                        <option value="config.save">config.save</option>
                        <option value="qdrant.snapshot">qdrant.snapshot</option>
                        <option value="dlq.retry">dlq.retry</option>
                        <option value="dlq.skip">dlq.skip</option>
                    </select>
                    <button onClick={exportCsv} className="flex items-center gap-1 px-3 py-1.5 rounded-lg text-xs cursor-pointer"
                        style={{ background: 'var(--color-bg-elevated)', color: 'var(--color-text-primary)' }}>
                        <Download size={12} /> Export
                    </button>
                </div>
            </div>

            {/* Table */}
            <div className="card-compact overflow-x-auto">
                <table className="w-full text-xs">
                    <thead>
                        <tr style={{ color: 'var(--color-text-muted)' }}>
                            <th className="text-left py-2 pr-4">Timestamp</th>
                            <th className="text-left py-2 pr-4">User</th>
                            <th className="text-left py-2 pr-4">Action</th>
                            <th className="text-left py-2">Detail</th>
                        </tr>
                    </thead>
                    <tbody>
                        {entries.map((e, i) => (
                            <tr key={i} style={{ borderTop: '1px solid var(--color-border-subtle)' }}>
                                <td className="py-2 pr-4 whitespace-nowrap" style={{ color: 'var(--color-text-secondary)' }}>
                                    {new Date(e.timestamp).toLocaleString()}
                                </td>
                                <td className="py-2 pr-4 font-medium">{e.user_id}</td>
                                <td className="py-2 pr-4">
                                    <span className="px-2 py-0.5 rounded text-xs" style={{ background: 'var(--color-bg-elevated)', color: actionColor(e.action) }}>
                                        {e.action}
                                    </span>
                                </td>
                                <td className="py-2 truncate max-w-[300px]" style={{ color: 'var(--color-text-muted)' }}>
                                    {JSON.stringify(e.detail)}
                                </td>
                            </tr>
                        ))}
                        {entries.length === 0 && (
                            <tr><td colSpan={4} className="py-4 text-center" style={{ color: 'var(--color-text-muted)' }}>No audit entries</td></tr>
                        )}
                    </tbody>
                </table>
            </div>

            {/* Pagination */}
            {total > 50 && (
                <div className="flex items-center justify-center gap-2">
                    <button onClick={() => setPage(p => Math.max(1, p - 1))} disabled={page === 1}
                        className="px-3 py-1 text-xs rounded cursor-pointer disabled:opacity-40"
                        style={{ background: 'var(--color-bg-elevated)', color: 'var(--color-text-primary)' }}>
                        Prev
                    </button>
                    <span className="text-xs" style={{ color: 'var(--color-text-secondary)' }}>
                        Page {page} of {Math.ceil(total / 50)}
                    </span>
                    <button onClick={() => setPage(p => p + 1)} disabled={page >= Math.ceil(total / 50)}
                        className="px-3 py-1 text-xs rounded cursor-pointer disabled:opacity-40"
                        style={{ background: 'var(--color-bg-elevated)', color: 'var(--color-text-primary)' }}>
                        Next
                    </button>
                </div>
            )}
        </div>
    )
}
