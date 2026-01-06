import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { createJob } from '../api/jobs'
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

export default function HomePage() {
    const navigate = useNavigate()
    const [videoUrl, setVideoUrl] = useState('')
    const [sourceLanguage, setSourceLanguage] = useState('')
    const [targetLanguage, setTargetLanguage] = useState('zh')
    const [loading, setLoading] = useState(false)
    const [error, setError] = useState<string | null>(null)

    const handleSubmit = async (e: React.FormEvent) => {
        e.preventDefault()
        if (!videoUrl.trim()) {
            setError('请输入视频链接')
            return
        }

        setLoading(true)
        setError(null)

        try {
            const job = await createJob({
                video_url: videoUrl.trim(),
                source_language: sourceLanguage || undefined,
                target_language: targetLanguage,
            })
            navigate(`/jobs/${job.id}`)
        } catch (err) {
            setError(err instanceof Error ? err.message : '创建任务失败')
        } finally {
            setLoading(false)
        }
    }

    return (
        <div className="max-w-2xl mx-auto">
            {/* Hero Section */}
            <div className="text-center mb-12">
                <h1 className="text-4xl md:text-5xl font-bold mb-4">
                    <span className="bg-gradient-to-r from-indigo-400 via-purple-400 to-pink-400 bg-clip-text text-transparent">
                        视频语义翻译
                    </span>
                </h1>
                <p className="text-lg text-[--color-text-muted] max-w-xl mx-auto">
                    基于语义理解的字幕翻译系统，通过多阶段 LLM 处理，生成更加自然、准确的翻译字幕
                </p>
            </div>

            {/* Features */}
            <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-12">
                {[
                    { icon: '🎯', label: '语义切分' },
                    { icon: '📚', label: '术语一致' },
                    { icon: '🔄', label: '多 Pass 精化' },
                    { icon: '🌍', label: '多语言支持' },
                ].map((feature) => (
                    <div
                        key={feature.label}
                        className="glass-card p-4 text-center"
                    >
                        <span className="text-2xl mb-2 block">{feature.icon}</span>
                        <span className="text-sm text-[--color-text-muted]">{feature.label}</span>
                    </div>
                ))}
            </div>

            {/* Form */}
            <form onSubmit={handleSubmit} className="glass-card p-8">
                <h2 className="text-xl font-semibold mb-6">创建翻译任务</h2>

                {error && (
                    <div className="mb-6 p-4 rounded-lg bg-red-500/10 border border-red-500/30 text-red-400">
                        {error}
                    </div>
                )}

                <div className="space-y-6">
                    <div>
                        <label htmlFor="videoUrl" className="block text-sm font-medium mb-2">
                            视频链接
                        </label>
                        <input
                            id="videoUrl"
                            type="url"
                            className="input"
                            placeholder="https://example.com/video.mp4"
                            value={videoUrl}
                            onChange={(e) => setVideoUrl(e.target.value)}
                            disabled={loading}
                        />
                        <p className="text-xs text-[--color-text-muted] mt-2">
                            支持 MP4, MKV, WebM 等常见视频格式
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
                            指定后会作为 ASR 语言提示（例如 `en`、`zh`），不指定则交由模型自动判断
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
                                开始翻译
                            </>
                        )}
                    </button>
                </div>
            </form>

            {/* How it works */}
            <div className="mt-12">
                <h3 className="text-lg font-semibold mb-6 text-center">工作流程</h3>
                <div className="flex items-center justify-between text-sm">
                    {[
                        { step: 1, label: '音频提取', icon: '🎵' },
                        { step: 2, label: '语音识别', icon: '🎙️' },
                        { step: 3, label: '语义切分', icon: '✂️' },
                        { step: 4, label: 'AI翻译', icon: '🤖' },
                        { step: 5, label: '质量审校', icon: '✅' },
                    ].map((item, index) => (
                        <div key={item.step} className="flex items-center">
                            <div className="flex flex-col items-center">
                                <div className="w-12 h-12 rounded-full bg-gradient-to-br from-indigo-500/20 to-purple-500/20 border border-indigo-500/30 flex items-center justify-center text-xl">
                                    {item.icon}
                                </div>
                                <span className="text-[--color-text-muted] mt-2 text-xs">{item.label}</span>
                            </div>
                            {index < 4 && (
                                <div className="w-8 h-px bg-gradient-to-r from-indigo-500/50 to-transparent mx-2" />
                            )}
                        </div>
                    ))}
                </div>
            </div>
        </div>
    )
}
