import { useCallback, useEffect, useState } from 'react'

import { ApiError } from '../../api/client'
import {
    type ContentMode,
    type ExportFormat,
    type PrimaryPosition,
} from '../../api/subtitles'
import { createExport, listExports, type SubtitleExport } from '../../api/exports'

interface SubtitleExportPanelProps {
    projectId: string
    hasLLMCompleted: boolean
}

const formatOptions: { value: ExportFormat; label: string; description: string; icon: string }[] = [
    { value: 'srt', label: 'SRT', description: '最通用，兼容所有播放器', icon: '📄' },
    { value: 'vtt', label: 'WebVTT', description: '网页播放器推荐', icon: '🌐' },
    { value: 'ass', label: 'ASS', description: '支持高级样式（字体、颜色）', icon: '🎨' },
    { value: 'json', label: 'JSON', description: '程序化处理', icon: '⚙️' },
]

const contentOptions: { value: ContentMode; label: string; description: string }[] = [
    { value: 'both', label: '双语字幕', description: '同时显示翻译和原文' },
    { value: 'primary_only', label: '仅翻译', description: '只显示翻译文本' },
    { value: 'secondary_only', label: '仅原文', description: '只显示原始语言文本' },
]

const positionOptions: { value: PrimaryPosition; label: string; description: string }[] = [
    { value: 'top', label: '翻译在上', description: '翻译显示在第一行' },
    { value: 'bottom', label: '翻译在下', description: '原文显示在第一行' },
]

function formatExportsError(err: unknown): string {
    if (err instanceof ApiError) {
        const detailText =
            err.detail == null
                ? null
                : typeof err.detail === 'string'
                    ? err.detail
                    : JSON.stringify(err.detail, null, 2)

        const base = `${err.message} (HTTP ${err.status})`
        if (!detailText || detailText === err.message) return base
        return `${base}\n${detailText}`
    }
    if (err instanceof Error) return err.message
    return String(err)
}

