import { useCallback, useState, useMemo, useEffect } from 'react'
import { Link } from 'react-router-dom'
import { listProjects, deleteProject, type Project } from '../api/projects'
import { ProjectCard } from '../components/project/ProjectCard'
import { usePolling } from '../hooks/usePolling'
import { useDocumentVisibility } from '../hooks/useDocumentVisibility'

type SortOption = 'updated_desc' | 'updated_asc' | 'created_desc' | 'created_asc' | 'name_asc' | 'name_desc'

const sortOptions: { value: SortOption; label: string }[] = [
    { value: 'updated_desc', label: '最近更新' },
    { value: 'updated_asc', label: '最早更新' },
    { value: 'created_desc', label: '最近创建' },
    { value: 'created_asc', label: '最早创建' },
    { value: 'name_asc', label: '名称 A-Z' },
    { value: 'name_desc', label: '名称 Z-A' },
]

// Skeleton component for loading state
function ProjectCardSkeleton() {
    return (
        <div className="glass-card p-6">
            <div className="flex items-start justify-between mb-4">
                <div className="flex-1">
                    <div className="skeleton h-6 w-32 mb-2"></div>
                    <div className="skeleton h-4 w-48"></div>
                </div>
                <div className="skeleton h-6 w-20 rounded-full"></div>
            </div>
            <div className="skeleton h-2 w-full rounded-full mb-4"></div>
            <div className="flex gap-2">
                <div className="skeleton h-4 w-16"></div>
                <div className="skeleton h-4 w-20"></div>
            </div>
        </div>
    )
}

