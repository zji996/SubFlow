import { useMemo, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { Spinner } from '../components/common/Spinner'
import { SubtitleExportPanel } from '../components/project/SubtitleExportPanel'
import { SubtitleEditor } from '../components/project/SubtitleEditor'
import { ProjectActions } from '../components/project/detail/ProjectActions'
import { ProjectHeader } from '../components/project/detail/ProjectHeader'
import { ProjectInfo } from '../components/project/detail/ProjectInfo'
import { ProjectPipeline } from '../components/project/detail/ProjectPipeline'
import { useProject } from '../hooks/useProject'
import { formatDuration } from '../utils'

export default function ProjectDetailPage() {
    const { projectId } = useParams<{ projectId: string }>()
    const navigate = useNavigate()

    const [showEditor, setShowEditor] = useState(false)

    const { data: project, loading, error, runNext, runAll, retryStage, deleteProject, failedStage, hasLLMCompleted } =
        useProject(projectId)

    const projectSummary = useMemo(() => {
        if (!project || project.status !== 'completed') return null
        const runs = project.stage_runs || []

        const totalDurationMs = runs.reduce((acc, r) => acc + (r.duration_ms || 0), 0)
        const llmRun = runs.find((r) => r.stage === 'llm')
        const asrSegments = llmRun?.metrics?.items_total || 0
        const llmCalls = llmRun?.metrics?.llm_calls_count || 0
        const promptTokens = llmRun?.metrics?.llm_prompt_tokens || 0
        const completionTokens = llmRun?.metrics?.llm_completion_tokens || 0
        const totalTokens = promptTokens + completionTokens

        return {
            totalDuration: formatDuration(totalDurationMs, { unit: 'ms', style: 'human' }),
            asrSegments,
            llmCalls,
            totalTokens,
        }
    }, [project])

    const handleDelete = async () => {
        if (!projectId) return
        if (!window.confirm('确认删除该项目？此操作不可恢复。')) return
        const ok = await deleteProject()
        if (ok) navigate('/projects')
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
                    <p className="text-[--color-text-muted] mb-6">{error}</p>
                    <Link to="/projects" className="btn-primary inline-block">
                        返回列表
                    </Link>
                </div>
            </div>
        )
    }

    if (!project || !projectId) return null

    return (
        <div className="animate-fade-in">
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

            <div className="glass-card p-6 mb-8">
                <ProjectHeader project={project} />
                <ProjectInfo project={project} />
                <ProjectActions
                    project={project}
                    projectId={projectId}
                    failedStage={failedStage ? { name: failedStage.name, label: failedStage.label } : null}
                    onRunNext={runNext}
                    onRunAll={runAll}
                    onRetry={retryStage}
                    onEditSubtitles={() => setShowEditor(true)}
                    onDelete={handleDelete}
                />
                {error && (
                    <div className="mt-4 text-sm text-[--color-error-light]">{error}</div>
                )}
            </div>

            <ProjectPipeline project={project} />

            {projectSummary && (
                <div className="summary-panel mb-8">
                    <div className="summary-panel-title">
                        <svg className="w-5 h-5 text-[--color-success-light]" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                            <path
                                strokeLinecap="round"
                                strokeLinejoin="round"
                                strokeWidth={2}
                                d="M9 19v-6a2 2 0 00-2-2H5a2 2 0 00-2 2v6a2 2 0 002 2h2a2 2 0 002-2zm0 0V9a2 2 0 012-2h2a2 2 0 012 2v10m-6 0a2 2 0 002 2h2a2 2 0 002-2m0 0V5a2 2 0 012-2h2a2 2 0 012 2v14a2 2 0 01-2 2h-2a2 2 0 01-2-2z"
                            />
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

            <SubtitleExportPanel projectId={projectId} hasLLMCompleted={hasLLMCompleted} />

            {showEditor && (
                <SubtitleEditor projectId={projectId} onClose={() => setShowEditor(false)} />
            )}
        </div>
    )
}

