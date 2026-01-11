import { useCallback, useEffect, useState } from 'react'
import {
    getSubtitleEditData,
    type SubtitleEditComputedEntry,
    type SubtitleEditDataResponse,
    type TranslationStyle,
} from '../../api/subtitles'
import { createExport } from '../../api/exports'
import type { ExportFormat, ContentMode, PrimaryPosition } from '../../api/subtitles'
import { Spinner } from '../common/Spinner'

interface SubtitleEditorProps {
    projectId: string
    onClose: () => void
}

interface EditedEntry {
    segment_id: number
    secondary?: string
    primary?: string
}

function formatTimestamp(seconds: number): string {
    const h = Math.floor(seconds / 3600)
    const m = Math.floor((seconds % 3600) / 60)
    const s = Math.floor(seconds % 60)
    const ms = Math.floor((seconds % 1) * 1000)
    return `${String(h).padStart(2, '0')}:${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')},${String(ms).padStart(3, '0')}`
}

export function SubtitleEditor({ projectId, onClose }: SubtitleEditorProps) {
    const [loading, setLoading] = useState(true)
    const [error, setError] = useState<string | null>(null)
    const [data, setData] = useState<SubtitleEditDataResponse | null>(null)
    const [translationStyle, setTranslationStyle] = useState<TranslationStyle>('per_chunk')
    const [editedEntries, setEditedEntries] = useState<Map<number, EditedEntry>>(new Map())
    const [isSaving, setIsSaving] = useState(false)
    const [saveError, setSaveError] = useState<string | null>(null)

    const fetchData = useCallback(async () => {
        setLoading(true)
        setError(null)
        try {
            const result = await getSubtitleEditData(projectId)
            setData(result)
        } catch (err) {
            setError(err instanceof Error ? err.message : 'Failed to load subtitle data')
        } finally {
            setLoading(false)
        }
    }, [projectId])

    useEffect(() => {
        void fetchData()
    }, [fetchData])

    const getPrimary = (entry: SubtitleEditComputedEntry): string => {
        switch (translationStyle) {
            case 'per_chunk':
                return entry.primary_per_chunk
            case 'full':
                return entry.primary_full
            case 'per_segment':
                return entry.primary_per_segment
            default:
                return entry.primary_per_chunk
        }
    }

    const handleEdit = (segmentId: number, field: 'secondary' | 'primary', value: string) => {
        setEditedEntries((prev) => {
            const newMap = new Map(prev)
            const existing = newMap.get(segmentId) || { segment_id: segmentId }
            newMap.set(segmentId, { ...existing, [field]: value })
            return newMap
        })
    }

    const getDisplayValue = (entry: SubtitleEditComputedEntry, field: 'secondary' | 'primary'): string => {
        const edited = editedEntries.get(entry.segment_id)
        if (field === 'secondary') {
            return edited?.secondary ?? entry.secondary
        }
        return edited?.primary ?? getPrimary(entry)
    }

    const isEdited = (segmentId: number): boolean => {
        return editedEntries.has(segmentId)
    }

    const handleSaveExport = async (format: ExportFormat) => {
        setIsSaving(true)
        setSaveError(null)

        const entriesArray: Array<{
            segment_id: number
            secondary?: string
            primary?: string
        }> = []

        // Include all entries, with or without edits
        for (const entry of data?.computed_entries || []) {
            const edited = editedEntries.get(entry.segment_id)
            if (edited) {
                entriesArray.push({
                    segment_id: entry.segment_id,
                    secondary: edited.secondary,
                    primary: edited.primary,
                })
            }
        }

        try {
            const exp = await createExport(projectId, {
                format,
                content: 'both' as ContentMode,
                primary_position: 'top' as PrimaryPosition,
                translation_style: translationStyle,
                edited_entries: entriesArray.length > 0 ? entriesArray : undefined,
            } as Parameters<typeof createExport>[1])

            // Trigger download
            const link = document.createElement('a')
            link.href = exp.download_url
            document.body.appendChild(link)
            link.click()
            document.body.removeChild(link)
        } catch (err) {
            setSaveError(err instanceof Error ? err.message : 'Failed to save export')
        } finally {
            setIsSaving(false)
        }
    }

    const handleResetEdits = () => {
        setEditedEntries(new Map())
    }

    if (loading) {
        return (
            <div className="fixed inset-0 z-50 bg-black/50 flex items-center justify-center">
                <div className="glass-card p-8">
                    <Spinner size="lg" />
                    <p className="mt-4 text-[--color-text-muted]">加载字幕数据...</p>
                </div>
            </div>
        )
    }

    if (error) {
        return (
            <div className="fixed inset-0 z-50 bg-black/50 flex items-center justify-center">
                <div className="glass-card p-8 max-w-md">
                    <div className="text-[--color-error-light] mb-4">{error}</div>
                    <div className="flex gap-3">
                        <button onClick={fetchData} className="btn-primary">
                            重试
                        </button>
                        <button onClick={onClose} className="btn-secondary">
                            关闭
                        </button>
                    </div>
                </div>
            </div>
        )
    }

    const entries = data?.computed_entries || []

    return (
        <div className="fixed inset-0 z-50 bg-black/50 flex items-center justify-center p-4">
            <div className="glass-card w-full max-w-6xl max-h-[90vh] flex flex-col animate-fade-in">
                {/* Header */}
                <div className="flex items-center justify-between gap-4 p-6 border-b border-[--color-border]">
                    <div>
                        <h2 className="text-xl font-bold text-gradient">字幕编辑器</h2>
                        <p className="text-sm text-[--color-text-muted]">
                            点击单元格编辑内容，编辑后可导出为字幕文件
                        </p>
                    </div>
                    <button onClick={onClose} className="btn-icon">
                        <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
                        </svg>
                    </button>
                </div>

                {/* Toolbar */}
                <div className="flex items-center justify-between gap-4 px-6 py-3 border-b border-[--color-border] bg-[--color-bg-elevated]">
                    <div className="flex items-center gap-4">
                        <label className="text-sm text-[--color-text-muted]">翻译样式:</label>
                        <select
                            value={translationStyle}
                            onChange={(e) => setTranslationStyle(e.target.value as TranslationStyle)}
                            className="input py-1 px-3 text-sm"
                        >
                            <option value="per_chunk">按翻译分段</option>
                            <option value="full">完整意译</option>
                            <option value="per_segment">均分翻译</option>
                        </select>
                    </div>
                    <div className="flex items-center gap-2">
                        {editedEntries.size > 0 && (
                            <span className="text-xs text-[--color-text-muted]">
                                已编辑 {editedEntries.size} 项
                            </span>
                        )}
                        <button
                            onClick={handleResetEdits}
                            disabled={editedEntries.size === 0}
                            className="btn-secondary text-sm py-1"
                        >
                            重置编辑
                        </button>
                    </div>
                </div>

                {/* Table */}
                <div className="flex-1 overflow-auto">
                    <table className="w-full text-sm">
                        <thead className="sticky top-0 bg-[--color-bg-card] border-b border-[--color-border]">
                            <tr>
                                <th className="text-left px-4 py-3 font-medium text-[--color-text-muted] w-24">
                                    #
                                </th>
                                <th className="text-left px-4 py-3 font-medium text-[--color-text-muted] w-40">
                                    时间
                                </th>
                                <th className="text-left px-4 py-3 font-medium text-[--color-text-muted]">
                                    翻译 (主字幕)
                                </th>
                                <th className="text-left px-4 py-3 font-medium text-[--color-text-muted]">
                                    原文 (副字幕)
                                </th>
                            </tr>
                        </thead>
                        <tbody>
                            {entries.map((entry, idx) => (
                                <tr
                                    key={entry.segment_id}
                                    className={`border-b border-[--color-border] hover:bg-[--color-bg-hover] transition-colors ${isEdited(entry.segment_id) ? 'bg-[--color-primary]/5' : ''
                                        }`}
                                >
                                    <td className="px-4 py-2 text-[--color-text-dim] font-mono">
                                        {idx + 1}
                                    </td>
                                    <td className="px-4 py-2 font-mono text-xs text-[--color-text-muted]">
                                        {formatTimestamp(entry.start)}
                                        <br />
                                        <span className="text-[--color-text-dim]">→ {formatTimestamp(entry.end)}</span>
                                    </td>
                                    <td className="px-4 py-2">
                                        <textarea
                                            value={getDisplayValue(entry, 'primary')}
                                            onChange={(e) => handleEdit(entry.segment_id, 'primary', e.target.value)}
                                            className="w-full bg-transparent border-0 focus:outline-none focus:ring-1 focus:ring-[--color-primary] rounded px-2 py-1 resize-none"
                                            rows={2}
                                            placeholder="(无翻译)"
                                        />
                                    </td>
                                    <td className="px-4 py-2">
                                        <textarea
                                            value={getDisplayValue(entry, 'secondary')}
                                            onChange={(e) => handleEdit(entry.segment_id, 'secondary', e.target.value)}
                                            className="w-full bg-transparent border-0 focus:outline-none focus:ring-1 focus:ring-[--color-primary] rounded px-2 py-1 resize-none"
                                            rows={2}
                                            placeholder="(无原文)"
                                        />
                                    </td>
                                </tr>
                            ))}
                        </tbody>
                    </table>
                </div>

                {/* Footer */}
                <div className="flex items-center justify-between gap-4 p-6 border-t border-[--color-border]">
                    <div className="text-sm text-[--color-text-muted]">
                        共 {entries.length} 条字幕
                    </div>
                    {saveError && (
                        <div className="text-sm text-[--color-error-light]">{saveError}</div>
                    )}
                    <div className="flex items-center gap-3">
                        <button onClick={onClose} className="btn-secondary">
                            取消
                        </button>
                        <div className="relative group">
                            <button className="btn-primary" disabled={isSaving}>
                                {isSaving ? (
                                    <>
                                        <Spinner size="sm" />
                                        保存中...
                                    </>
                                ) : (
                                    <>
                                        <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-4l-4 4m0 0l-4-4m4 4V4" />
                                        </svg>
                                        导出字幕
                                    </>
                                )}
                            </button>
                            <div className="absolute bottom-full right-0 mb-2 hidden group-hover:block">
                                <div className="glass-card p-2 shadow-lg min-w-32">
                                    <button
                                        onClick={() => handleSaveExport('srt')}
                                        className="w-full text-left px-3 py-2 rounded hover:bg-[--color-bg-hover] text-sm"
                                    >
                                        📄 SRT
                                    </button>
                                    <button
                                        onClick={() => handleSaveExport('vtt')}
                                        className="w-full text-left px-3 py-2 rounded hover:bg-[--color-bg-hover] text-sm"
                                    >
                                        🌐 WebVTT
                                    </button>
                                    <button
                                        onClick={() => handleSaveExport('ass')}
                                        className="w-full text-left px-3 py-2 rounded hover:bg-[--color-bg-hover] text-sm"
                                    >
                                        🎨 ASS
                                    </button>
                                    <button
                                        onClick={() => handleSaveExport('json')}
                                        className="w-full text-left px-3 py-2 rounded hover:bg-[--color-bg-hover] text-sm"
                                    >
                                        ⚙️ JSON
                                    </button>
                                </div>
                            </div>
                        </div>
                    </div>
                </div>
            </div>
        </div>
    )
}
