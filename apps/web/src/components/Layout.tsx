import { Outlet, Link, useLocation } from 'react-router-dom'

export default function Layout() {
    const location = useLocation()

    return (
        <div className="min-h-screen">
            {/* Header */}
            <header className="border-b border-[--color-border] bg-[--color-bg]/80 backdrop-blur-sm sticky top-0 z-50">
                <div className="max-w-6xl mx-auto px-6 py-4 flex items-center justify-between">
                    <Link to="/" className="flex items-center gap-3 group">
                        <div className="w-10 h-10 rounded-xl bg-gradient-to-br from-indigo-500 to-purple-600 flex items-center justify-center shadow-lg group-hover:shadow-indigo-500/30 transition-shadow">
                            <span className="text-2xl">🎬</span>
                        </div>
                        <div>
                            <h1 className="text-xl font-bold bg-gradient-to-r from-indigo-400 to-purple-400 bg-clip-text text-transparent">
                                SubFlow
                            </h1>
                            <p className="text-xs text-[--color-text-muted]">视频语义翻译</p>
                        </div>
                    </Link>

                    <nav className="flex items-center gap-6">
                        <NavLink to="/" active={location.pathname === '/'}>
                            首页
                        </NavLink>
                        <NavLink to="/jobs" active={location.pathname.startsWith('/jobs')}>
                            任务列表
                        </NavLink>
                    </nav>
                </div>
            </header>

            {/* Main content */}
            <main className="max-w-6xl mx-auto px-6 py-8">
                <Outlet />
            </main>

            {/* Footer */}
            <footer className="border-t border-[--color-border] mt-auto">
                <div className="max-w-6xl mx-auto px-6 py-6 text-center text-[--color-text-muted] text-sm">
                    SubFlow © 2026 - 基于语义理解的视频字幕翻译系统
                </div>
            </footer>
        </div>
    )
}

function NavLink({
    to,
    active,
    children,
}: {
    to: string
    active: boolean
    children: React.ReactNode
}) {
    return (
        <Link
            to={to}
            className={`text-sm font-medium transition-colors ${active
                    ? 'text-indigo-400'
                    : 'text-[--color-text-muted] hover:text-[--color-text]'
                }`}
        >
            {children}
        </Link>
    )
}
