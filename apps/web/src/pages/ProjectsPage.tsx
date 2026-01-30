import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { ProjectCard } from '../components/project/ProjectCard'
import { Select } from '../components/common/Select'
import { useProjects, type SortOption } from '../hooks/useProjects'

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
    const {
        data: projects,
        loading,
        error,
        clearError,
        refetch,
        sortBy,
        setSortBy,
        sortOptions,
        deleteProject,
        deletingIds,
    } = useProjects()
    const [uiError, setUiError] = useState<string | null>(null)
    const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set())
    const [isBatchDeleting, setIsBatchDeleting] = useState(false)
    const [isSelectMode, setIsSelectMode] = useState(false)
    useEffect(() => {
        // Clear selection for deleted projects
        setSelectedIds((prev) => {
            const next = new Set(prev)
            const currentIds = new Set(projects.map((p) => p.id))
            for (const id of next) {
                if (!currentIds.has(id)) next.delete(id)
            }
            return next
        })
    }, [projects])

    const handleDelete = async (projectId: string) => {
        if (!window.confirm('确认删除该项目？此操作不可恢复。')) return
        await deleteProject(projectId)
        setSelectedIds((prev) => {
            const next = new Set(prev)
            next.delete(projectId)
            return next
        })
    }

    const handleSelect = (projectId: string, selected: boolean) => {
        setSelectedIds(prev => {
            const newIds = new Set(prev)
            if (selected) {
                newIds.add(projectId)
            } else {
                newIds.delete(projectId)
            }
            return newIds
        })
    }

    const handleSelectAll = () => {
        if (selectedIds.size === projects.length) {
            setSelectedIds(new Set())
        } else {
            setSelectedIds(new Set(projects.map(p => p.id)))
        }
    }

    const handleBatchDelete = async () => {
        if (selectedIds.size === 0) return
        if (!window.confirm(`确认删除选中的 ${selectedIds.size} 个项目？此操作不可恢复。`)) return

        setIsBatchDeleting(true)
        const idsToDelete = Array.from(selectedIds)
        const failed: string[] = []

        for (const id of idsToDelete) {
            const ok = await deleteProject(id)
            if (!ok) failed.push(id)
        }

        setSelectedIds(new Set(failed))

        if (failed.length > 0) {
            setUiError(`${idsToDelete.length - failed.length} 个项目删除成功，${failed.length} 个失败`)
        }

        setIsBatchDeleting(false)
    }

    const isAllSelected = projects.length > 0 && selectedIds.size === projects.length


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
            {(uiError || error) && (
                <div className="p-4 rounded-xl bg-[--color-error]/10 border border-[--color-error]/30 text-[--color-error-light] mb-6 flex items-center gap-3 animate-fade-in">
                    <svg className="w-5 h-5 shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 8v4m0 4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
                    </svg>
                    <span>{uiError || error}</span>
                    <button
                        onClick={() => {
                            if (uiError) setUiError(null)
                            else clearError()
                        }}
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
                    {/* Stats & Sort Bar */}
                    <div className="mb-6">
                        {!isSelectMode ? (
                            /* Normal mode: Stats + Sort */
                            <div className="flex flex-col lg:flex-row gap-4">
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

                                {/* Sort & Batch Manage button */}
                                <div className="flex items-center gap-2">
                                    <button
                                        onClick={() => setIsSelectMode(true)}
                                        className="btn-secondary text-sm"
                                        title="进入批量管理模式"
                                    >
                                        <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2m-6 9l2 2 4-4" />
                                        </svg>
                                        <span className="hidden sm:inline">批量管理</span>
                                    </button>
                                    <svg className="w-4 h-4 text-[--color-text-muted]" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M3 4h13M3 8h9m-9 4h6m4 0l4-4m0 0l4 4m-4-4v12" />
                                    </svg>
                                    <div className="w-[160px]">
                                        <Select
                                            value={sortBy}
                                            onChange={(val) => setSortBy(val as SortOption)}
                                            options={sortOptions}
                                            className="text-sm"
                                        />
                                    </div>
                                </div>
                            </div>
                        ) : (
                            /* Select mode: All in one row */
                            <div className="flex flex-wrap items-center gap-3">
                                {/* Selection hint */}
                                <div className="glass-card px-4 py-2 flex items-center gap-2">
                                    <svg className="w-4 h-4 text-[--color-primary-light]" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2m-6 9l2 2 4-4" />
                                    </svg>
                                    <span className="text-sm text-[--color-text-secondary]">
                                        点击卡片选择
                                    </span>
                                    {selectedIds.size > 0 && (
                                        <span className="text-sm font-medium text-[--color-primary-light] ml-1">
                                            ({selectedIds.size}/{projects.length})
                                        </span>
                                    )}
                                </div>

                                {/* Spacer */}
                                <div className="flex-1"></div>

                                {/* Action buttons - all inline */}
                                <div className="flex items-center gap-2">
                                    {/* Exit select mode */}
                                    <button
                                        onClick={() => {
                                            setIsSelectMode(false)
                                            setSelectedIds(new Set())
                                        }}
                                        className="btn-secondary text-sm"
                                        title="退出选择模式"
                                    >
                                        <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
                                        </svg>
                                        <span className="hidden sm:inline">取消</span>
                                    </button>

                                    {/* Select all */}
                                    <button
                                        onClick={handleSelectAll}
                                        className={`btn-secondary text-sm ${isAllSelected ? 'bg-[--color-primary]/10 border-[--color-primary]' : ''}`}
                                        title={isAllSelected ? '取消全选' : '全选'}
                                    >
                                        {isAllSelected ? (
                                            <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
                                            </svg>
                                        ) : (
                                            <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                                <rect x="4" y="4" width="16" height="16" rx="2" strokeWidth={2} />
                                            </svg>
                                        )}
                                        <span className="hidden sm:inline">{isAllSelected ? '取消全选' : '全选'}</span>
                                    </button>

                                    {/* Batch delete */}
                                    <button
                                        onClick={handleBatchDelete}
                                        disabled={isBatchDeleting || selectedIds.size === 0}
                                        className="btn-secondary text-sm text-[--color-error-light] border-[--color-error]/30 hover:bg-[--color-error]/10 disabled:opacity-50 disabled:cursor-not-allowed"
                                        title={selectedIds.size > 0 ? `删除选中的 ${selectedIds.size} 个项目` : '请先选择项目'}
                                    >
                                        {isBatchDeleting ? (
                                            <svg className="w-4 h-4 animate-spin" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                                <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"></circle>
                                                <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
                                            </svg>
                                        ) : (
                                            <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" />
                                            </svg>
                                        )}
                                        <span>删除{selectedIds.size > 0 ? ` (${selectedIds.size})` : ''}</span>
                                    </button>

                                    {/* Sort */}
                                    <div className="hidden sm:flex items-center gap-2 ml-2 pl-2 border-l border-[--color-border]">
                                        <svg className="w-4 h-4 text-[--color-text-muted]" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M3 4h13M3 8h9m-9 4h6m4 0l4-4m0 0l4 4m-4-4v12" />
                                        </svg>
                                        <div className="w-[140px]">
                                            <Select
                                                value={sortBy}
                                                onChange={(val) => setSortBy(val as SortOption)}
                                                options={sortOptions}
                                                className="text-sm"
                                            />
                                        </div>
                                    </div>
                                </div>
                            </div>
                        )}
                    </div>


                    {/* Project Cards */}
                    <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
                        {projects.map((p, index) => (
                            <div
                                key={p.id}
                                className="animate-slide-up"
                                style={{ animationDelay: `${index * 50}ms` }}
                            >
                                <ProjectCard
                                    project={p}
                                    onDelete={() => handleDelete(p.id)}
                                    isDeleting={deletingIds.has(p.id)}
                                    isSelected={isSelectMode ? selectedIds.has(p.id) : undefined}
                                    onSelect={isSelectMode ? (selected) => handleSelect(p.id, selected) : undefined}
                                />
                            </div>
                        ))}
                    </div>
                </>
            )}
        </div>
    )
}
