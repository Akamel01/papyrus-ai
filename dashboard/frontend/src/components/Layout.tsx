import { NavLink, useLocation } from 'react-router-dom'
import {
    LayoutDashboard, Settings, Play, Map, BarChart3, ShieldCheck, LogOut
} from 'lucide-react'
import { clearTokens } from '../lib/api'

const navItems = [
    { to: '/', icon: LayoutDashboard, label: 'Dashboard' },
    { to: '/config', icon: Settings, label: 'Config' },
    { to: '/runs', icon: Play, label: 'Runs' },
    { to: '/coverage', icon: Map, label: 'Coverage' },
    { to: '/metrics', icon: BarChart3, label: 'Metrics' },
    { to: '/admin', icon: ShieldCheck, label: 'Admin' },
]

export default function Layout({ children }: { children: React.ReactNode }) {
    const location = useLocation()

    const handleLogout = () => {
        clearTokens()
        window.location.href = '/login'
    }

    return (
        <div className="flex h-screen overflow-hidden">
            {/* Sidebar */}
            <aside className="w-16 flex flex-col items-center py-4 gap-1 border-r shrink-0"
                style={{ background: 'var(--color-bg-surface)', borderColor: 'var(--color-border)' }}>

                {/* Logo */}
                <div className="w-9 h-9 rounded-lg flex items-center justify-center mb-4 font-bold text-sm"
                    style={{ background: 'var(--color-accent)' }}>
                    SM
                </div>

                {/* Nav items */}
                {navItems.map(({ to, icon: Icon, label }) => {
                    const active = location.pathname === to
                    return (
                        <NavLink key={to} to={to} title={label}
                            className="w-11 h-11 flex items-center justify-center rounded-lg transition-colors"
                            style={{
                                background: active ? 'var(--color-accent)' : 'transparent',
                                color: active ? '#fff' : 'var(--color-text-secondary)',
                            }}
                        >
                            <Icon size={18} />
                        </NavLink>
                    )
                })}

                <div className="flex-1" />

                {/* Logout */}
                <button onClick={handleLogout} title="Logout"
                    className="w-11 h-11 flex items-center justify-center rounded-lg transition-colors cursor-pointer"
                    style={{ color: 'var(--color-text-muted)' }}>
                    <LogOut size={18} />
                </button>
            </aside>

            {/* Main */}
            <main className="flex-1 overflow-y-auto p-4" style={{ background: 'var(--color-bg-primary)' }}>
                {children}
            </main>
        </div>
    )
}
