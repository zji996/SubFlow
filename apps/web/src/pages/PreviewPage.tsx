import { useCallback, useEffect, useMemo, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import {
    getProjectPreview,
    getProjectPreviewSegments,
    type PreviewSegment,
    type ProjectPreviewResponse,
} from '../api/preview'
import { Spinner } from '../components/common/Spinner'

function formatTime(seconds: number): string {
    const mins = Math.floor(seconds / 60)
    const secs = Math.floor(seconds % 60)
    const ms = Math.floor((seconds % 1) * 1000)
    return `${String(mins).padStart(2, '0')}:${String(secs).padStart(2, '0')}.${String(ms).padStart(3, '0')}`
}

function formatDuration(seconds: number): string {
    const mins = Math.floor(seconds / 60)
    const secs = Math.floor(seconds % 60)
    return `${mins}:${String(secs).padStart(2, '0')}`
}

export default function PreviewPage() {
    const { projectId } = useParams<{ projectId: string }>()
    const [preview, setPreview] = useState<ProjectPreviewResponse | null>(null)
    const [segments, setSegments] = useState<PreviewSegment[]>([])
    const [segmentsTotal, setSegmentsTotal] = useState(0)
    const [loading, setLoading] = useState(true)
    const [segmentsLoading, setSegmentsLoading] = useState(false)
    const [segmentsError, setSegmentsError] = useState<string | null>(null)
    const [error, setError] = useState<string | null>(null)
    const [selectedRegion, setSelectedRegion] = useState<number | null>(null)
    const [offset, setOffset] = useState(0)
    const [searchQuery, setSearchQuery] = useState('')
    const limit = 50

    const loadPreview = useCallback(async () => {
        if (!projectId) return
        setLoading(true)
        setError(null)
        try {
            const data = await getProjectPreview(projectId)
            setPreview(data)
        } catch (err) {
            setError(err instanceof Error ? err.message : 'Failed to load preview')
        } finally {
            setLoading(false)
        }
    }, [projectId])

    const loadSegments = useCallback(async (nextOffset: number) => {
        if (!projectId) return
        setSegmentsLoading(true)
        setSegmentsError(null)
        try {
            const data = await getProjectPreviewSegments(projectId, {
                offset: nextOffset,
                limit,
                region_id: selectedRegion ?? undefined,
            })
            setSegments(data.segments)
            setSegmentsTotal(data.total)
            setOffset(nextOffset)
        } catch (err) {
            console.error('Failed to load segments:', err)
            setSegmentsError(err instanceof Error ? err.message : 'Failed to load segments')
        } finally {
            setSegmentsLoading(false)
        }
    }, [projectId, selectedRegion])

    useEffect(() => {
        loadPreview()
    }, [loadPreview])

    useEffect(() => {
        if (preview) {
            loadSegments(0)
        }
    }, [preview, selectedRegion, loadSegments])

    const handleRegionClick = (regionId: number | null) => {
        setSelectedRegion(regionId)
        setOffset(0)
    }

    const handlePageChange = (newOffset: number) => {
        loadSegments(newOffset)
    }

    const filteredSegments = useMemo(() => {
        if (!searchQuery.trim()) return segments
        const q = searchQuery.toLowerCase()
        return segments.filter(seg =>
            seg.text.toLowerCase().includes(q) ||
            (seg.corrected_text?.toLowerCase().includes(q)) ||
            (seg.semantic_chunk?.translation?.toLowerCase().includes(q)) ||
            (seg.semantic_chunk?.translation_chunk_text?.toLowerCase().includes(q))
        )
    }, [segments, searchQuery])

    const correctionRate = useMemo(() => {
        if (!preview?.stats.asr_segment_count) return 0
        return Math.round((preview.stats.corrected_count / preview.stats.asr_segment_count) * 100)
    }, [preview])

    if (loading && !preview) {
        return (
            <div className="flex items-center justify-center py-20">
                <Spinner size="lg" />
            </div>
        )
    }

    if (error && !preview) {
        return (
            <div className="max-w-2xl mx-auto">
                <div className="glass-card p-8 text-center">
                    <div className="text-5xl mb-4">⚠️</div>
                    <h2 className="text-xl font-semibold mb-2">加载失败</h2>
                    <p className="text-[--color-text-muted] mb-6">{error}</p>
                    <Link to={`/projects/${projectId}`} className="btn-primary inline-block">
                        返回项目详情
                    </Link>
                </div>
            </div>
        )
    }

    if (!preview) return null

    const { stats, global_context, vad_regions } = preview
    const timelineDurationS = Math.max(
        stats.total_duration_s,
        vad_regions.reduce((mx, r) => Math.max(mx, r.end), 0),
        0,
    )

    return (
        <div className="animate-fade-in">
            {/* Back link */}
            <div className="mb-6">
                <Link
                    to={`/projects/${projectId}`}
                    className="inline-flex items-center gap-2 text-[--color-text-muted] hover:text-[--color-text] text-sm transition-colors"
                >
                    <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 19l-7-7 7-7" />
                    </svg>
                    返回项目详情
                </Link>
            </div>

            {/* Header */}
            <div className="glass-card p-6 mb-6">
                <div className="flex items-center justify-between gap-4 mb-4">
                    <div>
                        <h1 className="text-2xl font-bold text-gradient">
                            {preview.project.name || `项目 #${preview.project.id.slice(0, 8)}`}
                        </h1>
                        <p className="text-sm text-[--color-text-muted]">数据预览</p>
                    </div>
                    <Link to={`/projects/${projectId}`} className="btn-secondary">
                        返回详情
                    </Link>
                </div>
            </div>

            {/* Stats Grid */}
            <div className="grid grid-cols-2 md:grid-cols-5 gap-4 mb-6">
                <div className="glass-card p-4 text-center">
                    <div className="text-2xl font-bold text-[--color-primary-light]">{stats.vad_region_count}</div>
                    <div className="text-xs text-[--color-text-muted]">语音区域</div>
                </div>
                <div className="glass-card p-4 text-center">
                    <div className="text-2xl font-bold text-[--color-accent-light]">{stats.asr_segment_count}</div>
                    <div className="text-xs text-[--color-text-muted]">ASR 段落</div>
                </div>
                <div className="glass-card p-4 text-center">
                    <div className="text-2xl font-bold text-[--color-success-light]">{stats.corrected_count}</div>
                    <div className="text-xs text-[--color-text-muted]">已纠错 ({correctionRate}%)</div>
                </div>
                <div className="glass-card p-4 text-center">
                    <div className="text-2xl font-bold text-[--color-warning-light]">{stats.semantic_chunk_count}</div>
                    <div className="text-xs text-[--color-text-muted]">语义块</div>
                </div>
                <div className="glass-card p-4 text-center">
                    <div className="text-2xl font-bold">{formatDuration(stats.total_duration_s)}</div>
                    <div className="text-xs text-[--color-text-muted]">总时长</div>
                </div>
            </div>

            {/* Global Context */}
            {global_context.topic && (
                <div className="glass-card p-5 mb-6">
                    <h3 className="text-sm font-semibold mb-3 flex items-center gap-2">
                        <span className="w-6 h-6 rounded-lg bg-[--color-primary]/20 flex items-center justify-center text-xs">🎯</span>
                        全局上下文
                    </h3>
                    <div className="grid md:grid-cols-3 gap-4 mb-4">
                        <div className="p-3 rounded-lg bg-[--color-bg]/50 border border-[--color-border]">
                            <div className="text-xs text-[--color-text-muted] mb-1">主题</div>
                            <div className="text-sm">{global_context.topic || '-'}</div>
                        </div>
                        <div className="p-3 rounded-lg bg-[--color-bg]/50 border border-[--color-border]">
                            <div className="text-xs text-[--color-text-muted] mb-1">领域</div>
                            <div className="text-sm">{global_context.domain || '-'}</div>
                        </div>
                        <div className="p-3 rounded-lg bg-[--color-bg]/50 border border-[--color-border]">
                            <div className="text-xs text-[--color-text-muted] mb-1">风格</div>
                            <div className="text-sm">{global_context.style || '-'}</div>
                        </div>
                    </div>
                    {global_context.glossary && Object.keys(global_context.glossary).length > 0 && (
                        <div className="p-3 rounded-lg bg-[--color-bg]/50 border border-[--color-border]">
                            <div className="text-xs text-[--color-text-muted] mb-2">术语表</div>
                            <div className="flex flex-wrap gap-2">
                                {Object.entries(global_context.glossary).map(([src, tgt]) => (
                                    <span key={src} className="px-2 py-1 rounded bg-[--color-primary]/10 text-xs">
                                        {src} → {tgt}
                                    </span>
                                ))}
                            </div>
                        </div>
                    )}
                </div>
            )}

            {/* Timeline */}
            {vad_regions.length > 0 && timelineDurationS > 0 && (
                <div className="glass-card p-5 mb-6">
                    <h3 className="text-sm font-semibold mb-3 flex items-center gap-2">
                        <span className="w-6 h-6 rounded-lg bg-[--color-accent]/20 flex items-center justify-center text-xs">📊</span>
                        时间轴视图
                        <span className="ml-auto text-xs text-[--color-text-dim] font-normal">
                            点击区域筛选段落
                        </span>
                    </h3>
                    <div className="relative h-16 rounded-lg bg-[--color-bg]/50 border border-[--color-border] overflow-hidden">
                        {/* Time markers */}
                        <div className="absolute inset-x-0 top-0 h-6 flex items-center px-2 border-b border-[--color-border]/50">
                            {Array.from({ length: Math.ceil(timelineDurationS / 60) + 1 }).map((_, i) => (
                                <div
                                    key={i}
                                    className="absolute text-xs text-[--color-text-dim]"
                                    style={{ left: `${(i * 60 / timelineDurationS) * 100}%` }}
                                >
                                    {formatDuration(i * 60)}
                                </div>
                            ))}
                        </div>
                        {/* Region blocks */}
                        <div className="absolute inset-x-0 bottom-0 h-10 px-2">
                            <button
                                onClick={() => handleRegionClick(null)}
                                className={`absolute inset-0 transition-opacity ${selectedRegion === null ? 'opacity-100' : 'opacity-30 hover:opacity-60'}`}
                                title="显示所有区域"
                            />
                            {vad_regions.map((region) => {
                                const left = (region.start / timelineDurationS) * 100
                                const width = ((region.end - region.start) / timelineDurationS) * 100
                                const isSelected = selectedRegion === region.region_id
                                return (
                                    <button
                                        key={region.region_id}
                                        onClick={() => handleRegionClick(region.region_id)}
                                        className={`absolute h-8 rounded transition-all ${isSelected
                                            ? 'bg-[--color-primary] ring-2 ring-[--color-primary-light]'
                                            : 'bg-[--color-accent]/60 hover:bg-[--color-accent]'
                                            }`}
                                        style={{ left: `${left}%`, width: `${Math.max(width, 0.5)}%`, top: '4px' }}
                                        title={`Region ${region.region_id}: ${formatTime(region.start)} - ${formatTime(region.end)} (${region.segment_count} 段)`}
                                    />
                                )
                            })}
                        </div>
                    </div>
                    {selectedRegion !== null && (
                        <div className="mt-2 flex items-center gap-2 text-xs text-[--color-text-muted]">
                            <span>已选中: Region {selectedRegion}</span>
                            <button
                                onClick={() => handleRegionClick(null)}
                                className="text-[--color-primary-light] hover:underline"
                            >
                                清除筛选
                            </button>
                        </div>
                    )}
                </div>
            )}

            {/* Search */}
            <div className="glass-card p-4 mb-6">
                <div className="flex items-center gap-3">
                    <svg className="w-5 h-5 text-[--color-text-muted]" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" />
                    </svg>
                    <input
                        type="text"
                        value={searchQuery}
                        onChange={(e) => setSearchQuery(e.target.value)}
                        placeholder="搜索文本内容..."
                        className="flex-1 bg-transparent text-sm outline-none placeholder-[--color-text-dim]"
                    />
                    {searchQuery && (
                        <button
                            onClick={() => setSearchQuery('')}
                            className="text-xs text-[--color-text-muted] hover:text-[--color-text]"
                        >
                            清除
                        </button>
                    )}
                </div>
            </div>

            {/* Segments List */}
            <div className="glass-card p-5">
                <div className="flex items-center justify-between gap-3 mb-4">
                    <h3 className="text-sm font-semibold flex items-center gap-2">
                        <span className="w-6 h-6 rounded-lg bg-[--color-success]/20 flex items-center justify-center text-xs">🎤</span>
                        ASR 段落
                        <span className="text-[--color-text-dim] font-normal">
                            ({filteredSegments.length} / {segmentsTotal})
                        </span>
                    </h3>
                    {segmentsLoading && <Spinner size="sm" />}
                </div>

                {segmentsError && (
                    <div className="mb-4 p-3 rounded-lg bg-[--color-error]/10 border border-[--color-error]/30 text-sm text-[--color-error-light]">
                        {segmentsError}
                    </div>
                )}

                {filteredSegments.length === 0 ? (
                    <div className="text-center py-8 text-[--color-text-muted]">
                        {searchQuery ? '没有匹配的结果' : '暂无数据'}
                    </div>
                ) : (
                    <div className="space-y-3">
                        {filteredSegments.map((seg) => (
                            <div
                                key={seg.id}
                                className="p-4 rounded-xl bg-[--color-bg]/50 border border-[--color-border] hover:border-[--color-border-light] transition-colors"
                            >
                                {/* Header */}
                                <div className="flex items-center gap-3 mb-3">
                                    <span className="px-2 py-1 rounded bg-[--color-primary]/10 text-xs font-mono text-[--color-primary-light]">
                                        #{seg.id}
                                    </span>
                                    <span className="text-xs text-[--color-text-muted] font-mono">
                                        {formatTime(seg.start)} → {formatTime(seg.end)}
                                    </span>
                                    {seg.corrected_text && seg.corrected_text !== seg.text && (
                                        <span className="px-2 py-0.5 rounded bg-[--color-success]/10 text-xs text-[--color-success-light]">
                                            已纠错
                                        </span>
                                    )}
                                </div>

                                {/* Text content */}
                                <div className="space-y-2">
                                    <div>
                                        <div className="text-xs text-[--color-text-muted] mb-1">原文</div>
                                        <div className="text-sm">{seg.text || <span className="text-[--color-text-dim] italic">（空）</span>}</div>
                                    </div>
                                    {seg.corrected_text && seg.corrected_text !== seg.text && (
                                        <div>
                                            <div className="text-xs text-[--color-success-light] mb-1">纠错后</div>
                                            <div className="text-sm text-[--color-success-light]">{seg.corrected_text}</div>
                                        </div>
                                    )}
                                </div>

                                {/* Semantic chunk */}
                                {seg.semantic_chunk && (
                                    <details className="mt-3 pt-3 border-t border-[--color-border]">
                                        <summary className="cursor-pointer select-none text-xs text-[--color-text-muted] hover:text-[--color-text]">
                                            语义块 #{seg.semantic_chunk.id} • 翻译
                                        </summary>
                                        <div className="mt-2 space-y-2">
                                            <div className="p-3 rounded-lg bg-[--color-primary]/5 border border-[--color-primary]/20">
                                                <div className="text-xs text-[--color-primary-light] mb-1">完整翻译</div>
                                                <div className="text-sm">{seg.semantic_chunk.translation || '-'}</div>
                                            </div>
                                            {seg.semantic_chunk.translation_chunk_text && (
                                                <div className="p-3 rounded-lg bg-[--color-accent]/5 border border-[--color-accent]/20">
                                                    <div className="text-xs text-[--color-accent-light] mb-1">对应此段落的翻译片段</div>
                                                    <div className="text-sm">{seg.semantic_chunk.translation_chunk_text}</div>
                                                </div>
                                            )}
                                        </div>
                                    </details>
                                )}
                            </div>
                        ))}
                    </div>
                )}

                {/* Pagination */}
                {segmentsTotal > limit && (
                    <div className="mt-4 flex items-center justify-center gap-3">
                        <button
                            onClick={() => handlePageChange(Math.max(0, offset - limit))}
                            disabled={offset === 0}
                            className="btn-secondary text-sm disabled:opacity-50"
                        >
                            上一页
                        </button>
                        <span className="text-xs text-[--color-text-muted]">
                            {Math.floor(offset / limit) + 1} / {Math.ceil(segmentsTotal / limit)}
                        </span>
                        <button
                            onClick={() => handlePageChange(offset + limit)}
                            disabled={offset + limit >= segmentsTotal}
                            className="btn-secondary text-sm disabled:opacity-50"
                        >
                            下一页
                        </button>
                    </div>
                )}
            </div>
        </div>
    )
}
