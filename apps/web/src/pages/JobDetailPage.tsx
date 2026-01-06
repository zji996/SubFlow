import { useEffect, useCallback, useState } from 'react'
import { useParams, Link } from 'react-router-dom'
import { getJob, type Job } from '../api/jobs'
import { usePolling } from '../hooks/usePolling'
import { StatusBadge } from '../components/StatusBadge'
import { Spinner } from '../components/Spinner'
import { addJobToStorage } from './JobsPage'

export default function JobDetailPage() {
    const { jobId } = useParams<{ jobId: string }>()
    const [subtitleContent, setSubtitleContent] = useState<string | null>(null)
    const [downloading, setDownloading] = useState(false)

    const fetcher = useCallback(() => {
        if (!jobId) throw new Error('No job ID')
        return getJob(jobId)
    }, [jobId])

    const { data: job, loading, error } = usePolling<Job>({
        fetcher,
        interval: 2000,
        enabled: !!jobId,
        shouldStop: (data) => data.status === 'completed' || data.status === 'failed',
    })

    // Store job ID for history
    useEffect(() => {
        if (jobId) {
            addJobToStorage(jobId)
        }
    }, [jobId])

    // Fetch subtitle content when completed
    useEffect(() => {
        async function fetchSubtitle() {
            if (job?.status === 'completed' && jobId) {
                try {
                    // Try to get the subtitle from Redis via a custom endpoint
                    const response = await fetch(`/jobs/${jobId}/result`)
                    if (response.ok) {
                        const text = await response.text()
                        setSubtitleContent(text)
                    }
                } catch {
                    // Ignore errors - subtitle preview is optional
                }
            }
        }
        fetchSubtitle()
    }, [job?.status, jobId])

    const handleDownload = async () => {
        if (!job?.result_url) return
        setDownloading(true)
        try {
            const response = await fetch(job.result_url)
            const blob = await response.blob()
            const url = window.URL.createObjectURL(blob)
            const a = document.createElement('a')
            a.href = url
            a.download = `subtitles_${jobId}.srt`
            document.body.appendChild(a)
            a.click()
            window.URL.revokeObjectURL(url)
            document.body.removeChild(a)
        } catch (err) {
            console.error('Download failed:', err)
        } finally {
            setDownloading(false)
        }
    }

    if (loading && !job) {
        return (
            <div className="flex items-center justify-center py-20">
                <Spinner size="lg" />
            </div>
        )
    }

    if (error && !job) {
        return (
            <div className="max-w-2xl mx-auto">
                <div className="glass-card p-8 text-center">
                    <div className="text-5xl mb-4">⚠️</div>
                    <h2 className="text-xl font-semibold mb-2">加载失败</h2>
                    <p className="text-[--color-text-muted] mb-6">{error.message}</p>
                    <Link to="/jobs" className="btn-primary inline-block">
                        返回列表
                    </Link>
                </div>
            </div>
        )
    }

    if (!job) return null

    return (
        <div className="max-w-3xl mx-auto">
            {/* Breadcrumb */}
            <div className="mb-6">
                <Link to="/jobs" className="text-[--color-text-muted] hover:text-[--color-text] text-sm flex items-center gap-2">
                    <span>←</span> 返回任务列表
                </Link>
            </div>

            {/* Main Card */}
            <div className="glass-card p-8">
                <div className="flex items-start justify-between gap-4 mb-8">
                    <div>
                        <h1 className="text-2xl font-bold mb-2">
                            任务 #{job.id.slice(0, 8)}
                        </h1>
                        <p className="text-sm text-[--color-text-muted] font-mono">
                            {job.id}
                        </p>
                    </div>
                    <StatusBadge status={job.status} />
                </div>

                {/* Progress for processing jobs */}
                {job.status === 'processing' && (
                    <div className="mb-8">
                        <div className="flex items-center gap-4 mb-4">
                            <Spinner size="md" />
                            <span className="text-[--color-text-muted]">正在处理您的视频...</span>
                        </div>
                        <div className="space-y-2">
                            {[
                                { stage: '音频提取', done: true },
                                { stage: '语音识别', done: true },
                                { stage: 'LLM 处理', done: false, active: true },
                                { stage: '字幕生成', done: false },
                            ].map((step) => (
                                <div
                                    key={step.stage}
                                    className={`flex items-center gap-3 text-sm ${step.done
                                            ? 'text-green-400'
                                            : step.active
                                                ? 'text-indigo-400'
                                                : 'text-[--color-text-muted]'
                                        }`}
                                >
                                    <span>
                                        {step.done ? '✅' : step.active ? '⏳' : '⏸️'}
                                    </span>
                                    <span>{step.stage}</span>
                                    {step.active && <Spinner size="sm" />}
                                </div>
                            ))}
                        </div>
                    </div>
                )}

                {/* Completed */}
                {job.status === 'completed' && (
                    <div className="space-y-6">
                        <div className="p-4 rounded-lg bg-green-500/10 border border-green-500/30">
                            <div className="flex items-center gap-3 text-green-400">
                                <span className="text-2xl">🎉</span>
                                <div>
                                    <h3 className="font-semibold">翻译完成</h3>
                                    <p className="text-sm opacity-80">您的字幕已准备就绪</p>
                                </div>
                            </div>
                        </div>

                        {/* Subtitle Preview */}
                        {subtitleContent && (
                            <div>
                                <h3 className="text-sm font-medium mb-2 text-[--color-text-muted]">
                                    字幕预览
                                </h3>
                                <pre className="bg-[--color-bg] rounded-lg p-4 text-sm overflow-x-auto max-h-64 overflow-y-auto font-mono">
                                    {subtitleContent.slice(0, 2000)}
                                    {subtitleContent.length > 2000 && '\n\n...'}
                                </pre>
                            </div>
                        )}

                        {/* Download Button */}
                        {job.result_url && (
                            <button
                                onClick={handleDownload}
                                disabled={downloading}
                                className="btn-primary w-full flex items-center justify-center gap-2"
                            >
                                {downloading ? (
                                    <>
                                        <Spinner size="sm" />
                                        下载中...
                                    </>
                                ) : (
                                    <>
                                        <span>📥</span>
                                        下载字幕文件
                                    </>
                                )}
                            </button>
                        )}
                    </div>
                )}

                {/* Failed */}
                {job.status === 'failed' && (
                    <div className="p-6 rounded-lg bg-red-500/10 border border-red-500/30">
                        <div className="flex items-start gap-4">
                            <span className="text-3xl">❌</span>
                            <div>
                                <h3 className="font-semibold text-red-400 mb-2">处理失败</h3>
                                <p className="text-sm text-[--color-text-muted]">
                                    {job.error || '未知错误'}
                                </p>
                                <Link
                                    to="/"
                                    className="inline-block mt-4 text-sm text-indigo-400 hover:text-indigo-300"
                                >
                                    ← 重新提交任务
                                </Link>
                            </div>
                        </div>
                    </div>
                )}

                {/* Pending */}
                {job.status === 'pending' && (
                    <div className="text-center py-8">
                        <div className="text-5xl mb-4">⏳</div>
                        <h3 className="text-lg font-medium mb-2">任务等待中</h3>
                        <p className="text-[--color-text-muted]">
                            您的任务已加入队列，正在等待处理
                        </p>
                    </div>
                )}
            </div>
        </div>
    )
}
