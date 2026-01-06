import { useState } from 'react'
import { useNavigate, Link } from 'react-router-dom'
import { createProject } from '../api/projects'
import { Spinner } from '../components/Spinner'

const languages = [
    { code: 'zh', name: '中文' },
    { code: 'en', name: 'English' },
    { code: 'ja', name: '日本語' },
    { code: 'ko', name: '한국어' },
    { code: 'es', name: 'Español' },
    { code: 'fr', name: 'Français' },
    { code: 'de', name: 'Deutsch' },
]

export default function NewProjectPage() {
    const navigate = useNavigate()
    const [name, setName] = useState('Demo')
    const [mediaUrl, setMediaUrl] = useState('')
    const [sourceLanguage, setSourceLanguage] = useState('')
    const [targetLanguage, setTargetLanguage] = useState('zh')
    const [loading, setLoading] = useState(false)
    const [error, setError] = useState<string | null>(null)

    const handleSubmit = async (e: React.FormEvent) => {
        e.preventDefault()
        if (!mediaUrl.trim()) {
            setError('请输入媒体路径或链接')
            return
        }

        setLoading(true)
        setError(null)

        try {
            const project = await createProject({
                name: name.trim() || 'Untitled',
                media_url: mediaUrl.trim(),
                language: sourceLanguage || undefined,
                target_language: targetLanguage,
            })
            navigate(`/projects/${project.id}`)
        } catch (err) {
            setError(err instanceof Error ? err.message : '创建项目失败')
        } finally {
            setLoading(false)
        }
    }

    return (
        <div className="max-w-2xl mx-auto">
            <div className="mb-6">
                <Link
                    to="/projects"
                    className="text-[--color-text-muted] hover:text-[--color-text] text-sm flex items-center gap-2"
                >
                    <span>←</span> 返回项目列表
                </Link>
            </div>

            <form onSubmit={handleSubmit} className="glass-card p-8">
                <h2 className="text-xl font-semibold mb-6">创建项目</h2>

                {error && (
                    <div className="mb-6 p-4 rounded-lg bg-red-500/10 border border-red-500/30 text-red-400">
                        {error}
                    </div>
                )}

                <div className="space-y-6">
                    <div>
                        <label htmlFor="name" className="block text-sm font-medium mb-2">
                            项目名称
                        </label>
                        <input
                            id="name"
                            className="input"
                            value={name}
                            onChange={(e) => setName(e.target.value)}
                            disabled={loading}
                        />
                    </div>

                    <div>
                        <label htmlFor="mediaUrl" className="block text-sm font-medium mb-2">
                            media_url
                        </label>
                        <input
                            id="mediaUrl"
                            className="input"
                            placeholder="/abs/path/video.mkv 或 https://..."
                            value={mediaUrl}
                            onChange={(e) => setMediaUrl(e.target.value)}
                            disabled={loading}
                        />
                        <p className="text-xs text-[--color-text-muted] mt-2">
                            支持本地路径或 http(s) URL
                        </p>
                    </div>

                    <div>
                        <label htmlFor="targetLanguage" className="block text-sm font-medium mb-2">
                            目标语言
                        </label>
                        <select
                            id="targetLanguage"
                            className="input"
                            value={targetLanguage}
                            onChange={(e) => setTargetLanguage(e.target.value)}
                            disabled={loading}
                        >
                            {languages.map((lang) => (
                                <option key={lang.code} value={lang.code}>
                                    {lang.name}
                                </option>
                            ))}
                        </select>
                    </div>

                    <div>
                        <label htmlFor="sourceLanguage" className="block text-sm font-medium mb-2">
                            源语言（可选）
                        </label>
                        <select
                            id="sourceLanguage"
                            className="input"
                            value={sourceLanguage}
                            onChange={(e) => setSourceLanguage(e.target.value)}
                            disabled={loading}
                        >
                            <option value="">自动识别</option>
                            {languages.map((lang) => (
                                <option key={lang.code} value={lang.code}>
                                    {lang.name}
                                </option>
                            ))}
                        </select>
                        <p className="text-xs text-[--color-text-muted] mt-2">
                            传给 ASR 的 language hint（可不填）
                        </p>
                    </div>

                    <button
                        type="submit"
                        className="btn-primary w-full flex items-center justify-center gap-2"
                        disabled={loading}
                    >
                        {loading ? (
                            <>
                                <Spinner size="sm" />
                                创建中...
                            </>
                        ) : (
                            <>
                                <span>🚀</span>
                                创建并开始
                            </>
                        )}
                    </button>
                </div>
            </form>
        </div>
    )
}

