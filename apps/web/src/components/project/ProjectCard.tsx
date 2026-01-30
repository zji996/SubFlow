import type { MouseEvent } from 'react'
import { Link } from 'react-router-dom'
import type { Project } from '../../api/projects'
import { StatusBadge } from '../common/StatusBadge'

interface ProjectCardProps {
    project: Project
    onDelete?: () => void
    isDeleting?: boolean
    isSelected?: boolean
    onSelect?: (selected: boolean) => void
}

// Calculate progress percentage based on current stage
function getProgress(project: Project): number {
    if (project.status === 'completed') return 100
    if (project.status === 'failed') return (project.current_stage / 5) * 100
    // Each stage is 20%
    return Math.min((project.current_stage / 5) * 100, 100)
}

// Get filename from path/url
function getMediaName(url: string): string {
    if (!url) return '未知文件'
    const parts = url.split('/').pop() || url
    const decoded = decodeURIComponent(parts.split('?')[0])
    return decoded.length > 40 ? decoded.slice(0, 37) + '...' : decoded
}

// Format relative time
function formatRelativeTime(isoString?: string | null): string {
    if (!isoString) return ''
    const date = new Date(isoString)
    if (isNaN(date.getTime())) return ''

    const now = Date.now()
    const diff = now - date.getTime()
    const seconds = Math.floor(diff / 1000)
    const minutes = Math.floor(seconds / 60)
    const hours = Math.floor(minutes / 60)
    const days = Math.floor(hours / 24)

    if (days > 0) return `${days}天前`
    if (hours > 0) return `${hours}小时前`
    if (minutes > 0) return `${minutes}分钟前`
    return '刚刚'
}

// Card content component to avoid duplication
function CardContent({ project, progress, isActive }: { project: Project; progress: number; isActive: boolean }) {
    return (
        <>
            {/* Header */}
            <div className="flex items-start justify-between gap-4 mb-4 pr-8">
                <div className="min-w-0 flex-1">
                    <h3 className="text-lg font-semibold text-[--color-text] truncate group-hover:text-[--color-primary-light] transition-colors">
                        {project.name || `项目 #${project.id.slice(0, 8)}`}
                    </h3>
                    <p className="text-sm text-[--color-text-muted] mt-1 truncate flex items-center gap-2">
                        <svg className="w-4 h-4 shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 10l4.553-2.276A1 1 0 0121 8.618v6.764a1 1 0 01-1.447.894L15 14M5 18h8a2 2 0 002-2V8a2 2 0 00-2-2H5a2 2 0 00-2 2v8a2 2 0 002 2z" />
                        </svg>
                        {getMediaName(project.media_url)}
                    </p>
                </div>
                <StatusBadge status={project.status} />
            </div>

            {/* Progress Bar */}
            <div className="mb-4">
                <div className="progress-bar">
                    <div
                        className={`progress-bar-fill ${isActive ? 'animate-pulse' : ''}`}
                        style={{ width: `${progress}%` }}
                    />
                </div>
            </div>

            {/* Footer */}
            <div className="flex items-center justify-between text-xs text-[--color-text-muted]">
                <div className="flex items-center gap-3">
                    <span className="flex items-center gap-1">
                        <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2" />
                        </svg>
                        Stage {Math.min(project.current_stage, 5)}/5
                    </span>
                    <span className="flex items-center gap-1">
                        <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M3 5h12M9 3v2m1.048 9.5A18.022 18.022 0 016.412 9m6.088 9h7M11 21l5-10 5 10M12.751 5C11.783 10.77 8.07 15.61 3 18.129" />
                        </svg>
                        {project.source_language || 'auto'} → {project.target_language}
                    </span>
                </div>
                <span className="text-[--color-text-dim]">
                    {formatRelativeTime(project.updated_at)}
                </span>
            </div>
        </>
    )
}

export function ProjectCard({ project, onDelete, isDeleting, isSelected, onSelect }: ProjectCardProps) {
    const progress = getProgress(project)
    const isActive = project.status === 'processing'

    const handleDeleteClick = (e: MouseEvent<HTMLButtonElement>) => {
        e.preventDefault()
        e.stopPropagation()
        onDelete?.()
    }

    return (
        <div className={`glass-card group relative overflow-hidden ${isSelected ? 'outline outline-2 outline-[--color-primary]' : ''}`}>
            {/* Delete button - appears on hover (only in normal mode) */}
            {onDelete && !onSelect && (
                <button
                    onClick={handleDeleteClick}
                    disabled={isDeleting}
                    className="absolute top-3 right-3 z-10 opacity-0 group-hover:opacity-100 transition-opacity p-2 rounded-lg bg-[--color-error]/10 hover:bg-[--color-error]/20 text-[--color-error-light] disabled:opacity-50"
                    title="删除项目"
                    aria-label="删除项目"
                >
                    {isDeleting ? (
                        <svg className="w-4 h-4 animate-spin" fill="none" stroke="currentColor" viewBox="0 0 24 24" aria-hidden="true">
                            <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                            <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z" />
                        </svg>
                    ) : (
                        <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24" aria-hidden="true">
                            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" />
                        </svg>
                    )}
                </button>
            )}

            {/* Selection checkbox indicator (top-left, shown in select mode when selected) */}
            {onSelect && isSelected && (
                <div className="absolute top-3 left-3 z-10 p-1.5 rounded-lg bg-[--color-primary] text-white" aria-hidden="true">
                    <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={3} d="M5 13l4 4L19 7" />
                    </svg>
                </div>
            )}

            {/* Card content - clickable for selection OR navigation */}
            {onSelect ? (
                <button
                    onClick={() => onSelect(!isSelected)}
                    className="block w-full text-left p-6 hover:bg-[--color-bg-hover] transition-colors cursor-pointer"
                    aria-pressed={isSelected}
                    aria-label={`${isSelected ? '取消选择' : '选择'} ${project.name || `项目 #${project.id.slice(0, 8)}`}`}
                >
                    <CardContent project={project} progress={progress} isActive={isActive} />
                </button>
            ) : (
                <Link
                    to={`/projects/${project.id}`}
                    className="block p-6 hover:bg-[--color-bg-hover] transition-colors"
                    aria-label={`查看项目: ${project.name || `项目 #${project.id.slice(0, 8)}`}`}
                >
                    <CardContent project={project} progress={progress} isActive={isActive} />
                </Link>
            )}
        </div>
    )
}
