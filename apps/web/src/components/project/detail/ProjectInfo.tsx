import type { Project } from '../../../types/entities'
import { formatTime } from '../../../utils'

export function ProjectInfo({ project }: { project: Project }) {
    return (
        <>
            <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-6">
                <div className="p-3 rounded-xl bg-[--color-bg]/50 border border-[--color-border]">
                    <div className="text-xs text-[--color-text-muted] mb-1">源语言</div>
                    <div className="font-medium">{project.source_language || '自动识别'}</div>
                </div>
                <div className="p-3 rounded-xl bg-[--color-bg]/50 border border-[--color-border]">
                    <div className="text-xs text-[--color-text-muted] mb-1">目标语言</div>
                    <div className="font-medium">{project.target_language}</div>
                </div>
                <div className="p-3 rounded-xl bg-[--color-bg]/50 border border-[--color-border]">
                    <div className="text-xs text-[--color-text-muted] mb-1">进度</div>
                    <div className="font-medium">
                        {project.status === 'completed' ? (
                            <span className="text-[--color-success-light]">✓ 已完成</span>
                        ) : project.status === 'failed' ? (
                            <span className="text-[--color-error-light]">✗ 失败</span>
                        ) : (
                            `${Math.min(project.current_stage, 5)} / 5 阶段`
                        )}
                    </div>
                </div>
                <div className="p-3 rounded-xl bg-[--color-bg]/50 border border-[--color-border]">
                    <div className="text-xs text-[--color-text-muted] mb-1">更新时间</div>
                    <div className="font-medium text-sm">{formatTime(project.updated_at)}</div>
                </div>
            </div>

            <div className="p-3 rounded-xl bg-[--color-bg]/50 border border-[--color-border] mb-6">
                <div className="text-xs text-[--color-text-muted] mb-1">媒体路径</div>
                <div className="font-mono text-sm truncate">{project.media_url}</div>
            </div>
        </>
    )
}

