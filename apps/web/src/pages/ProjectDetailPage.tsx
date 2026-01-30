import { useCallback, useMemo, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import {
    deleteProject,
    getProject,
    retryStage,
    runAll,
    runStage,
    type Project,
    type StageName,
    type StageRun,
} from '../api/projects'
import { Spinner } from '../components/common/Spinner'
import { StatusBadge } from '../components/common/StatusBadge'
import { SubtitleExportPanel } from '../components/project/SubtitleExportPanel'
import { SubtitleEditor } from '../components/project/SubtitleEditor'
import { usePolling } from '../hooks/usePolling'

const stageOrder: { index: number; name: StageName; label: string }[] = [
    { index: 1, name: 'audio_preprocess', label: '音频处理' },
    { index: 2, name: 'vad', label: 'VAD 切分' },
    { index: 3, name: 'asr', label: 'ASR 识别' },
    { index: 4, name: 'llm_asr_correction', label: 'LLM ASR 纠错' },
    { index: 5, name: 'llm', label: 'LLM 翻译' },
]

function nextStage(currentStage: number): StageName | null {
    const next = stageOrder.find((s) => s.index === currentStage + 1)
    return next ? next.name : null
}

export default function ProjectDetailPage() {
    const { projectId } = useParams<{ projectId: string }>()
    const navigate = useNavigate()

    const [expandedStage, setExpandedStage] = useState<StageName | null>(null)
    const [showEditor, setShowEditor] = useState(false)

    const fetcher = useCallback((signal: AbortSignal) => {
        if (!projectId) throw new Error('No project ID')
        return getProject(projectId, { signal })
    }, [projectId])

    const { data: project, loading, error, refetch } = usePolling<Project>({
        fetcher,
        interval: 5000, // 5 seconds - balanced between responsiveness and server load
        enabled: !!projectId,
        shouldStop: (data) => data.status === 'completed',
    })

    const handleRunNext = async () => {
        if (!projectId || !project) return
        if (project.status === 'failed' && failedStage) {
            await retryStage(projectId, failedStage.name)
            refetch()
            return
        }
        const s = nextStage(project.current_stage)
        if (!s) return
        await runStage(projectId, s)
        refetch()
    }

    const handleRunAll = async () => {
        if (!projectId) return
        await runAll(projectId)
        refetch()
    }

    const handleRetry = async (stage?: StageName) => {
        if (!projectId) return
        await retryStage(projectId, stage)
        refetch()
    }

    const handleDelete = async () => {
        if (!projectId) return
        if (!window.confirm('确认删除该项目？此操作不可恢复。')) return
        await deleteProject(projectId)
        navigate('/projects')
    }

    const latestStageRuns = useMemo(() => {
        const out = new Map<StageName, StageRun>()
        if (!project) return out
        for (const r of project.stage_runs || []) {
            out.set(r.stage, r)
        }
        return out
    }, [project])

    const failedStage = useMemo(() => {
        return stageOrder.find((s) => latestStageRuns.get(s.name)?.status === 'failed') || null
    }, [latestStageRuns])

    const formatTime = (iso?: string | null) => {
        if (!iso) return '-'
        const dt = new Date(iso)
        if (Number.isNaN(dt.getTime())) return iso
        return dt.toLocaleString()
    }

    const formatRate = (value?: number | null, unit = 'items/s') => {
        if (typeof value !== 'number' || !Number.isFinite(value)) return null
        return `${value.toFixed(2)} ${unit}`
    }

    const formatInt = (value?: number | null) => {
        if (typeof value !== 'number' || !Number.isFinite(value)) return null
        return `${Math.trunc(value)}`
    }

    // Check if LLM stage is completed
    const hasLLMCompleted = useMemo(() => {
        if (!project) return false
        return project.current_stage >= 5
    }, [project])

    // 计算项目完成汇总统计
    const projectSummary = useMemo(() => {
        if (!project || project.status !== 'completed') return null
        const runs = project.stage_runs || []

        // 总耗时
        const totalDurationMs = runs.reduce((acc, r) => acc + (r.duration_ms || 0), 0)

        // 从 LLM 翻译阶段获取段落数和 LLM 统计
        const llmRun = runs.find(r => r.stage === 'llm')
        const asrSegments = llmRun?.metrics?.items_total || 0
        const llmCalls = llmRun?.metrics?.llm_calls_count || 0
        const promptTokens = llmRun?.metrics?.llm_prompt_tokens || 0
        const completionTokens = llmRun?.metrics?.llm_completion_tokens || 0
        const totalTokens = promptTokens + completionTokens

        // 格式化耗时
        const formatDuration = (ms: number) => {
            if (ms >= 60000) {
                const mins = Math.floor(ms / 60000)
                const secs = Math.floor((ms % 60000) / 1000)
                return `${mins}m ${secs}s`
            }
            return `${(ms / 1000).toFixed(1)}s`
        }

        return {
            totalDuration: formatDuration(totalDurationMs),
            asrSegments,
            llmCalls,
            totalTokens,
        }
    }, [project])

    if (loading && !project) {
        return (
            <div className="flex items-center justify-center py-20">
                <Spinner size="lg" />
            </div>
        )
    }

    if (error && !project) {
        return (
            <div className="max-w-2xl mx-auto">
                <div className="glass-card p-8 text-center">
                    <div className="text-5xl mb-4">⚠️</div>
                    <h2 className="text-xl font-semibold mb-2">加载失败</h2>
                    <p className="text-[--color-text-muted] mb-6">{error.message}</p>
                    <Link to="/projects" className="btn-primary inline-block">
                        返回列表
                    </Link>
                </div>
            </div>
        )
    }

    if (!project) return null

    return (
        <div className="animate-fade-in">
            {/* Back link */}
            <div className="mb-6">
                <Link
                    to="/projects"
                    className="inline-flex items-center gap-2 text-[--color-text-muted] hover:text-[--color-text] text-sm transition-colors"
                >
                    <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 19l-7-7 7-7" />
                    </svg>
                    返回项目列表
                </Link>
            </div>

            {/* Project Header */}
            <div className="glass-card p-6 mb-8">
                <div className="flex flex-col md:flex-row md:items-center justify-between gap-4 mb-6">
                    <div>
                        <h1 className="text-2xl font-bold text-gradient mb-2">
                            {project.name || `项目 #${project.id.slice(0, 8)}`}
                        </h1>
                        <p className="text-sm text-[--color-text-muted] font-mono">
                            {project.id}
                        </p>
                    </div>
                    <StatusBadge status={project.status} />
                </div>

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

                {/* Action Buttons */}
                {project.status === 'completed' ? (
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
                            <button onClick={() => setShowEditor(true)} className="btn-primary">
                                <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M11 5H6a2 2 0 00-2 2v11a2 2 0 002 2h11a2 2 0 002-2v-5m-1.414-9.414a2 2 0 112.828 2.828L11.828 15H9v-2.828l8.586-8.586z" />
                                </svg>
                                编辑字幕
                            </button>
                            <button onClick={handleDelete} className="btn-danger">
                                <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" />
                                </svg>
                                删除
                            </button>
                        </div>
                    </div>
                ) : (
                    <div className="flex flex-wrap gap-3">
                        {project.status === 'failed' && failedStage && (
                            <button
                                onClick={() => handleRetry(failedStage.name)}
                                disabled={project.status === 'processing'}
                                className="btn-warning"
                            >
                                <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 4v6h6M20 20v-6h-6" />
                                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M20 11a8 8 0 00-14.9-3M4 13a8 8 0 0014.9 3" />
                                </svg>
                                重试 {failedStage.label}
                            </button>
                        )}
                        <button
                            onClick={handleRunNext}
                            disabled={project.status === 'processing'}
                            className="btn-primary"
                        >
                            <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M14.752 11.168l-3.197-2.132A1 1 0 0010 9.87v4.263a1 1 0 001.555.832l3.197-2.132a1 1 0 000-1.664z" />
                            </svg>
                            {project.status === 'processing' ? '处理中...' : '执行下一步'}
                        </button>
                        <button
                            onClick={handleRunAll}
                            disabled={project.status === 'processing'}
                            className="btn-secondary"
                        >
                            <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13 5l7 7-7 7M5 5l7 7-7 7" />
                            </svg>
                            执行全部
                        </button>
                        <button onClick={handleDelete} className="btn-danger ml-auto">
                            <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" />
                            </svg>
                            删除项目
                        </button>
                    </div>
                )}
            </div>

            {/* Stage Pipeline */}
            <div className="glass-card p-6 mb-8">
                <h2 className="text-lg font-semibold mb-4">处理流程</h2>
                <div className="space-y-3">
                    {stageOrder.map((s, idx) => {
                        const run = latestStageRuns.get(s.name)
                        const status = run?.status || 'pending'
                        const expanded = expandedStage === s.name
                        const isLast = idx === stageOrder.length - 1

                        const stageBaseClass =
                            'border rounded-xl overflow-hidden transition-all border-[--color-border] bg-[rgba(15,23,42,0.4)]'
                        const stageStateClass =
                            status === 'completed'
                                ? 'border-[rgba(16,185,129,0.3)] bg-[rgba(16,185,129,0.05)]'
                                : status === 'running'
                                    ? 'border-[rgba(99,102,241,0.4)] bg-[rgba(99,102,241,0.08)] shadow-[var(--shadow-glow-primary)]'
                                    : status === 'failed'
                                        ? 'border-[rgba(239,68,68,0.3)] bg-[rgba(239,68,68,0.05)]'
                                        : ''

                        // 连接线样式
                        const connectorClass = status === 'completed'
                            ? 'stage-connector stage-connector-completed'
                            : status === 'running'
                                ? 'stage-connector stage-connector-running'
                                : 'stage-connector stage-connector-pending'

                        // 圆点样式
                        const nodeClass = status === 'completed'
                            ? 'stage-node stage-node-completed'
                            : status === 'running'
                                ? 'stage-node stage-node-running'
                                : status === 'failed'
                                    ? 'stage-node stage-node-failed'
                                    : 'stage-node stage-node-pending'

                        return (
                            <div key={s.name} className="relative">
                                {/* 连接线 (不在最后一个阶段显示) */}
                                {!isLast && (
                                    <div className={connectorClass} />
                                )}
                                <div className={`${stageBaseClass} ${stageStateClass}`}>
                                    <div
                                        className="flex items-center justify-between px-5 py-4 cursor-pointer transition-colors hover:bg-[--color-bg-hover]"
                                        onClick={() => setExpandedStage(expanded ? null : s.name)}
                                    >
                                        <div className="flex items-center gap-4">
                                            <div className={nodeClass}>
                                                {status === 'completed' ? '✓' : s.index}
                                            </div>
                                            <div>
                                                <div className="font-medium">{s.label}</div>
                                                <div className="text-xs text-[--color-text-muted]">{s.name}</div>
                                            </div>
                                        </div>
                                        <div className="flex items-center gap-3">
                                            {/* 已完成阶段显示耗时 */}
                                            {status === 'completed' && typeof run?.duration_ms === 'number' && (
                                                <span className="text-xs text-[--color-text-muted] font-mono">
                                                    {run.duration_ms >= 60000
                                                        ? `${Math.floor(run.duration_ms / 60000)}m ${((run.duration_ms % 60000) / 1000).toFixed(0)}s`
                                                        : `${(run.duration_ms / 1000).toFixed(1)}s`}
                                                </span>
                                            )}
                                            <StatusBadge status={status} size="sm" />
                                            <svg
                                                className={`w-4 h-4 text-[--color-text-muted] transition-transform ${expanded ? 'rotate-180' : ''}`}
                                                fill="none" stroke="currentColor" viewBox="0 0 24 24"
                                            >
                                                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
                                            </svg>
                                        </div>
                                    </div>


                                    {status === 'running' && (
                                        <div className="px-5 pb-4">
                                            <div className="progress-bar">
                                                <div
                                                    className="progress-bar-fill"
                                                    style={{ width: `${Math.max(0, Math.min(100, run?.progress ?? 0))}%` }}
                                                />
                                            </div>
                                            <div className="mt-2 text-xs text-[--color-text-muted]">
                                                {run?.progress_message || '处理中...'} {typeof run?.progress === 'number' ? `(${run.progress}%)` : ''}
                                            </div>
                                            {/* 重试状态提示 */}
                                            {run?.metrics?.retry_status === 'retrying' && (
                                                <div className="mt-2 flex items-center gap-2 text-xs px-3 py-2 rounded-lg bg-[--color-warning]/10 border border-[--color-warning]/30">
                                                    <svg className="w-4 h-4 text-[--color-warning-light] animate-spin" fill="none" viewBox="0 0 24 24">
                                                        <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                                                        <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z" />
                                                    </svg>
                                                    <span className="text-[--color-warning-light]">
                                                        自动重试中 ({run.metrics.retry_count}/{run.metrics.retry_max}) - {run.metrics.retry_reason}
                                                    </span>
                                                </div>
                                            )}
                                            {run?.metrics?.retry_status === 'recovered' && (
                                                <div className="mt-2 flex items-center gap-2 text-xs px-3 py-2 rounded-lg bg-[--color-success]/10 border border-[--color-success]/30">
                                                    <svg className="w-4 h-4 text-[--color-success-light]" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
                                                    </svg>
                                                    <span className="text-[--color-success-light]">重试成功，已自动恢复</span>
                                                </div>
                                            )}
                                            {run?.metrics?.retry_status === 'failed' && (
                                                <div className="mt-2 flex items-center gap-2 text-xs px-3 py-2 rounded-lg bg-[--color-error]/10 border border-[--color-error]/30">
                                                    <svg className="w-4 h-4 text-[--color-error-light]" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z" />
                                                    </svg>
                                                    <span className="text-[--color-error-light]">重试失败 - {run.metrics.retry_reason}</span>
                                                </div>
                                            )}
                                            {(run?.metrics && (
                                                <div className="mt-2 flex flex-wrap gap-2 text-[11px] text-[--color-text-muted]">
                                                    {formatRate(run.metrics.items_per_second, 'items/s') && (
                                                        <span className="px-2 py-1 rounded-md bg-[--color-bg]/40 border border-[--color-border]">
                                                            速率: {formatRate(run.metrics.items_per_second, 'items/s')}
                                                        </span>
                                                    )}
                                                    {formatRate(run.metrics.llm_tokens_per_second, 'tokens/s') && (
                                                        <span className="px-2 py-1 rounded-md bg-[--color-bg]/40 border border-[--color-border]">
                                                            LLM: {formatRate(run.metrics.llm_tokens_per_second, 'tokens/s')}
                                                        </span>
                                                    )}
                                                    {formatInt(run.metrics.active_tasks) && formatInt(run.metrics.max_concurrent) && (
                                                        <span className="px-2 py-1 rounded-md bg-[--color-bg]/40 border border-[--color-border]">
                                                            并发: {formatInt(run.metrics.active_tasks)}/{formatInt(run.metrics.max_concurrent)}
                                                        </span>
                                                    )}
                                                    {formatInt(run.metrics.llm_prompt_tokens) && formatInt(run.metrics.llm_completion_tokens) && (
                                                        <span className="px-2 py-1 rounded-md bg-[--color-bg]/40 border border-[--color-border]">
                                                            tokens: {formatInt(run.metrics.llm_prompt_tokens)}/{formatInt(run.metrics.llm_completion_tokens)}
                                                        </span>
                                                    )}
                                                </div>
                                            )) || null}
                                        </div>
                                    )}

                                    {expanded && (
                                        <div className="px-5 pt-4 pb-5 border-t border-[--color-border] animate-fade-in">
                                            <div className="grid gap-3 md:grid-cols-2 text-sm">
                                                <div className="p-3 rounded-lg bg-[--color-bg]/50 border border-[--color-border]">
                                                    <div className="text-xs text-[--color-text-muted]">开始时间</div>
                                                    <div className="mt-1 text-xs font-mono">{formatTime(run?.started_at)}</div>
                                                </div>
                                                <div className="p-3 rounded-lg bg-[--color-bg]/50 border border-[--color-border]">
                                                    <div className="text-xs text-[--color-text-muted]">完成时间</div>
                                                    <div className="mt-1 text-xs font-mono">{formatTime(run?.completed_at)}</div>
                                                </div>
                                                <div className="p-3 rounded-lg bg-[--color-bg]/50 border border-[--color-border]">
                                                    <div className="text-xs text-[--color-text-muted]">耗时</div>
                                                    <div className="mt-1 text-xs font-mono">
                                                        {typeof run?.duration_ms === 'number' ? `${(run.duration_ms / 1000).toFixed(2)}s` : '-'}
                                                    </div>
                                                </div>
                                                <div className="p-3 rounded-lg bg-[--color-bg]/50 border border-[--color-border]">
                                                    <div className="text-xs text-[--color-text-muted]">状态</div>
                                                    <div className="mt-1 text-xs font-mono">{status}</div>
                                                </div>
                                                {run?.metrics && (
                                                    <div className="md:col-span-2 p-3 rounded-lg bg-[--color-bg]/50 border border-[--color-border]">
                                                        <div className="text-xs text-[--color-text-muted] mb-2">实时指标</div>
                                                        <div className="flex flex-wrap gap-2 text-xs font-mono">
                                                            {typeof run.metrics.items_processed === 'number' && typeof run.metrics.items_total === 'number' && (
                                                                <span className="px-2 py-1 rounded-md bg-[--color-bg]/40 border border-[--color-border]">
                                                                    items: {formatInt(run.metrics.items_processed)}/{formatInt(run.metrics.items_total)}
                                                                </span>
                                                            )}
                                                            {formatRate(run.metrics.items_per_second, 'items/s') && (
                                                                <span className="px-2 py-1 rounded-md bg-[--color-bg]/40 border border-[--color-border]">
                                                                    items/s: {formatRate(run.metrics.items_per_second, 'items/s')}
                                                                </span>
                                                            )}
                                                            {typeof run.metrics.llm_prompt_tokens === 'number' && typeof run.metrics.llm_completion_tokens === 'number' && (
                                                                <span className="px-2 py-1 rounded-md bg-[--color-bg]/40 border border-[--color-border]">
                                                                    prompt/completion: {formatInt(run.metrics.llm_prompt_tokens)}/{formatInt(run.metrics.llm_completion_tokens)}
                                                                </span>
                                                            )}
                                                            {formatRate(run.metrics.llm_tokens_per_second, 'tokens/s') && (
                                                                <span className="px-2 py-1 rounded-md bg-[--color-bg]/40 border border-[--color-border]">
                                                                    tokens/s: {formatRate(run.metrics.llm_tokens_per_second, 'tokens/s')}
                                                                </span>
                                                            )}
                                                            {formatInt(run.metrics.active_tasks) && formatInt(run.metrics.max_concurrent) && (
                                                                <span className="px-2 py-1 rounded-md bg-[--color-bg]/40 border border-[--color-border]">
                                                                    active: {formatInt(run.metrics.active_tasks)}/{formatInt(run.metrics.max_concurrent)}
                                                                </span>
                                                            )}
                                                            {formatInt(run.metrics.llm_calls_count) && (
                                                                <span className="px-2 py-1 rounded-md bg-[--color-bg]/40 border border-[--color-border]">
                                                                    llm_calls: {formatInt(run.metrics.llm_calls_count)}
                                                                </span>
                                                            )}
                                                        </div>
                                                    </div>
                                                )}

                                                {status === 'failed' && (
                                                    <div className="md:col-span-2 p-3 rounded-lg bg-[--color-error]/10 border border-[--color-error]/30">
                                                        <div className="text-xs text-[--color-error-light] font-medium">错误信息</div>
                                                        <div className="mt-1 text-xs font-mono text-[--color-error-light]">
                                                            [{run?.error_code || 'UNKNOWN'}] {run?.error_message || run?.error || 'stage failed'}
                                                        </div>
                                                    </div>
                                                )}
                                            </div>
                                        </div>
                                    )}
                                </div>
                            </div>
                        )
                    })}
                </div>
            </div>

            {/* 项目完成汇总统计 */}
            {projectSummary && (
                <div className="summary-panel mb-8">
                    <div className="summary-panel-title">
                        <svg className="w-5 h-5 text-[--color-success-light]" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 19v-6a2 2 0 00-2-2H5a2 2 0 00-2 2v6a2 2 0 002 2h2a2 2 0 002-2zm0 0V9a2 2 0 012-2h2a2 2 0 012 2v10m-6 0a2 2 0 002 2h2a2 2 0 002-2m0 0V5a2 2 0 012-2h2a2 2 0 012 2v14a2 2 0 01-2 2h-2a2 2 0 01-2-2z" />
                        </svg>
                        处理完成 - 总览
                    </div>
                    <div className="summary-grid">
                        <div className="summary-item">
                            <div className="summary-item-label">总耗时</div>
                            <div className="summary-item-value">{projectSummary.totalDuration}</div>
                        </div>
                        <div className="summary-item">
                            <div className="summary-item-label">ASR 段落</div>
                            <div className="summary-item-value">{projectSummary.asrSegments} 段</div>
                        </div>
                        <div className="summary-item">
                            <div className="summary-item-label">LLM 调用</div>
                            <div className="summary-item-value">{projectSummary.llmCalls} 次</div>
                        </div>
                        <div className="summary-item">
                            <div className="summary-item-label">Token 消耗</div>
                            <div className="summary-item-value">
                                {projectSummary.totalTokens >= 1000
                                    ? `${(projectSummary.totalTokens / 1000).toFixed(1)}k`
                                    : projectSummary.totalTokens}
                            </div>
                        </div>
                    </div>
                </div>
            )}

            {/* Subtitle Export Panel */}
            {projectId && (
                <SubtitleExportPanel
                    projectId={projectId}
                    hasLLMCompleted={hasLLMCompleted}
                />
            )}

            {/* Subtitle Editor Modal */}
            {showEditor && projectId && (
                <SubtitleEditor
                    projectId={projectId}
                    onClose={() => setShowEditor(false)}
                />
            )}
        </div>
    )
}
