import type { ReactNode } from 'react'
import { Outlet, Link, useLocation } from 'react-router-dom'

export default function Layout() {
    const location = useLocation()

    return (
        <div className="min-h-screen flex flex-col">
            {/* Header */}
            <header className="border-b border-[--color-border] bg-[--color-bg-base]/80 backdrop-blur-xl sticky top-0 z-50">
                <div className="max-w-7xl mx-auto px-6 py-4 flex items-center justify-between">
                    {/* Logo */}
                    <Link to="/" className="flex items-center gap-3 group">
                        <div className="relative">
                            <div className="w-10 h-10 rounded-xl bg-gradient-to-br from-[--color-primary] to-[--color-accent] flex items-center justify-center shadow-lg group-hover:shadow-[--color-primary]/30 transition-all duration-300 group-hover:scale-105">
                                <svg className="w-6 h-6 text-white" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M7 4v16M17 4v16M3 8h4m10 0h4M3 12h18M3 16h4m10 0h4M4 20h16a1 1 0 001-1V5a1 1 0 00-1-1H4a1 1 0 00-1 1v14a1 1 0 001 1z" />
                                </svg>
                            </div>
                            {/* Processing indicator dot */}
                            <div className="absolute -top-1 -right-1 w-3 h-3 bg-[--color-success] rounded-full border-2 border-[--color-bg-base] animate-pulse hidden"></div>
                        </div>
                        <div>
                            <h1 className="text-xl font-bold text-gradient">
                                SubFlow
                            </h1>
                            <p className="text-xs text-[--color-text-dim]">视频语义翻译</p>
                        </div>
                    </Link>

                    {/* Navigation */}
                    <nav className="flex items-center gap-1">
                        <NavLink
                            to="/projects"
                            active={location.pathname === '/projects'}
                            icon={
                                <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 11H5m14 0a2 2 0 012 2v6a2 2 0 01-2 2H5a2 2 0 01-2-2v-6a2 2 0 012-2m14 0V9a2 2 0 00-2-2M5 11V9a2 2 0 012-2m0 0V5a2 2 0 012-2h6a2 2 0 012 2v2M7 7h10" />
                                </svg>
                            }
                        >
                            项目
                        </NavLink>
                        <NavLink
                            to="/projects/new"
                            active={location.pathname === '/projects/new'}
                            icon={
                                <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 4v16m8-8H4" />
                                </svg>
                            }
                            highlight
                        >
                            新建
                        </NavLink>
                    </nav>
                </div>
            </header>

            {/* Main content */}
            <main className="flex-1 max-w-7xl w-full mx-auto px-6 py-8">
                <Outlet />
            </main>

            {/* Footer */}
            <footer className="border-t border-[--color-border] mt-auto bg-[--color-bg-base]/50">
                <div className="max-w-7xl mx-auto px-6 py-6">
                    <div className="flex flex-col md:flex-row items-center justify-between gap-4">
                        <div className="flex items-center gap-3 text-sm text-[--color-text-muted]">
                            <span className="text-gradient font-semibold">SubFlow</span>
                            <span className="text-[--color-text-dim]">•</span>
                            <span>基于语义理解的视频字幕翻译系统</span>
                        </div>
                        <div className="flex items-center gap-4 text-xs text-[--color-text-dim]">
                            <a href="https://github.com" target="_blank" rel="noopener noreferrer" className="hover:text-[--color-text-muted] transition-colors flex items-center gap-1">
                                <svg className="w-4 h-4" fill="currentColor" viewBox="0 0 24 24">
                                    <path fillRule="evenodd" d="M12 2C6.477 2 2 6.484 2 12.017c0 4.425 2.865 8.18 6.839 9.504.5.092.682-.217.682-.483 0-.237-.008-.868-.013-1.703-2.782.605-3.369-1.343-3.369-1.343-.454-1.158-1.11-1.466-1.11-1.466-.908-.62.069-.608.069-.608 1.003.07 1.531 1.032 1.531 1.032.892 1.53 2.341 1.088 2.91.832.092-.647.35-1.088.636-1.338-2.22-.253-4.555-1.113-4.555-4.951 0-1.093.39-1.988 1.029-2.688-.103-.253-.446-1.272.098-2.65 0 0 .84-.27 2.75 1.026A9.564 9.564 0 0112 6.844c.85.004 1.705.115 2.504.337 1.909-1.296 2.747-1.027 2.747-1.027.546 1.379.202 2.398.1 2.651.64.7 1.028 1.595 1.028 2.688 0 3.848-2.339 4.695-4.566 4.943.359.309.678.92.678 1.855 0 1.338-.012 2.419-.012 2.747 0 .268.18.58.688.482A10.019 10.019 0 0022 12.017C22 6.484 17.522 2 12 2z" clipRule="evenodd" />
                                </svg>
                                GitHub
                            </a>
                            <span>© 2026</span>
                        </div>
                    </div>
                </div>
            </footer>
        </div>
    )
}

interface NavLinkProps {
    to: string
    active: boolean
    icon?: ReactNode
    highlight?: boolean
    children: ReactNode
}

function NavLink({
    to,
    active,
    icon,
    highlight,
    children,
}: NavLinkProps) {
    const baseClass = "flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-medium transition-all duration-200"

    if (highlight && !active) {
        return (
            <Link
                to={to}
                className={`${baseClass} bg-[--color-primary]/10 text-[--color-primary-light] hover:bg-[--color-primary]/20`}
            >
                {icon}
                {children}
            </Link>
        )
    }

    return (
        <Link
            to={to}
            className={`${baseClass} ${active
                    ? 'bg-[--color-bg-elevated] text-[--color-text] shadow-sm'
                    : 'text-[--color-text-muted] hover:text-[--color-text] hover:bg-[--color-bg-hover]'
                }`}
        >
            {icon}
            {children}
        </Link>
    )
}
