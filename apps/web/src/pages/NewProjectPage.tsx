import { useState, useRef, DragEvent, ChangeEvent } from 'react'
import { useNavigate, Link } from 'react-router-dom'
import { createProject } from '../api/projects'
import { uploadFile, type UploadProgress } from '../api/uploads'
import { Spinner } from '../components/common/Spinner'
import { Select } from '../components/common/Select'

const languages = [
    { code: 'zh', name: '中文', flag: '🇨🇳' },
    { code: 'en', name: 'English', flag: '🇺🇸' },
    { code: 'ja', name: '日本語', flag: '🇯🇵' },
    { code: 'ko', name: '한국어', flag: '🇰🇷' },
    { code: 'es', name: 'Español', flag: '🇪🇸' },
    { code: 'fr', name: 'Français', flag: '🇫🇷' },
    { code: 'de', name: 'Deutsch', flag: '🇩🇪' },
    { code: 'ru', name: 'Русский', flag: '🇷🇺' },
    { code: 'pt', name: 'Português', flag: '🇵🇹' },
    { code: 'it', name: 'Italiano', flag: '🇮🇹' },
]

export default function NewProjectPage() {
    const navigate = useNavigate()
    const fileInputRef = useRef<HTMLInputElement>(null)

    const [name, setName] = useState('')
    const [mediaUrl, setMediaUrl] = useState('')
    const [selectedFile, setSelectedFile] = useState<File | null>(null)
    const [sourceLanguage, setSourceLanguage] = useState('')
    const [targetLanguage, setTargetLanguage] = useState('zh')
    const [loading, setLoading] = useState(false)
    const [error, setError] = useState<string | null>(null)
    const [isDragOver, setIsDragOver] = useState(false)
    const [uploadProgress, setUploadProgress] = useState<UploadProgress | null>(null)

    const uploadZoneClass = `group relative flex flex-col items-center justify-center gap-4 px-8 py-12 border-2 rounded-2xl cursor-pointer transition-all duration-300 ${selectedFile
        ? 'border-[--color-success] border-solid bg-[rgba(16,185,129,0.05)]'
        : isDragOver
            ? 'border-[--color-primary] border-dashed bg-[rgba(99,102,241,0.1)] shadow-[var(--shadow-glow-primary)] scale-[1.02]'
            : 'border-[--color-border-light] border-dashed bg-[rgba(15,23,42,0.4)] hover:border-[--color-primary] hover:bg-[rgba(99,102,241,0.05)] hover:scale-[1.01]'
        }`

    const uploadIconClass = `w-16 h-16 flex items-center justify-center rounded-2xl transition-all duration-300 ${selectedFile
        ? 'bg-gradient-to-br from-[rgba(16,185,129,0.2)] to-[rgba(52,211,153,0.2)] text-[--color-success-light]'
        : 'bg-gradient-to-br from-[rgba(99,102,241,0.2)] to-[rgba(168,85,247,0.2)] text-[--color-primary-light] group-hover:scale-105 group-hover:from-[rgba(99,102,241,0.3)] group-hover:to-[rgba(168,85,247,0.3)]'
        }`

    const languageOptions = languages.map(l => ({
        value: l.code,
        label: l.name,
        icon: l.flag
    }))

    const sourceOptions = [
        { value: '', label: '自动识别', icon: '🔍' },
        ...languageOptions
    ]

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

    const handleDrop = (e: DragEvent<HTMLDivElement>) => {
        e.preventDefault()
        e.stopPropagation()
        setIsDragOver(false)

        const files = e.dataTransfer.files
        if (files.length > 0) {
            const file = files[0]
            if (isValidMediaFile(file)) {
                setSelectedFile(file)
                setMediaUrl('')
                // Auto-fill name from filename
                if (!name) {
                    setName(getNameFromFile(file.name))
                }
            } else {
                setError('请上传有效的视频或音频文件')
            }
        }
    }

    const handleFileChange = (e: ChangeEvent<HTMLInputElement>) => {
        const files = e.target.files
        if (files && files.length > 0) {
            const file = files[0]
            if (isValidMediaFile(file)) {
                setSelectedFile(file)
                setMediaUrl('')
                if (!name) {
                    setName(getNameFromFile(file.name))
                }
            } else {
                setError('请上传有效的视频或音频文件')
            }
        }
    }

    const isValidMediaFile = (file: File): boolean => {
        const validTypes = [
            'video/mp4', 'video/webm', 'video/ogg', 'video/quicktime',
            'video/x-matroska', 'video/x-msvideo', 'video/x-flv',
            'audio/mpeg', 'audio/wav', 'audio/ogg', 'audio/flac', 'audio/aac',
            'audio/mp4', 'audio/x-m4a'
        ]
        // Also check extension for .mkv etc
        const ext = file.name.split('.').pop()?.toLowerCase()
        const validExts = ['mp4', 'mkv', 'avi', 'mov', 'webm', 'flv', 'mp3', 'wav', 'flac', 'aac', 'm4a', 'ogg']
        return validTypes.includes(file.type) || (ext !== undefined && validExts.includes(ext))
    }

    const getNameFromFile = (filename: string): string => {
        return filename.replace(/\.[^/.]+$/, '').replace(/[_-]/g, ' ')
    }

    const handleClearFile = () => {
        setSelectedFile(null)
        if (fileInputRef.current) {
            fileInputRef.current.value = ''
        }
    }

    const formatFileSize = (bytes: number): string => {
        if (bytes < 1024) return `${bytes} B`
        if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
        if (bytes < 1024 * 1024 * 1024) return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
        return `${(bytes / (1024 * 1024 * 1024)).toFixed(2)} GB`
    }

    const handleSubmit = async (e: React.FormEvent) => {
        e.preventDefault()

        // Validate input
        if (!selectedFile && !mediaUrl.trim()) {
            setError('请选择文件或输入媒体链接')
            return
        }

        setLoading(true)
        setError(null)
        setUploadProgress(null)

        try {
            let finalMediaUrl = mediaUrl.trim()

            // If file selected, upload it first
            if (selectedFile && !mediaUrl.trim()) {
                try {
                    const uploadResult = await uploadFile(selectedFile, (progress) => {
                        setUploadProgress(progress)
                    })
                    finalMediaUrl = uploadResult.media_url
                } catch (uploadErr) {
                    if (uploadErr instanceof DOMException && uploadErr.name === 'AbortError') {
                        setLoading(false)
                        return
                    }
                    throw new Error(`文件上传失败: ${uploadErr instanceof Error ? uploadErr.message : '未知错误'}`)
                }
            }

            const project = await createProject({
                name: (name.trim() || selectedFile?.name?.replace(/\.[^/.]+$/, '') || 'Untitled').slice(0, 100),
                media_url: finalMediaUrl,
                language: sourceLanguage || undefined,
                target_language: targetLanguage,
            })
            navigate(`/projects/${project.id}`)
        } catch (err) {
            setError(err instanceof Error ? err.message : '创建项目失败')
        } finally {
            setLoading(false)
            setUploadProgress(null)
        }
    }

    return (
        <div className="max-w-2xl mx-auto animate-fade-in pb-12">
            {/* Back link */}
            <div className="mb-6">
                <Link
                    to="/projects"
                    className="inline-flex items-center gap-2 text-[--color-text-muted] hover:text-[--color-text] text-sm transition-colors hover:-translate-x-1 duration-200"
                >
                    <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 19l-7-7 7-7" />
                    </svg>
                    返回项目列表
                </Link>
            </div>

            <form onSubmit={handleSubmit} className="glass-card p-8">
                {/* Header */}
                <div className="mb-8">
                    <h1 className="text-2xl font-bold text-gradient mb-2">创建新项目</h1>
                    <p className="text-[--color-text-muted]">
                        上传视频或音频文件，开始自动翻译字幕
                    </p>
                </div>

                {/* Error */}
                {error && (
                    <div className="mb-6 p-4 rounded-xl bg-[--color-error]/10 border border-[--color-error]/30 text-[--color-error-light] flex items-start gap-3 animate-scale-in">
                        <svg className="w-5 h-5 shrink-0 mt-0.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 8v4m0 4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
                        </svg>
                        <span>{error}</span>
                    </div>
                )}

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
                                disabled={loading}
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
                                    <div className="text-sm text-[--color-text-muted] mb-3">
                                        {formatFileSize(selectedFile.size)}
                                    </div>
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
                                            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M7 16a4 4 0 01-.88-7.903A5 5 0 1115.9 6L16 6a5 5 0 011 9.9M15 13l-3-3m0 0l-3 3m3-3v12" />
                                        </svg>
                                    </div>
                                    <div className="text-center">
                                        <div className="text-base font-medium text-[--color-text-secondary] mb-1">
                                            拖拽文件到此处，或 <span className="text-[--color-primary-light] font-medium">点击选择</span>
                                        </div>
                                        <div className="text-sm text-[--color-text-muted]">
                                            支持 MP4, MKV, AVI, MOV, MP3, WAV 等格式
                                        </div>
                                    </div>
                                </>
                            )}
                        </div>
                    </div>

                    {/* Divider */}
                    <div className="flex items-center gap-4 animate-slide-up" style={{ animationDelay: '50ms' }}>
                        <div className="flex-1 h-px bg-[--color-border]"></div>
                        <span className="text-sm text-[--color-text-dim]">或</span>
                        <div className="flex-1 h-px bg-[--color-border]"></div>
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
                                setMediaUrl(e.target.value)
                                if (e.target.value) setSelectedFile(null)
                            }}
                            disabled={loading}
                        />
                        <p className="text-xs text-[--color-text-dim] mt-2">
                            输入服务器上的本地绝对路径，或公开可访问的 URL
                        </p>
                    </div>

                    {/* Project Name */}
                    <div className="animate-slide-up" style={{ animationDelay: '150ms' }}>
                        <label htmlFor="name" className="label">
                            项目名称
                        </label>
                        <input
                            id="name"
                            className="input"
                            placeholder="默认使用文件名"
                            value={name}
                            onChange={(e) => setName(e.target.value)}
                            disabled={loading}
                        />
                    </div>

                    {/* Language Selection */}
                    <div className="grid grid-cols-2 gap-4 animate-slide-up" style={{ animationDelay: '200ms' }}>
                        <div>
                            <label htmlFor="sourceLanguage" className="label">
                                源语言
                            </label>
                            <Select
                                value={sourceLanguage}
                                onChange={setSourceLanguage}
                                options={sourceOptions}
                                placeholder="自动识别"
                                disabled={loading}
                                searchable
                            />
                        </div>
                        <div>
                            <label htmlFor="targetLanguage" className="label">
                                目标语言
                            </label>
                            <Select
                                value={targetLanguage}
                                onChange={setTargetLanguage}
                                options={languageOptions}
                                disabled={loading}
                                searchable
                            />
                        </div>
                    </div>

                    {/* Submit Button */}
                    <div className="animate-slide-up" style={{ animationDelay: '250ms' }}>
                        <button
                            type="submit"
                            className="btn-primary w-full py-4 text-base"
                            disabled={loading || (!selectedFile && !mediaUrl.trim())}
                        >
                            {loading ? (
                                <>
                                    <Spinner size="sm" />
                                    <span>
                                        {uploadProgress
                                            ? `上传中 ${uploadProgress.percent}%`
                                            : '创建中...'}
                                    </span>
                                </>
                            ) : (
                                <>
                                    <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13 10V3L4 14h7v7l9-11h-7z" />
                                    </svg>
                                    <span>创建项目</span>
                                </>
                            )}
                        </button>
                    </div>

                    {/* Upload Progress Bar */}
                    {uploadProgress && (
                        <div className="animate-fade-in">
                            <div className="flex justify-between text-xs text-[--color-text-muted] mb-1">
                                <span>上传进度</span>
                                <span>{uploadProgress.percent}%</span>
                            </div>
                            <div className="h-2 rounded-full bg-[--color-bg-elevated] overflow-hidden">
                                <div
                                    className="h-full bg-gradient-to-r from-[--color-primary] to-[--color-accent] transition-all duration-300"
                                    style={{ width: `${uploadProgress.percent}%` }}
                                />
                            </div>
                        </div>
                    )}
                </div>
            </form>

            {/* Tips */}
            <div className="mt-6 p-4 rounded-xl bg-[--color-bg-card] border border-[--color-border] animate-slide-up" style={{ animationDelay: '300ms' }}>
                <h3 className="text-sm font-medium text-[--color-text-secondary] mb-2 flex items-center gap-2">
                    <svg className="w-4 h-4 text-[--color-primary-light]" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13 16h-1v-4h-1m1-4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
                    </svg>
                    提示
                </h3>
                <ul className="text-sm text-[--color-text-muted] space-y-1">
                    <li>• 如果服务器与浏览器不在同一台机器，请使用服务器上的本地路径</li>
                    <li>• 支持自动检测源语言，但指定可提高识别准确率</li>
                    <li>• 处理时间取决于视频长度，一般 1 小时视频约需 10-20 分钟</li>
                </ul>
            </div>
        </div>
    )
}
