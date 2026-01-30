import { useRef, useState, type ChangeEvent, type DragEvent } from 'react'

export interface MediaUploaderProps {
    name: string
    mediaUrl: string
    selectedFile: File | null
    disabled?: boolean
    onMediaUrlChange: (value: string) => void
    onSelectedFileChange: (file: File | null) => void
    onAutoName: (value: string) => void
    onError: (message: string | null) => void
}

function isValidMediaFile(file: File): boolean {
    const validTypes = [
        'video/mp4',
        'video/webm',
        'video/ogg',
        'video/quicktime',
        'video/x-matroska',
        'video/x-msvideo',
        'video/x-flv',
        'audio/mpeg',
        'audio/wav',
        'audio/ogg',
        'audio/flac',
        'audio/aac',
        'audio/mp4',
        'audio/x-m4a',
    ]
    const ext = file.name.split('.').pop()?.toLowerCase()
    const validExts = ['mp4', 'mkv', 'avi', 'mov', 'webm', 'flv', 'mp3', 'wav', 'flac', 'aac', 'm4a', 'ogg']
    return validTypes.includes(file.type) || (ext !== undefined && validExts.includes(ext))
}

function getNameFromFile(filename: string): string {
    return filename.replace(/\.[^/.]+$/, '').replace(/[_-]/g, ' ')
}

function formatFileSize(bytes: number): string {
    if (bytes < 1024) return `${bytes} B`
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
    if (bytes < 1024 * 1024 * 1024) return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
    return `${(bytes / (1024 * 1024 * 1024)).toFixed(2)} GB`
}