export function SubtitleExportPanel({ projectId, hasLLMCompleted }: SubtitleExportPanelProps) {
    const [format, setFormat] = useState<ExportFormat>('srt')
    const [content, setContent] = useState<ContentMode>('both')
    const [position, setPosition] = useState<PrimaryPosition>('top')

    const [exports, setExports] = useState<SubtitleExport[]>([])
    const [exportsLoading, setExportsLoading] = useState(false)
    const [exportsError, setExportsError] = useState<string | null>(null)
    const [isSaving, setIsSaving] = useState(false)



    const refreshExports = useCallback(async () => {
        setExportsLoading(true)
        setExportsError(null)
        try {
            if (import.meta.env.DEV) {
                // eslint-disable-next-line no-console
                console.log('[SubtitleExportPanel] refreshExports', { projectId })
            }
            const items = await listExports(projectId)
            if (import.meta.env.DEV) {
                // eslint-disable-next-line no-console
                console.log('[SubtitleExportPanel] refreshExports OK', { projectId, count: items.length })
            }
            setExports(items)
        } catch (err) {
            if (import.meta.env.DEV) {
                // eslint-disable-next-line no-console
                console.log('[SubtitleExportPanel] refreshExports ERROR', { projectId, err })
            }
            setExportsError(formatExportsError(err))
        } finally {
            setExportsLoading(false)
        }
    }, [projectId])

    useEffect(() => {
        if (!hasLLMCompleted) return
        void refreshExports()
    }, [hasLLMCompleted, refreshExports])



    const handleSaveExport = async () => {
        setIsSaving(true)
        setExportsError(null)
        try {
            if (import.meta.env.DEV) {
                // eslint-disable-next-line no-console
                console.log('[SubtitleExportPanel] handleSaveExport', {
                    projectId,
                    format,
                    content,
                    primary_position: position,
                })
            }
            const exp = await createExport(projectId, {
                format,
                content,
                primary_position: position,
            })
            if (import.meta.env.DEV) {
                // eslint-disable-next-line no-console
                console.log('[SubtitleExportPanel] handleSaveExport OK', { projectId, exportId: exp.id })
            }
            setExports((prev) => [exp, ...prev.filter((x) => x.id !== exp.id)])

            const link = document.createElement('a')
            link.href = exp.download_url
            document.body.appendChild(link)
            link.click()
            document.body.removeChild(link)
        } catch (err) {
            if (import.meta.env.DEV) {
                // eslint-disable-next-line no-console
                console.log('[SubtitleExportPanel] handleSaveExport ERROR', { projectId, err })
            }
            setExportsError(formatExportsError(err))
        } finally {
            setIsSaving(false)
        }
    }

    if (!hasLLMCompleted) {
        return (
            <div className="glass-card p-6 mt-8">
                <div className="flex items-center gap-3 mb-4">
                    <div className="w-10 h-10 rounded-xl bg-[--color-bg-hover] flex items-center justify-center">
                        <svg className="w-5 h-5 text-[--color-text-muted]" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 10v6m0 0l-3-3m3 3l3-3m2 8H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
                        </svg>
                    </div>
                    <div>
                        <h3 className="text-lg font-semibold">字幕导出</h3>
                        <p className="text-sm text-[--color-text-muted]">完成翻译阶段后可导出字幕</p>
                    </div>
                </div>
                <p className="text-sm text-[--color-text-dim]">
                    请先完成 LLM 翻译阶段（Stage 5）后才能导出字幕。
                </p>
            </div>
        )
    }

    return (
        <div className="glass-card p-6 mt-8 animate-fade-in">
            {/* Header */}
            <div className="flex items-center gap-3 mb-6">
                <div className="w-10 h-10 rounded-xl bg-gradient-to-br from-[--color-primary]/20 to-[--color-accent]/20 flex items-center justify-center">
                    <svg className="w-5 h-5 text-[--color-primary-light]" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 10v6m0 0l-3-3m3 3l3-3m2 8H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
                    </svg>
                </div>
                <div>
                    <h3 className="text-lg font-semibold">字幕导出</h3>
                    <p className="text-sm text-[--color-text-muted]">选择格式和内容，下载您的字幕文件</p>
                </div>
            </div>

            {/* Format Selection */}
            <div className="mb-6">
                <label className="block text-sm font-medium mb-3">📑 字幕格式</label>
                <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
                    {formatOptions.map((opt) => (
                        <button
                            key={opt.value}
                            onClick={() => setFormat(opt.value)}
                            className={`relative p-3 rounded-xl border text-left transition-all ${format === opt.value
                                ? 'border-[--color-primary] border-2 bg-[--color-primary]/10 shadow-[0_0_0_1px_var(--color-primary)]'
                                : 'border-[--color-border] hover:border-[--color-border-light] hover:bg-[--color-bg-hover]'
                                }`}
                        >
                            {format === opt.value && (
                                <div className="absolute top-2 right-2 w-5 h-5 rounded-full bg-[--color-primary] flex items-center justify-center">
                                    <svg className="w-3 h-3 text-white" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={3} d="M5 13l4 4L19 7" />
                                    </svg>
                                </div>
                            )}
                            <div className="flex items-center gap-2 mb-1">
                                <span>{opt.icon}</span>
                                <span className="font-medium">{opt.label}</span>
                            </div>
                            <p className="text-xs text-[--color-text-muted]">{opt.description}</p>
                        </button>
                    ))}
                </div>
            </div>

            {/* Content Mode */}
            <div className="mb-6">
                <label className="block text-sm font-medium mb-3">🔤 字幕内容</label>
                <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
                    {contentOptions.map((opt) => (
                        <button
                            key={opt.value}
                            onClick={() => setContent(opt.value)}
                            className={`relative p-3 rounded-xl border text-left transition-all ${content === opt.value
                                ? 'border-[--color-primary] border-2 bg-[--color-primary]/10 shadow-[0_0_0_1px_var(--color-primary)]'
                                : 'border-[--color-border] hover:border-[--color-border-light] hover:bg-[--color-bg-hover]'
                                }`}
                        >
                            {content === opt.value && (
                                <div className="absolute top-2 right-2 w-5 h-5 rounded-full bg-[--color-primary] flex items-center justify-center">
                                    <svg className="w-3 h-3 text-white" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={3} d="M5 13l4 4L19 7" />
                                    </svg>
                                </div>
                            )}
                            <div className="font-medium mb-1">{opt.label}</div>
                            <p className="text-xs text-[--color-text-muted]">{opt.description}</p>
                        </button>
                    ))}
                </div>
            </div>

            {/* Position (only for bilingual) */}
            {content === 'both' && (
                <div className="mb-6 animate-fade-in">
                    <label className="block text-sm font-medium mb-3">↕️ 显示顺序</label>
                    <div className="grid grid-cols-2 gap-3">
                        {positionOptions.map((opt) => (
                            <button
                                key={opt.value}
                                onClick={() => setPosition(opt.value)}
                                className={`relative p-3 rounded-xl border text-left transition-all ${position === opt.value
                                    ? 'border-[--color-primary] border-2 bg-[--color-primary]/10 shadow-[0_0_0_1px_var(--color-primary)]'
                                    : 'border-[--color-border] hover:border-[--color-border-light] hover:bg-[--color-bg-hover]'
                                    }`}
                            >
                                {position === opt.value && (
                                    <div className="absolute top-2 right-2 w-5 h-5 rounded-full bg-[--color-primary] flex items-center justify-center">
                                        <svg className="w-3 h-3 text-white" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={3} d="M5 13l4 4L19 7" />
                                        </svg>
                                    </div>
                                )}
                                <div className="font-medium mb-1">{opt.label}</div>
                                <p className="text-xs text-[--color-text-muted]">{opt.description}</p>
                            </button>
                        ))}
                    </div>
                </div>
            )}

            {/* Preview Summary */}
            <div className="p-4 rounded-xl bg-[--color-bg]/50 border border-[--color-border] mb-6">
                <div className="text-sm text-[--color-text-muted] mb-2">导出配置预览</div>
                <div className="flex flex-wrap gap-2">
                    <span className="px-2 py-1 rounded-lg bg-[--color-primary]/10 text-[--color-primary-light] text-xs font-medium">
                        {formatOptions.find(f => f.value === format)?.label}
                    </span>
                    <span className="px-2 py-1 rounded-lg bg-[--color-bg-elevated] text-[--color-text-secondary] text-xs">
                        {contentOptions.find(c => c.value === content)?.label}
                    </span>
                    {content === 'both' && (
                        <span className="px-2 py-1 rounded-lg bg-[--color-bg-elevated] text-[--color-text-secondary] text-xs">
                            {positionOptions.find(p => p.value === position)?.label}
                        </span>
                    )}
                </div>
            </div>

            {/* Export Button */}
            <button
                onClick={handleSaveExport}
                disabled={isSaving}
                className="btn-primary w-full py-4 text-base"
            >
                {isSaving ? (
                    <>
                        <svg className="w-5 h-5 animate-spin" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                            <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"></circle>
                            <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
                        </svg>
                        <span>导出中...</span>
                    </>
                ) : (
                    <>
                        <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-4l-4 4m0 0l-4-4m4 4V4" />
                        </svg>
                        <span>导出字幕</span>
                    </>
                )}
            </button>

            {/* History Section */}
            <div className="mt-6 border-t border-[--color-border] pt-6">
                <div className="flex items-center justify-between gap-3 mb-4">
                    <div>
                        <div className="text-sm font-medium">历史导出</div>
                        <div className="text-xs text-[--color-text-muted]">点击上方导出后会自动保存版本</div>
                    </div>
                    <button
                        onClick={refreshExports}
                        disabled={exportsLoading}
                        className="btn-secondary"
                    >
                        刷新
                    </button>
                </div>

                {exportsError && (
                    <div className="mb-4 p-3 rounded-lg bg-[--color-error]/10 border border-[--color-error]/30 text-xs text-[--color-error-light] whitespace-pre-wrap break-words">
                        {exportsError}
                    </div>
                )}

                {exportsLoading ? (
                    <div className="text-xs text-[--color-text-muted]">加载中…</div>
                ) : exports.length === 0 ? (
                    <div className="text-xs text-[--color-text-dim]">暂无导出版本</div>
                ) : (
                    <div className="space-y-2">
                        {exports.map((exp) => {
                            const dt = new Date(exp.created_at)
                            const ts = Number.isNaN(dt.getTime()) ? exp.created_at : dt.toLocaleString()
                            const formatIcon = {
                                srt: '📄',
                                vtt: '🌐',
                                ass: '🎨',
                                json: '⚙️',
                            }[exp.format] || '📄'
                            return (
                                <div
                                    key={exp.id}
                                    className="flex items-center justify-between gap-3 p-3 rounded-xl bg-[--color-bg]/50 border border-[--color-border] hover:border-[--color-border-light] transition-colors"
                                >
                                    <div className="flex items-center gap-3 min-w-0">
                                        <div className="w-9 h-9 rounded-lg bg-[--color-bg-elevated] flex items-center justify-center text-lg shrink-0">
                                            {formatIcon}
                                        </div>
                                        <div className="min-w-0">
                                            <div className="flex items-center gap-2 text-sm font-medium">
                                                <span>{exp.format.toUpperCase()}</span>
                                                <span className="px-1.5 py-0.5 rounded bg-[--color-bg-elevated] text-[0.625rem] text-[--color-text-muted]">
                                                    {exp.source === 'edited' ? '已编辑' : '自动'}
                                                </span>
                                            </div>
                                            <div className="text-xs text-[--color-text-dim] truncate">{ts}</div>
                                        </div>
                                    </div>
                                    <button
                                        onClick={() => {
                                            const link = document.createElement('a')
                                            link.href = exp.download_url
                                            document.body.appendChild(link)
                                            link.click()
                                            document.body.removeChild(link)
                                        }}
                                        className="btn-secondary shrink-0 py-2 px-3 text-xs"
                                    >
                                        <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-4l-4 4m0 0l-4-4m4 4V4" />
                                        </svg>
                                        下载
                                    </button>
                                </div>
                            )
                        })}
                    </div>
                )}
            </div>
        </div>
    )
}
