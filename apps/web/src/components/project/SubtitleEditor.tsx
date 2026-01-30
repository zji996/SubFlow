import { useEffect, useRef, useState } from 'react'
import { useExports } from '../../hooks/useExports'
import { useSubtitles } from '../../hooks/useSubtitles'
import type { ExportFormat, SubtitleEditComputedEntry } from '../../types/entities'
import { Spinner } from '../common/Spinner'
import { formatTimestamp } from '../../utils'

interface SubtitleEditorProps {
    projectId: string
    onClose: () => void
}

interface EditedEntry {
    segment_id: number
    secondary?: string
    primary?: string
}

// Export dropdown component with click-to-toggle for mobile compatibility
interface ExportDropdownProps {
    onExport: (format: ExportFormat) => Promise<void>
    isSaving: boolean
}

function ExportDropdown({ onExport, isSaving }: ExportDropdownProps) {
    const [isOpen, setIsOpen] = useState(false)
    const dropdownRef = useRef<HTMLDivElement>(null)

    // Close dropdown when clicking outside
    useEffect(() => {
        const handleClickOutside = (event: MouseEvent) => {
            if (dropdownRef.current && !dropdownRef.current.contains(event.target as Node)) {
                setIsOpen(false)
            }
        }
        if (isOpen) {
            document.addEventListener('mousedown', handleClickOutside)
            return () => document.removeEventListener('mousedown', handleClickOutside)
        }
    }, [isOpen])

    // Close on Escape key
    useEffect(() => {
        const handleEscape = (e: KeyboardEvent) => {
            if (e.key === 'Escape') setIsOpen(false)
        }
        if (isOpen) {
            document.addEventListener('keydown', handleEscape)
            return () => document.removeEventListener('keydown', handleEscape)
        }
    }, [isOpen])

    const handleExport = async (format: ExportFormat) => {
        setIsOpen(false)
        await onExport(format)
    }

    const exportOptions: { format: ExportFormat; icon: string; label: string }[] = [
        { format: 'srt', icon: '📄', label: 'SRT' },
        { format: 'vtt', icon: '🌐', label: 'WebVTT' },
        { format: 'ass', icon: '🎨', label: 'ASS' },
        { format: 'json', icon: '⚙️', label: 'JSON' },
    ]

    return (
        <div ref={dropdownRef} className="relative">
            <button
                className="btn-primary"
                disabled={isSaving}
                onClick={() => setIsOpen(!isOpen)}
                aria-haspopup="menu"
                aria-expanded={isOpen}
            >
                {isSaving ? (
                    <>
                        <Spinner size="sm" />
                        保存中...
                    </>
                ) : (
                    <>
                        <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24" aria-hidden="true">
                            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-4l-4 4m0 0l-4-4m4 4V4" />
                        </svg>
                        导出字幕
                        <svg className={`w-3 h-3 ml-1 transition-transform ${isOpen ? 'rotate-180' : ''}`} fill="none" stroke="currentColor" viewBox="0 0 24 24" aria-hidden="true">
                            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
                        </svg>
                    </>
                )}
            </button>
            {isOpen && (
                <div
                    className="absolute bottom-full right-0 mb-2 animate-scale-in"
                    role="menu"
                    aria-orientation="vertical"
                >
                    <div className="glass-card p-2 shadow-lg min-w-32">
                        {exportOptions.map(({ format, icon, label }) => (
                            <button
                                key={format}
                                onClick={() => handleExport(format)}
                                className="w-full text-left px-3 py-2 rounded hover:bg-[--color-bg-hover] text-sm flex items-center gap-2"
                                role="menuitem"
                            >
                                <span aria-hidden="true">{icon}</span>
                                {label}
                            </button>
                        ))}
                    </div>
                </div>
            )}
        </div>
    )
}

export function SubtitleEditor({ projectId, onClose }: SubtitleEditorProps) {
    const { data, loading, error, refetch } = useSubtitles(projectId)
    const { createExport, saving: isSaving, error: saveError } = useExports(projectId, { enabled: false })
    const [editedEntries, setEditedEntries] = useState<Map<number, EditedEntry>>(new Map())

    const getPrimary = (entry: SubtitleEditComputedEntry): string => {
        return entry.primary
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
            const exp = await createExport({
                format,
                content: 'both',
                primary_position: 'top',
                edited_entries: entriesArray.length > 0 ? entriesArray : undefined,
            })

            // Trigger download
            const link = document.createElement('a')
            link.href = exp.download_url
            document.body.appendChild(link)
            link.click()
            document.body.removeChild(link)
        } catch {
            // Error state handled by hook
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
                        <button onClick={refetch} className="btn-primary">
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
                    <div />
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
                        <ExportDropdown
                            onExport={handleSaveExport}
                            isSaving={isSaving}
                        />
                    </div>
                </div>
            </div>
        </div>
    )
}
