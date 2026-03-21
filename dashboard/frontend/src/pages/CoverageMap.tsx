import { useEffect, useState, useRef, useCallback } from 'react'
import { metrics, coverage } from '../lib/api'

export default function CoverageMap() {
    const [data, setData] = useState<{ keywords: string[]; years: number[]; matrix: number[][] } | null>(null)
    const [drilldown, setDrilldown] = useState<{ keyword: string; year: number; papers_count: number; embedded_count: number; sources: Record<string, number>; gap_pct: number } | null>(null)
    const canvasRef = useRef<HTMLCanvasElement>(null)
    const CELL_W = 80, CELL_H = 40, PAD_L = 120, PAD_T = 30

    useEffect(() => {
        metrics.coverage().then(setData).catch(() => { })
    }, [])

    const draw = useCallback(() => {
        if (!data || !canvasRef.current) return
        const ctx = canvasRef.current.getContext('2d')!
        const { keywords, years, matrix } = data

        const w = PAD_L + years.length * CELL_W + 20
        const h = PAD_T + keywords.length * CELL_H + 20
        canvasRef.current.width = w * 2
        canvasRef.current.height = h * 2
        canvasRef.current.style.width = w + 'px'
        canvasRef.current.style.height = h + 'px'
        ctx.scale(2, 2)

        // Background
        ctx.fillStyle = '#1e293b'
        ctx.fillRect(0, 0, w, h)

        // Column headers (years)
        ctx.fillStyle = '#94a3b8'
        ctx.font = '11px Inter, sans-serif'
        ctx.textAlign = 'center'
        years.forEach((yr, j) => {
            ctx.fillText(String(yr), PAD_L + j * CELL_W + CELL_W / 2, PAD_T - 8)
        })

        // Rows
        keywords.forEach((kw, i) => {
            // Row label
            ctx.fillStyle = '#94a3b8'
            ctx.textAlign = 'right'
            ctx.fillText(kw.length > 14 ? kw.slice(0, 12) + '…' : kw, PAD_L - 10, PAD_T + i * CELL_H + CELL_H / 2 + 4)

            years.forEach((_, j) => {
                const pct = matrix[i]?.[j] ?? 0
                const x = PAD_L + j * CELL_W
                const y = PAD_T + i * CELL_H

                // Cell color
                if (pct === 0) ctx.fillStyle = '#0f172a'
                else if (pct < 25) ctx.fillStyle = '#1e3a5f'
                else if (pct < 50) ctx.fillStyle = '#1d4e8c'
                else if (pct < 75) ctx.fillStyle = '#2563eb'
                else ctx.fillStyle = '#10b981'

                ctx.fillRect(x + 1, y + 1, CELL_W - 2, CELL_H - 2)

                // Cell text
                ctx.fillStyle = pct > 50 ? '#fff' : '#94a3b8'
                ctx.textAlign = 'center'
                ctx.font = '11px Inter, sans-serif'
                ctx.fillText(pct > 0 ? pct + '%' : '–', x + CELL_W / 2, y + CELL_H / 2 + 4)
            })
        })
    }, [data])

    useEffect(draw, [draw])

    const handleClick = (e: React.MouseEvent<HTMLCanvasElement>) => {
        if (!data || !canvasRef.current) return
        const rect = canvasRef.current.getBoundingClientRect()
        const x = e.clientX - rect.left
        const y = e.clientY - rect.top
        const col = Math.floor((x - PAD_L) / CELL_W)
        const row = Math.floor((y - PAD_T) / CELL_H)

        if (col >= 0 && col < data.years.length && row >= 0 && row < data.keywords.length) {
            coverage.drilldown(data.keywords[row], data.years[col])
                .then(setDrilldown)
                .catch(() => { })
        }
    }

    return (
        <div className="space-y-3">
            <div className="card-compact">
                <h2 className="text-sm font-semibold mb-3">Discovery Coverage Map</h2>
                {data ? (
                    <div className="overflow-x-auto">
                        <canvas ref={canvasRef} onClick={handleClick} className="cursor-pointer rounded" />
                    </div>
                ) : (
                    <div className="text-sm" style={{ color: 'var(--color-text-muted)' }}>Loading coverage data…</div>
                )}

                {/* Legend */}
                <div className="flex items-center gap-4 mt-3 text-xs" style={{ color: 'var(--color-text-muted)' }}>
                    <span className="flex items-center gap-1"><span className="w-4 h-3 rounded inline-block" style={{ background: '#0f172a' }} /> 0%</span>
                    <span className="flex items-center gap-1"><span className="w-4 h-3 rounded inline-block" style={{ background: '#1e3a5f' }} /> 1–25%</span>
                    <span className="flex items-center gap-1"><span className="w-4 h-3 rounded inline-block" style={{ background: '#1d4e8c' }} /> 26–50%</span>
                    <span className="flex items-center gap-1"><span className="w-4 h-3 rounded inline-block" style={{ background: '#2563eb' }} /> 51–75%</span>
                    <span className="flex items-center gap-1"><span className="w-4 h-3 rounded inline-block" style={{ background: '#10b981' }} /> 76–100%</span>
                </div>
            </div>

            {/* Drill-down */}
            {drilldown && (
                <div className="card-compact">
                    <h3 className="text-sm font-semibold mb-2">
                        {drilldown.keyword} × {drilldown.year}
                    </h3>
                    <div className="grid grid-cols-2 md:grid-cols-4 gap-3 text-xs">
                        <div>
                            <span style={{ color: 'var(--color-text-secondary)' }}>Total Papers</span>
                            <div className="text-lg font-semibold">{drilldown.papers_count.toLocaleString()}</div>
                        </div>
                        <div>
                            <span style={{ color: 'var(--color-text-secondary)' }}>Embedded</span>
                            <div className="text-lg font-semibold">{drilldown.embedded_count.toLocaleString()}</div>
                        </div>
                        <div>
                            <span style={{ color: 'var(--color-text-secondary)' }}>Gap</span>
                            <div className="text-lg font-semibold" style={{ color: drilldown.gap_pct > 50 ? 'var(--color-warning)' : 'var(--color-success)' }}>
                                {drilldown.gap_pct}%
                            </div>
                        </div>
                        <div>
                            <span style={{ color: 'var(--color-text-secondary)' }}>Sources</span>
                            {Object.entries(drilldown.sources).map(([src, cnt]) => (
                                <div key={src}>{src}: {(cnt as number).toLocaleString()}</div>
                            ))}
                        </div>
                    </div>
                </div>
            )}
        </div>
    )
}