export default function ProjectsPage() {
    const [projects, setProjects] = useState<Project[]>([])
    const [error, setError] = useState<string | null>(null)
    const [sortBy, setSortBy] = useState<SortOption>('updated_desc')
    const [deletingId, setDeletingId] = useState<string | null>(null)

    // Pause polling when user switches to another tab
    const isVisible = useDocumentVisibility()

    const fetcher = useCallback((signal: AbortSignal) => listProjects({ signal }), [])

    // Only auto-poll when there are projects in processing state
    const hasProcessing = projects.some(p => p.status === 'processing')
    const shouldPoll = isVisible && hasProcessing

    const { loading, refetch } = usePolling<Project[]>({
        fetcher,
        interval: 15000, // 15 seconds when polling
        enabled: shouldPoll,
        onSuccess: (data) => {
            setProjects(data)
            setError(null)
        },
        onError: (err) => {
            setError(err.message)
        },
    })

    // Initial fetch on mount (always happens once)
    const [initialLoaded, setInitialLoaded] = useState(false)
    useEffect(() => {
        if (!initialLoaded) {
            refetch()
            setInitialLoaded(true)
        }
    }, [initialLoaded, refetch])

    // Sort projects
    const sortedProjects = useMemo(() => {
        const sorted = [...projects]
        sorted.sort((a, b) => {
            switch (sortBy) {
                case 'updated_desc': {
                    const aTime = a.updated_at ? new Date(a.updated_at).getTime() : 0
                    const bTime = b.updated_at ? new Date(b.updated_at).getTime() : 0
                    return bTime - aTime
                }
                case 'updated_asc': {
                    const aTime = a.updated_at ? new Date(a.updated_at).getTime() : 0
                    const bTime = b.updated_at ? new Date(b.updated_at).getTime() : 0
                    return aTime - bTime
                }
                case 'created_desc': {
                    const aTime = a.created_at ? new Date(a.created_at).getTime() : 0
                    const bTime = b.created_at ? new Date(b.created_at).getTime() : 0
                    return bTime - aTime
                }
                case 'created_asc': {
                    const aTime = a.created_at ? new Date(a.created_at).getTime() : 0
                    const bTime = b.created_at ? new Date(b.created_at).getTime() : 0
                    return aTime - bTime
                }
                case 'name_asc':
                    return (a.name || '').localeCompare(b.name || '')
                case 'name_desc':
                    return (b.name || '').localeCompare(a.name || '')
                default:
                    return 0
            }
        })
        return sorted
    }, [projects, sortBy])

    const handleDelete = async (projectId: string) => {
        if (!window.confirm('确认删除该项目？此操作不可恢复。')) return

        setDeletingId(projectId)
        try {
            await deleteProject(projectId)
            setProjects(prev => prev.filter(p => p.id !== projectId))
        } catch (err) {
            setError(err instanceof Error ? err.message : '删除失败')
        } finally {
            setDeletingId(null)
        }
    }

    return (
        <div className="animate-fade-in">
            {/* Header */}
            <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 mb-8">
                <div>
                    <h1 className="text-2xl font-bold text-gradient">项目列表</h1>
                    <p className="text-[--color-text-muted] mt-1">
                        创建并管理视频翻译项目
                    </p>
                </div>
                <div className="flex items-center gap-2">
                    <button
                        onClick={() => refetch()}
                        disabled={loading}
                        className="btn-secondary"
                        title="刷新列表"
                    >
                        <svg
                            className={`w-5 h-5 ${loading ? 'animate-spin' : ''}`}
                            fill="none"
                            stroke="currentColor"
                            viewBox="0 0 24 24"
                        >
                            <path
                                strokeLinecap="round"
                                strokeLinejoin="round"
                                strokeWidth={2}
                                d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15"
                            />
                        </svg>
                        <span className="hidden sm:inline">刷新</span>
                    </button>
                    <Link to="/projects/new" className="btn-primary">
                        <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 4v16m8-8H4" />
                        </svg>
                        <span>新建项目</span>
                    </Link>
                </div>
            </div>

            {/* Error Alert */}
            {error && (
                <div className="p-4 rounded-xl bg-[--color-error]/10 border border-[--color-error]/30 text-[--color-error-light] mb-6 flex items-center gap-3 animate-fade-in">
                    <svg className="w-5 h-5 shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 8v4m0 4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
                    </svg>
                    <span>{error}</span>
                    <button
                        onClick={() => setError(null)}
                        className="ml-auto text-[--color-error-light] hover:text-white"
                    >
                        <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
                        </svg>
                    </button>
                </div>
            )}

            {/* Loading State */}
            {loading && projects.length === 0 && (
                <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
                    {[1, 2, 3].map((i) => (
                        <ProjectCardSkeleton key={i} />
                    ))}
                </div>
            )}

            {/* Empty State */}
            {!loading && projects.length === 0 && (
                <div className="glass-card p-16 text-center animate-slide-up">
                    <div className="w-24 h-24 mx-auto mb-6 rounded-2xl bg-gradient-to-br from-[--color-primary]/20 to-[--color-accent]/20 flex items-center justify-center">
                        <svg className="w-12 h-12 text-[--color-primary-light]" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M7 4v16M17 4v16M3 8h4m10 0h4M3 12h18M3 16h4m10 0h4M4 20h16a1 1 0 001-1V5a1 1 0 00-1-1H4a1 1 0 00-1 1v14a1 1 0 001 1z" />
                        </svg>
                    </div>
                    <h3 className="text-xl font-semibold mb-2">暂无项目</h3>
                    <p className="text-[--color-text-muted] mb-8 max-w-sm mx-auto">
                        创建您的第一个项目，开始自动翻译视频字幕
                    </p>
                    <Link to="/projects/new" className="btn-primary inline-flex">
                        <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 4v16m8-8H4" />
                        </svg>
                        <span>创建第一个项目</span>
                    </Link>
                </div>
            )}

            {/* Project Grid */}
            {!loading && projects.length > 0 && (
                <>
                    {/* Stats & Sort */}
                    <div className="flex flex-col lg:flex-row gap-4 mb-6">
                        {/* Stats */}
                        <div className="grid grid-cols-4 gap-3 flex-1">
                            <div className="glass-card p-3 text-center">
                                <div className="text-xl font-bold text-gradient">{projects.length}</div>
                                <div className="text-xs text-[--color-text-muted]">总项目</div>
                            </div>
                            <div className="glass-card p-3 text-center">
                                <div className="text-xl font-bold text-[--color-success-light]">
                                    {projects.filter(p => p.status === 'completed').length}
                                </div>
                                <div className="text-xs text-[--color-text-muted]">已完成</div>
                            </div>
                            <div className="glass-card p-3 text-center">
                                <div className="text-xl font-bold text-[--color-primary-light]">
                                    {projects.filter(p => p.status === 'processing').length}
                                </div>
                                <div className="text-xs text-[--color-text-muted]">处理中</div>
                            </div>
                            <div className="glass-card p-3 text-center">
                                <div className="text-xl font-bold text-[--color-error-light]">
                                    {projects.filter(p => p.status === 'failed').length}
                                </div>
                                <div className="text-xs text-[--color-text-muted]">失败</div>
                            </div>
                        </div>

                        {/* Sort */}
                        <div className="flex items-center gap-2">
                            <svg className="w-4 h-4 text-[--color-text-muted]" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M3 4h13M3 8h9m-9 4h6m4 0l4-4m0 0l4 4m-4-4v12" />
                            </svg>
                            <select
                                value={sortBy}
                                onChange={(e) => setSortBy(e.target.value as SortOption)}
                                className="input py-2 px-3 w-auto min-w-[140px] text-sm"
                            >
                                {sortOptions.map(opt => (
                                    <option key={opt.value} value={opt.value}>
                                        {opt.label}
                                    </option>
                                ))}
                            </select>
                        </div>
                    </div>

                    {/* Project Cards */}
                    <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
                        {sortedProjects.map((p, index) => (
                            <div
                                key={p.id}
                                className="animate-slide-up"
                                style={{ animationDelay: `${index * 50}ms` }}
                            >
                                <ProjectCard
                                    project={p}
                                    onDelete={() => handleDelete(p.id)}
                                    isDeleting={deletingId === p.id}
                                />
                            </div>
                        ))}
                    </div>
                </>
            )}
        </div>
    )
}
