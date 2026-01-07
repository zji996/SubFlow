import { useCallback, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { getProject, getSubtitles, runAll, runStage, type Project, type StageName, type SubtitlePreview } from '../api/projects'
import { Spinner } from '../components/Spinner'
import { StatusBadge } from '../components/StatusBadge'
import { usePolling } from '../hooks/usePolling'

const stageOrder: { index: number; name: StageName; label: string }[] = [
    { index: 1, name: 'audio_preprocess', label: '音频处理' },
    { index: 2, name: 'vad', label: 'VAD 切分' },
    { index: 3, name: 'asr', label: 'ASR 识别' },
    { index: 4, name: 'llm', label: 'LLM 处理' },
    { index: 5, name: 'export', label: '导出字幕' },
]

function nextStage(currentStage: number): StageName | null {
    const next = stageOrder.find((s) => s.index === currentStage + 1)
    return next ? next.name : null
}

export default function ProjectDetailPage() {
    const { projectId } = useParams<{ projectId: string }>()
    const [subtitlePreview, setSubtitlePreview] = useState<SubtitlePreview | null>(null)
    const [subtitleLoading, setSubtitleLoading] = useState(false)
    const [subtitleError, setSubtitleError] = useState<string | null>(null)

    const fetcher = useCallback(() => {
        if (!projectId) throw new Error('No project ID')
        return getProject(projectId)
    }, [projectId])

    const { data: project, loading, error } = usePolling<Project>({
        fetcher,
        interval: 2000,
        enabled: !!projectId,
    })

    const handleRunNext = async () => {
        if (!projectId || !project) return
        const s = nextStage(project.current_stage)
        await runStage(projectId, s || undefined)
    }

    const handleRunAll = async () => {
        if (!projectId) return
        await runAll(projectId)
    }

    const handleLoadSubtitles = async () => {
        if (!projectId) return
        setSubtitleLoading(true)
        setSubtitleError(null)
        try {
            const preview = await getSubtitles(projectId)
            setSubtitlePreview(preview)
        } catch (err) {
            setSubtitleError(err instanceof Error ? err.message : 'Failed to load subtitles')
        } finally {
            setSubtitleLoading(false)
        }
    }

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

    const exportArtifacts = (project.artifacts || {})['export'] || {}
    const downloadUrl: string | undefined = exportArtifacts['subtitles.srt_url']
    const localPath: string | undefined = exportArtifacts['subtitles.srt']
    const hasExport = Boolean(downloadUrl || localPath)

    return (
        <div className="max-w-4xl mx-auto">
            <div className="mb-6">
                <Link
                    to="/projects"
                    className="text-[--color-text-muted] hover:text-[--color-text] text-sm flex items-center gap-2"
                >
                    <span>←</span> 返回项目列表
                </Link>
            </div>

            <div className="glass-card p-8">
                <div className="flex items-start justify-between gap-4 mb-8">
                    <div className="min-w-0">
                        <h1 className="text-2xl font-bold mb-2 truncate">{project.name}</h1>
                        <p className="text-sm text-[--color-text-muted] font-mono">{project.id}</p>
                        <p className="text-sm text-[--color-text-muted] mt-2 truncate">
                            {project.media_url}
                        </p>
                    </div>
                    <StatusBadge status={project.status} />
                </div>

                <div className="grid gap-3 md:grid-cols-2 mb-8">
                    <div className="p-4 rounded-lg bg-[--color-bg] border border-[--color-border]">
                        <div className="text-xs text-[--color-text-muted]">source_language</div>
                        <div className="mt-1 text-sm">{project.source_language || 'auto'}</div>
                    </div>
                    <div className="p-4 rounded-lg bg-[--color-bg] border border-[--color-border]">
                        <div className="text-xs text-[--color-text-muted]">target_language</div>
                        <div className="mt-1 text-sm">{project.target_language}</div>
                    </div>
                </div>

                <div className="flex gap-3 mb-10">
                    <button onClick={handleRunNext} className="btn-primary">
                        执行下一步
                    </button>
                    <button onClick={handleRunAll} className="btn-secondary">
                        执行全部
                    </button>
                </div>

                <div className="space-y-3">
                    {stageOrder.map((s) => {
                        const done = project.current_stage >= s.index
                        const active = project.current_stage + 1 === s.index && project.status === 'processing'
                        return (
                            <div
                                key={s.name}
                                className={`flex items-center justify-between p-4 rounded-lg border ${done
                                        ? 'border-green-500/30 bg-green-500/5'
                                        : active
                                            ? 'border-indigo-500/30 bg-indigo-500/5'
                                            : 'border-[--color-border] bg-[--color-bg]'
                                    }`}
                            >
                                <div className="flex items-center gap-3">
                                    <span>{done ? '✅' : active ? '⏳' : '⏸️'}</span>
                                    <div>
                                        <div className="font-medium">{s.label}</div>
                                        <div className="text-xs text-[--color-text-muted]">{s.name}</div>
                                    </div>
                                </div>
                                <div className="text-xs text-[--color-text-muted]">Stage {s.index}</div>
                            </div>
                        )
                    })}
                </div>

                {hasExport && (
                    <div className="mt-10 p-4 rounded-lg border border-[--color-border] bg-[--color-bg]">
                        <div className="text-sm font-medium mb-2">Export</div>
                        {downloadUrl ? (
                            <a className="text-indigo-400 hover:text-indigo-300 text-sm" href={downloadUrl}>
                                下载字幕（S3 预签名 URL）
                            </a>
                        ) : (
                            <div className="text-xs text-[--color-text-muted] font-mono">{localPath}</div>
                        )}

                        <div className="mt-4 flex items-center gap-3">
                            <button onClick={handleLoadSubtitles} className="btn-secondary" disabled={subtitleLoading}>
                                {subtitleLoading ? '加载中…' : subtitlePreview ? '刷新预览' : '预览字幕'}
                            </button>
                            {subtitlePreview && (
                                <div className="text-xs text-[--color-text-muted]">
                                    source: <span className="font-mono">{subtitlePreview.source}</span>
                                </div>
                            )}
                        </div>

                        {subtitleError && (
                            <div className="mt-3 text-sm text-red-400">{subtitleError}</div>
                        )}

                        {subtitlePreview && (
                            <pre className="mt-4 max-h-[420px] overflow-auto rounded-lg border border-[--color-border] bg-black/30 p-4 text-xs leading-relaxed whitespace-pre-wrap">
                                {subtitlePreview.content}
                            </pre>
                        )}
                    </div>
                )}
            </div>
        </div>
    )
}