export function MediaUploader({
    name,
    mediaUrl,
    selectedFile,
    disabled,
    onMediaUrlChange,
    onSelectedFileChange,
    onAutoName,
    onError,
}: MediaUploaderProps) {
    const fileInputRef = useRef<HTMLInputElement>(null)
    const [isDragOver, setIsDragOver] = useState(false)

    const uploadZoneClass = `group relative flex flex-col items-center justify-center gap-4 px-8 py-12 border-2 rounded-2xl cursor-pointer transition-all duration-300 ${
        selectedFile
            ? 'border-[--color-success] border-solid bg-[rgba(16,185,129,0.05)]'
            : isDragOver
                ? 'border-[--color-primary] border-dashed bg-[rgba(99,102,241,0.1)] shadow-[var(--shadow-glow-primary)] scale-[1.02]'
                : 'border-[--color-border-light] border-dashed bg-[rgba(15,23,42,0.4)] hover:border-[--color-primary] hover:bg-[rgba(99,102,241,0.05)] hover:scale-[1.01]'
        }`

    const uploadIconClass = `w-16 h-16 flex items-center justify-center rounded-2xl transition-all duration-300 ${
        selectedFile
            ? 'bg-gradient-to-br from-[rgba(16,185,129,0.2)] to-[rgba(52,211,153,0.2)] text-[--color-success-light]'
            : 'bg-gradient-to-br from-[rgba(99,102,241,0.2)] to-[rgba(168,85,247,0.2)] text-[--color-primary-light] group-hover:scale-105 group-hover:from-[rgba(99,102,241,0.3)] group-hover:to-[rgba(168,85,247,0.3)]'
        }`

    const handleDragOver = (e: DragEvent<HTMLDivElement>) => {
        e.preventDefault()
        e.stopPropagation()
        setIsDragOver(true)
    }

    const handleDragLeave = (e: DragEvent<HTMLDivElement>) => {
        e.preventDefault()
        e.stopPropagation()
        setIsDragOver(false)
    }

    const acceptFile = (file: File) => {
        if (!isValidMediaFile(file)) {
            onError('请上传有效的视频或音频文件')
            return
        }
        onError(null)
        onSelectedFileChange(file)
        onMediaUrlChange('')
        if (!name) onAutoName(getNameFromFile(file.name))
    }

    const handleDrop = (e: DragEvent<HTMLDivElement>) => {
        e.preventDefault()
        e.stopPropagation()
        setIsDragOver(false)

        const files = e.dataTransfer.files
        if (files.length > 0) acceptFile(files[0])
    }

    const handleFileChange = (e: ChangeEvent<HTMLInputElement>) => {
        const files = e.target.files
        if (!files || files.length === 0) return
        acceptFile(files[0])
    }

    const handleClearFile = () => {
        onSelectedFileChange(null)
        if (fileInputRef.current) fileInputRef.current.value = ''
    }

    return (
        <div className="space-y-6">
            {/* File Upload Zone */}
            <div className="animate-slide-up" style={{ animationDelay: '0ms' }}>
                <label className="label">媒体文件</label>
                <div
                    className={uploadZoneClass}
                    onDragOver={handleDragOver}
                    onDragLeave={handleDragLeave}
                    onDrop={handleDrop}
                    onClick={() => !selectedFile && fileInputRef.current?.click()}
                >
                    <input
                        ref={fileInputRef}
                        type="file"
                        accept="video/*,audio/*,.mkv,.avi,.mov,.flv"
                        onChange={handleFileChange}
                        disabled={disabled}
                        className="hidden"
                    />

                    {selectedFile ? (
                        <div className="text-center animate-scale-in">
                            <div className={`${uploadIconClass} mx-auto mb-3`}>
                                <svg className="w-8 h-8" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
                                </svg>
                            </div>
                            <div className="font-medium text-[--color-text-secondary] mb-1 truncate max-w-[300px]">
                                {selectedFile.name}
                            </div>
                            <div className="text-sm text-[--color-text-muted] mb-3">{formatFileSize(selectedFile.size)}</div>
                            <button
                                type="button"
                                onClick={(e) => {
                                    e.stopPropagation()
                                    handleClearFile()
                                }}
                                className="text-sm text-[--color-error-light] hover:underline"
                            >
                                移除文件
                            </button>
                        </div>
                    ) : (
                        <>
                            <div className={uploadIconClass}>
                                <svg className="w-8 h-8" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                    <path
                                        strokeLinecap="round"
                                        strokeLinejoin="round"
                                        strokeWidth={2}
                                        d="M7 16a4 4 0 01-.88-7.903A5 5 0 1115.9 6L16 6a5 5 0 011 9.9M15 13l-3-3m0 0l-3 3m3-3v12"
                                    />
                                </svg>
                            </div>
                            <div className="text-center">
                                <div className="text-base font-medium text-[--color-text-secondary] mb-1">
                                    拖拽文件到此处，或 <span className="text-[--color-primary-light] font-medium">点击选择</span>
                                </div>
                                <div className="text-sm text-[--color-text-muted]">支持 MP4, MKV, AVI, MOV, MP3, WAV 等格式</div>
                            </div>
                        </>
                    )}
                </div>
            </div>

            {/* Divider */}
            <div className="flex items-center gap-4 animate-slide-up" style={{ animationDelay: '50ms' }}>
                <div className="flex-1 h-px bg-[--color-border]" />
                <span className="text-sm text-[--color-text-dim]">或</span>
                <div className="flex-1 h-px bg-[--color-border]" />
            </div>

            {/* URL Input */}
            <div className="animate-slide-up" style={{ animationDelay: '100ms' }}>
                <label htmlFor="mediaUrl" className="label">
                    媒体链接 / 服务器路径
                </label>
                <input
                    id="mediaUrl"
                    className="input"
                    placeholder="/path/to/video.mp4 或 https://..."
                    value={mediaUrl}
                    onChange={(e) => {
                        const next = e.target.value
                        onMediaUrlChange(next)
                        if (next) onSelectedFileChange(null)
                    }}
                    disabled={disabled}
                />
                <p className="text-xs text-[--color-text-dim] mt-2">输入服务器上的本地绝对路径，或公开可访问的 URL</p>
            </div>
        </div>
    )
}

