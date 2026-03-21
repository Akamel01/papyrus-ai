import { useState } from 'react'
import { auth, setTokens } from '../lib/api'
import { Lock, User, AlertCircle } from 'lucide-react'

export default function Login({ onLogin }: { onLogin: () => void }) {
    const [username, setUsername] = useState('')
    const [password, setPassword] = useState('')
    const [error, setError] = useState('')
    const [loading, setLoading] = useState(false)

    const handleSubmit = async (e: React.FormEvent) => {
        e.preventDefault()
        setError('')
        setLoading(true)
        try {
            const res = await auth.login(username, password)
            setTokens(res.access_token, res.refresh_token)
            localStorage.setItem('user_role', res.role)
            onLogin()
        } catch {
            setError('Invalid credentials')
        } finally {
            setLoading(false)
        }
    }

    return (
        <div className="min-h-screen flex items-center justify-center"
            style={{ background: 'var(--color-bg-primary)' }}>
            <div className="w-full max-w-sm">
                {/* Header */}
                <div className="text-center mb-8">
                    <div className="w-14 h-14 rounded-xl flex items-center justify-center mx-auto mb-4 text-xl font-bold"
                        style={{ background: 'var(--color-accent)' }}>
                        SM
                    </div>
                    <h1 className="text-xl font-semibold" style={{ color: 'var(--color-text-primary)' }}>
                        SME Pipeline Dashboard
                    </h1>
                    <p className="text-sm mt-1" style={{ color: 'var(--color-text-secondary)' }}>
                        Sign in to continue
                    </p>
                </div>

                {/* Form */}
                <form onSubmit={handleSubmit} className="card space-y-4">
                    {error && (
                        <div className="flex items-center gap-2 text-sm p-3 rounded-lg"
                            style={{ background: 'rgba(239,68,68,0.1)', color: 'var(--color-error)' }}>
                            <AlertCircle size={16} /> {error}
                        </div>
                    )}

                    <div>
                        <label className="text-xs font-medium mb-1 block" style={{ color: 'var(--color-text-secondary)' }}>
                            Username
                        </label>
                        <div className="relative">
                            <User size={16} className="absolute left-3 top-1/2 -translate-y-1/2"
                                style={{ color: 'var(--color-text-muted)' }} />
                            <input type="text" value={username} onChange={e => setUsername(e.target.value)}
                                className="w-full pl-10 pr-3 py-2 rounded-lg text-sm outline-none"
                                style={{
                                    background: 'var(--color-bg-primary)',
                                    border: '1px solid var(--color-border)',
                                    color: 'var(--color-text-primary)',
                                }}
                                placeholder="Enter username" autoFocus />
                        </div>
                    </div>

                    <div>
                        <label className="text-xs font-medium mb-1 block" style={{ color: 'var(--color-text-secondary)' }}>
                            Password
                        </label>
                        <div className="relative">
                            <Lock size={16} className="absolute left-3 top-1/2 -translate-y-1/2"
                                style={{ color: 'var(--color-text-muted)' }} />
                            <input type="password" value={password} onChange={e => setPassword(e.target.value)}
                                className="w-full pl-10 pr-3 py-2 rounded-lg text-sm outline-none"
                                style={{
                                    background: 'var(--color-bg-primary)',
                                    border: '1px solid var(--color-border)',
                                    color: 'var(--color-text-primary)',
                                }}
                                placeholder="Enter password" />
                        </div>
                    </div>

                    <button type="submit" disabled={loading}
                        className="w-full py-2.5 rounded-lg text-sm font-semibold transition-colors cursor-pointer"
                        style={{
                            background: loading ? 'var(--color-bg-elevated)' : 'var(--color-accent)',
                            color: '#fff',
                        }}>
                        {loading ? 'Signing in…' : 'Sign In'}
                    </button>
                </form>
            </div>
        </div>
    )
}
