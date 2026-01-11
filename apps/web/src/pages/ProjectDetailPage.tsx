import { useCallback, useMemo, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import {
    deleteProject,
    getArtifactContent,
    getProject,
    runAll,
    runStage,
    type ArtifactContentResponse,
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
    const [artifactPreview, setArtifactPreview] = useState<ArtifactContentResponse | null>(null)
    const [artifactLoading, setArtifactLoading] = useState(false)
    const [artifactError, setArtifactError] = useState<string | null>(null)
    const [showEditor, setShowEditor] = useState(false)

    const fetcher = useCallback((signal: AbortSignal) => {
        if (!projectId) throw new Error('No project ID')
        return getProject(projectId, { signal })
    }, [projectId])

    const { data: project, loading, error } = usePolling<Project>({
        fetcher,
        interval: 2000,
        enabled: !!projectId,
    })

    const handleRunNext = async () => {
        if (!projectId || !project) return
        const s = nextStage(project.current_stage)
        if (!s) return
        await runStage(projectId, s)
    }

    const handleRunAll = async () => {
        if (!projectId) return
        await runAll(projectId)
    }

    const handleDelete = async () => {
        if (!projectId) return
        if (!window.confirm('确认删除该项目？此操作不可恢复。')) return
        await deleteProject(projectId)
        navigate('/projects')
    }

    const handlePreviewArtifact = async (stage: StageName, name: string) => {
        if (!projectId) return
        setArtifactLoading(true)
        setArtifactError(null)
        try {
            const res = await getArtifactContent(projectId, stage, name)
            setArtifactPreview(res)
        } catch (err) {
            setArtifactError(err instanceof Error ? err.message : 'Failed to load artifact')
        } finally {
            setArtifactLoading(false)
        }
    }

    const latestStageRuns = useMemo(() => {
        const out = new Map<StageName, StageRun>()
        if (!project) return out
        for (const r of project.stage_runs || []) {
            out.set(r.stage, r)
        }
        return out
    }, [project])

    const formatTime = (iso?: string | null) => {
        if (!iso) return '-'
        const dt = new Date(iso)
        if (Number.isNaN(dt.getTime())) return iso
        return dt.toLocaleString()
    }

    // Check if LLM stage is completed
    const hasLLMCompleted = useMemo(() => {
        if (!project) return false
        return project.current_stage >= 5
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
                    {stageOrder.map((s) => {
                        const run = latestStageRuns.get(s.name)
                        const status = run?.status || 'pending'
                        const expanded = expandedStage === s.name
                        const outputArtifacts = run?.output_artifacts || {}
                        const artifactNames = Object.keys(outputArtifacts)

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

                        return (
                            <div key={s.name} className={`${stageBaseClass} ${stageStateClass}`}>
                                <div
                                    className="flex items-center justify-between px-5 py-4 cursor-pointer transition-colors hover:bg-[--color-bg-hover]"
                                    onClick={() => setExpandedStage(expanded ? null : s.name)}
                                >
                                    <div className="flex items-center gap-3">
                                        <div className={`w-8 h-8 rounded-lg flex items-center justify-center text-sm font-medium ${status === 'completed' ? 'bg-[--color-success]/20 text-[--color-success-light]' :
                                            status === 'running' ? 'bg-[--color-primary]/20 text-[--color-primary-light]' :
                                                status === 'failed' ? 'bg-[--color-error]/20 text-[--color-error-light]' :
                                                    'bg-[--color-bg-hover] text-[--color-text-muted]'
                                            }`}>
                                            {status === 'completed' ? '✓' : s.index}
                                        </div>
                                        <div>
                                            <div className="font-medium">{s.label}</div>
                                            <div className="text-xs text-[--color-text-muted]">{s.name}</div>
                                        </div>
                                    </div>
                                    <div className="flex items-center gap-3">
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

                                            {status === 'failed' && (
                                                <div className="md:col-span-2 p-3 rounded-lg bg-[--color-error]/10 border border-[--color-error]/30">
                                                    <div className="text-xs text-[--color-error-light] font-medium">错误信息</div>
                                                    <div className="mt-1 text-xs font-mono text-[--color-error-light]">
                                                        [{run?.error_code || 'UNKNOWN'}] {run?.error_message || run?.error || 'stage failed'}
                                                    </div>
                                                </div>
                                            )}

                                            <div className="md:col-span-2 p-3 rounded-lg bg-[--color-bg]/50 border border-[--color-border]">
                                                <div className="flex items-center justify-between gap-3 mb-2">
                                                    <div className="text-xs text-[--color-text-muted]">输出产物</div>
                                                    <div className="text-xs text-[--color-text-dim]">{artifactNames.length} 个文件</div>
                                                </div>
                                                {artifactNames.length === 0 ? (
                                                    <div className="text-xs text-[--color-text-dim]">暂无</div>
                                                ) : (
                                                    <div className="space-y-2">
                                                        {artifactNames.map((name) => (
                                                            <div key={name} className="flex items-center justify-between gap-3">
                                                                <div className="min-w-0">
                                                                    <div className="text-xs font-mono truncate">{name}</div>
                                                                </div>
                                                                <button
                                                                    className="text-xs text-[--color-primary-light] hover:underline shrink-0"
                                                                    onClick={(e) => {
                                                                        e.stopPropagation()
                                                                        handlePreviewArtifact(s.name, name)
                                                                    }}
                                                                    disabled={artifactLoading}
                                                                >
                                                                    {artifactLoading ? '加载中...' : '预览'}
                                                                </button>
                                                            </div>
                                                        ))}
                                                    </div>
                                                )}
                                            </div>
                                        </div>
                                    </div>
                                )}
                            </div>
                        )
                    })}
                </div>
            </div>

            {/* Artifact Preview Modal */}
            {(artifactError || artifactPreview) && (
                <div className="glass-card p-6 mb-8 animate-fade-in">
                    <div className="flex items-center justify-between gap-3 mb-4">
                        <div className="text-lg font-semibold">产物预览</div>
                        <button
                            className="btn-icon"
                            onClick={() => {
                                setArtifactPreview(null)
                                setArtifactError(null)
                            }}
                        >
                            <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
                            </svg>
                        </button>
                    </div>
                    {artifactError && <div className="text-sm text-[--color-error-light]">{artifactError}</div>}
                    {artifactPreview && (
                        <>
                            <div className="text-sm text-[--color-text-muted] mb-3">
                                {artifactPreview.stage} / {artifactPreview.name}
                            </div>
                            <pre className="code-preview">
                                {artifactPreview.kind === 'json'
                                    ? JSON.stringify(artifactPreview.data, null, 2).slice(0, 20000)
                                    : artifactPreview.data.slice(0, 20000)}
                            </pre>
                        </>
                    )}
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
