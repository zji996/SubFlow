import { useMemo, useState } from 'react'
import { STAGE_ORDER } from '../../../constants/stages'
import type { Project, StageName, StageRun } from '../../../types/entities'
import { formatDuration, formatTime } from '../../../utils'
import { StatusBadge } from '../../common/StatusBadge'

function formatRate(value?: number | null, unit = 'items/s') {
    if (typeof value !== 'number' || !Number.isFinite(value)) return null
    return `${value.toFixed(2)} ${unit}`
}

function formatInt(value?: number | null) {
    if (typeof value !== 'number' || !Number.isFinite(value)) return null
    return `${Math.trunc(value)}`
}

function getLatestStageRuns(project: Project): Map<StageName, StageRun> {
    const out = new Map<StageName, StageRun>()
    for (const r of project.stage_runs || []) out.set(r.stage, r)
    return out
}

export function ProjectPipeline({ project }: { project: Project }) {
    const [expandedStage, setExpandedStage] = useState<StageName | null>(null)

    const latestStageRuns = useMemo(() => getLatestStageRuns(project), [project])

    return (
        <div className="glass-card p-6 mb-8">
            <h2 className="text-lg font-semibold mb-4">处理流程</h2>
            <div className="space-y-3">
                {STAGE_ORDER.map((s, idx) => {
                    const run = latestStageRuns.get(s.name)
                    const status = run?.status || 'pending'
                    const expanded = expandedStage === s.name
                    const isLast = idx === STAGE_ORDER.length - 1

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

                    const connectorClass =
                        status === 'completed'
                            ? 'stage-connector stage-connector-completed'
                            : status === 'running'
                                ? 'stage-connector stage-connector-running'
                                : 'stage-connector stage-connector-pending'

                    const nodeClass =
                        status === 'completed'
                            ? 'stage-node stage-node-completed'
                            : status === 'running'
                                ? 'stage-node stage-node-running'
                                : status === 'failed'
                                    ? 'stage-node stage-node-failed'
                                    : 'stage-node stage-node-pending'

                    return (
                        <div key={s.name} className="relative">
                            {!isLast && <div className={connectorClass} />}
                            <div className={`${stageBaseClass} ${stageStateClass}`}>
                                <div
                                    className="flex items-center justify-between px-5 py-4 cursor-pointer transition-colors hover:bg-[--color-bg-hover]"
                                    onClick={() => setExpandedStage(expanded ? null : s.name)}
                                >
                                    <div className="flex items-center gap-4">
                                        <div className={nodeClass}>{status === 'completed' ? '✓' : s.index}</div>
                                        <div>
                                            <div className="font-medium">{s.label}</div>
                                            <div className="text-xs text-[--color-text-muted]">{s.name}</div>
                                        </div>
                                    </div>
                                    <div className="flex items-center gap-3">
                                        {status === 'completed' && typeof run?.duration_ms === 'number' && (
                                            <span className="text-xs text-[--color-text-muted] font-mono">
                                                {formatDuration(run.duration_ms, { unit: 'ms', style: 'human' })}
                                            </span>
                                        )}
                                        <StatusBadge status={status} size="sm" />
                                        <svg
                                            className={`w-4 h-4 text-[--color-text-muted] transition-transform ${expanded ? 'rotate-180' : ''}`}
                                            fill="none"
                                            stroke="currentColor"
                                            viewBox="0 0 24 24"
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
                                            {run?.progress_message || '处理中...'}{' '}
                                            {typeof run?.progress === 'number' ? `(${run.progress}%)` : ''}
                                        </div>
                                    </div>
                                )}

                                {expanded && (
                                    <div className="px-5 pb-5 animate-fade-in border-t border-[--color-border]">
                                        <div className="mt-4">
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
                                                        {typeof run?.duration_ms === 'number'
                                                            ? `${(run.duration_ms / 1000).toFixed(2)}s`
                                                            : '-'}
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
                                                            {typeof run.metrics.items_processed === 'number' &&
                                                                typeof run.metrics.items_total === 'number' && (
                                                                    <span className="px-2 py-1 rounded-md bg-[--color-bg]/40 border border-[--color-border]">
                                                                        items: {formatInt(run.metrics.items_processed)}/
                                                                        {formatInt(run.metrics.items_total)}
                                                                    </span>
                                                                )}
                                                            {formatRate(run.metrics.items_per_second, 'items/s') && (
                                                                <span className="px-2 py-1 rounded-md bg-[--color-bg]/40 border border-[--color-border]">
                                                                    items/s: {formatRate(run.metrics.items_per_second, 'items/s')}
                                                                </span>
                                                            )}
                                                            {typeof run.metrics.llm_prompt_tokens === 'number' &&
                                                                typeof run.metrics.llm_completion_tokens === 'number' && (
                                                                    <span className="px-2 py-1 rounded-md bg-[--color-bg]/40 border border-[--color-border]">
                                                                        prompt/completion: {formatInt(run.metrics.llm_prompt_tokens)}/
                                                                        {formatInt(run.metrics.llm_completion_tokens)}
                                                                    </span>
                                                                )}
                                                            {formatRate(run.metrics.llm_tokens_per_second, 'tokens/s') && (
                                                                <span className="px-2 py-1 rounded-md bg-[--color-bg]/40 border border-[--color-border]">
                                                                    tokens/s: {formatRate(run.metrics.llm_tokens_per_second, 'tokens/s')}
                                                                </span>
                                                            )}
                                                            {formatInt(run.metrics.active_tasks) &&
                                                                formatInt(run.metrics.max_concurrent) && (
                                                                    <span className="px-2 py-1 rounded-md bg-[--color-bg]/40 border border-[--color-border]">
                                                                        active: {formatInt(run.metrics.active_tasks)}/
                                                                        {formatInt(run.metrics.max_concurrent)}
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
                                                            [{run?.error_code || 'UNKNOWN'}]{' '}
                                                            {run?.error_message || run?.error || 'stage failed'}
                                                        </div>
                                                    </div>
                                                )}
                                            </div>
                                        </div>
                                    </div>
                                )}
                            </div>
                        </div>
                    )
                })}
            </div>
        </div>
    )
}

