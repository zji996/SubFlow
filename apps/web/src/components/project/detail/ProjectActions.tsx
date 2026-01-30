import { Link } from 'react-router-dom'
import type { Project, StageName } from '../../../types/entities'

export interface FailedStageInfo {
    name: StageName
    label: string
}

interface ProjectActionsProps {
    project: Project
    projectId: string
    failedStage: FailedStageInfo | null
    onRunNext: () => void
    onRunAll: () => void
    onRetry: (stage?: StageName) => void
    onEditSubtitles: () => void
    onDelete: () => void
}

export function ProjectActions({
    project,
    projectId,
    failedStage,
    onRunNext,
    onRunAll,
    onRetry,
    onEditSubtitles,
    onDelete,
}: ProjectActionsProps) {
    if (project.status === 'completed') {
        return (
            <div className="flex items-center justify-between gap-4 p-4 rounded-xl bg-[--color-success]/10 border border-[--color-success]/30">
                <div className="flex items-center gap-3">
                    <div className="w-10 h-10 rounded-xl bg-[--color-success]/20 flex items-center justify-center">
                        <svg className="w-5 h-5 text-[--color-success-light]" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
                        </svg>
                    </div>
                    <div>
                        <div className="font-medium text-[--color-success-light]">处理完成</div>
                        <div className="text-xs text-[--color-text-muted]">所有阶段已成功完成，可以导出字幕</div>
                    </div>
                </div>
                <div className="flex items-center gap-2">
                    <Link to={`/projects/${projectId}/preview`} className="btn-secondary">
                        <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" />
                            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M2.458 12C3.732 7.943 7.523 5 12 5c4.478 0 8.268 2.943 9.542 7-1.274 4.057-5.064 7-9.542 7-4.477 0-8.268-2.943-9.542-7z" />
                        </svg>
                        预览数据
                    </Link>
                    <button onClick={onEditSubtitles} className="btn-primary">
                        <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M11 5H6a2 2 0 00-2 2v11a2 2 0 002 2h11a2 2 0 002-2v-5m-1.414-9.414a2 2 0 112.828 2.828L11.828 15H9v-2.828l8.586-8.586z" />
                        </svg>
                        编辑字幕
                    </button>
                    <button onClick={onDelete} className="btn-danger">
                        <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" />
                        </svg>
                        删除
                    </button>
                </div>
            </div>
        )
    }

    return (
        <div className="flex flex-wrap gap-3">
            {project.status === 'failed' && failedStage && (
                <button onClick={() => onRetry(failedStage.name)} className="btn-warning">
                    <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 4v6h6M20 20v-6h-6" />
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M20 11a8 8 0 00-14.9-3M4 13a8 8 0 0014.9 3" />
                    </svg>
                    重试 {failedStage.label}
                </button>
            )}
            <button onClick={onRunNext} disabled={project.status === 'processing'} className="btn-primary">
                <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M14.752 11.168l-3.197-2.132A1 1 0 0010 9.87v4.263a1 1 0 001.555.832l3.197-2.132a1 1 0 000-1.664z" />
                </svg>
                {project.status === 'processing' ? '处理中...' : '执行下一步'}
            </button>
            <button onClick={onRunAll} disabled={project.status === 'processing'} className="btn-secondary">
                <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13 5l7 7-7 7M5 5l7 7-7 7" />
                </svg>
                执行全部
            </button>
            <button onClick={onDelete} className="btn-danger ml-auto">
                <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" />
                </svg>
                删除项目
            </button>
        </div>
    )
}

