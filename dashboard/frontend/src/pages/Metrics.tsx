import { useEffect, useState } from 'react'
import { AreaChart, Area, XAxis, YAxis, Tooltip, ResponsiveContainer } from 'recharts'
import { metrics } from '../lib/api'

export default function Metrics() {
    const [range, setRange] = useState('1h')
    const [history, setHistory] = useState<{ timestamps: number[]; cpu: number[]; ram: number[]; gpu_util: number[]; throughput: number[] }>({ timestamps: [], cpu: [], ram: [], gpu_util: [], throughput: [] })
    const [proj, setProj] = useState<{ mean_per_day: number; lower95: number; upper95: number; rate_per_hr: number; samples: number }>({ mean_per_day: 0, lower95: 0, upper95: 0, rate_per_hr: 0, samples: 0 })

    useEffect(() => {
        const load = () => {
            metrics.history(range).then(setHistory).catch(() => { })
            metrics.projection().then(setProj).catch(() => { })
        }
        load()
        const i = setInterval(load, 30000)
        return () => clearInterval(i)
    }, [range])

    // Format time label based on range
    const formatTime = (ts: number) => {
        const date = new Date(ts * 1000)
        if (range === '7d') {
            return date.toLocaleDateString([], { weekday: 'short', hour: '2-digit' })
        }
        return date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
    }

    // Transform for Recharts
    const chartData = history.timestamps.map((ts, i) => ({
        time: formatTime(ts),
        cpu: history.cpu[i],
        ram: history.ram[i],
        gpu: history.gpu_util[i] ?? 0,
        throughput: history.throughput[i],
    }))

    const ranges = ['1h', '6h', '24h', '7d']

    return (
        <div className="space-y-3">
            {/* Time range selector */}
            <div className="card-compact flex items-center justify-between">
                <h2 className="text-sm font-semibold">System Metrics</h2>
                <div className="flex gap-1">
                    {ranges.map(r => (
                        <button key={r} onClick={() => setRange(r)}
                            className="px-3 py-1 text-xs rounded-lg transition-colors cursor-pointer"
                            style={{
                                background: range === r ? 'var(--color-accent)' : 'var(--color-bg-elevated)',
                                color: range === r ? '#fff' : 'var(--color-text-secondary)',
                            }}>{r}</button>
                    ))}
                </div>
            </div>

            {/* CPU, RAM & GPU chart */}
            <div className="card-compact">
                <div className="text-xs mb-2" style={{ color: 'var(--color-text-secondary)' }}>CPU, RAM & GPU Usage (%)</div>
                <ResponsiveContainer width="100%" height={200}>
                    <AreaChart data={chartData}>
                        <defs>
                            <linearGradient id="cpuGrad" x1="0" y1="0" x2="0" y2="1">
                                <stop offset="0%" stopColor="#3b82f6" stopOpacity={0.3} />
                                <stop offset="100%" stopColor="#3b82f6" stopOpacity={0} />
                            </linearGradient>
                            <linearGradient id="ramGrad" x1="0" y1="0" x2="0" y2="1">
                                <stop offset="0%" stopColor="#f59e0b" stopOpacity={0.3} />
                                <stop offset="100%" stopColor="#f59e0b" stopOpacity={0} />
                            </linearGradient>
                            <linearGradient id="gpuGrad" x1="0" y1="0" x2="0" y2="1">
                                <stop offset="0%" stopColor="#10b981" stopOpacity={0.3} />
                                <stop offset="100%" stopColor="#10b981" stopOpacity={0} />
                            </linearGradient>
                        </defs>
                        <XAxis dataKey="time" tick={{ fill: '#64748b', fontSize: 10 }} axisLine={false} tickLine={false} />
                        <YAxis domain={[0, 100]} tick={{ fill: '#64748b', fontSize: 10 }} axisLine={false} tickLine={false} width={30} />
                        <Tooltip contentStyle={{ background: '#1e293b', border: '1px solid #334155', borderRadius: 6, fontSize: 12 }} />
                        <Area type="monotone" dataKey="cpu" stroke="#3b82f6" fill="url(#cpuGrad)" strokeWidth={1.5} name="CPU" />
                        <Area type="monotone" dataKey="ram" stroke="#f59e0b" fill="url(#ramGrad)" strokeWidth={1.5} name="RAM" />
                        <Area type="monotone" dataKey="gpu" stroke="#10b981" fill="url(#gpuGrad)" strokeWidth={1.5} name="GPU" />
                    </AreaChart>
                </ResponsiveContainer>
            </div>

            {/* Projection */}
            <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
                <div className="card-compact">
                    <div className="text-xs" style={{ color: 'var(--color-text-secondary)' }}>Current Rate</div>
                    <div className="text-2xl font-semibold mt-1">{proj.rate_per_hr.toLocaleString()}</div>
                    <div className="text-xs" style={{ color: 'var(--color-text-muted)' }}>papers/hour</div>
                </div>
                <div className="card-compact">
                    <div className="text-xs" style={{ color: 'var(--color-text-secondary)' }}>Projected Daily</div>
                    <div className="text-2xl font-semibold mt-1">{proj.mean_per_day.toLocaleString()}</div>
                    <div className="text-xs" style={{ color: 'var(--color-text-muted)' }}>papers/day</div>
                </div>
                <div className="card-compact">
                    <div className="text-xs" style={{ color: 'var(--color-text-secondary)' }}>95% CI</div>
                    <div className="text-2xl font-semibold mt-1">
                        {proj.lower95.toLocaleString()} – {proj.upper95.toLocaleString()}
                    </div>
                    <div className="text-xs" style={{ color: 'var(--color-text-muted)' }}>
                        {proj.samples} samples
                    </div>
                </div>
            </div>

            {/* Throughput chart */}
            <div className="card-compact">
                <div className="text-xs mb-2" style={{ color: 'var(--color-text-secondary)' }}>Embedded Papers (cumulative)</div>
                <ResponsiveContainer width="100%" height={200}>
                    <AreaChart data={chartData}>
                        <defs>
                            <linearGradient id="tpGrad" x1="0" y1="0" x2="0" y2="1">
                                <stop offset="0%" stopColor="#10b981" stopOpacity={0.3} />
                                <stop offset="100%" stopColor="#10b981" stopOpacity={0} />
                            </linearGradient>
                        </defs>
                        <XAxis dataKey="time" tick={{ fill: '#64748b', fontSize: 10 }} axisLine={false} tickLine={false} />
                        <YAxis tick={{ fill: '#64748b', fontSize: 10 }} axisLine={false} tickLine={false} width={50} />
                        <Tooltip contentStyle={{ background: '#1e293b', border: '1px solid #334155', borderRadius: 6, fontSize: 12 }} />
                        <Area type="monotone" dataKey="throughput" stroke="#10b981" fill="url(#tpGrad)" strokeWidth={1.5} name="Embedded" />
                    </AreaChart>
                </ResponsiveContainer>
            </div>
        </div>
    )
}
