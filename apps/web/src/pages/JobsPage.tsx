import { useState, useEffect } from 'react'
import { Link } from 'react-router-dom'
import type { Job } from '../api/jobs'
import { JobCard } from '../components/JobCard'
import { Spinner } from '../components/Spinner'

// Note: In production, this would fetch from an API endpoint that lists jobs
// For now, we'll store job IDs in localStorage as a simple solution
const STORAGE_KEY = 'subflow_jobs'

function getStoredJobIds(): string[] {
    try {
        const stored = localStorage.getItem(STORAGE_KEY)
        return stored ? JSON.parse(stored) : []
    } catch {
        return []
    }
}

export function addJobToStorage(jobId: string) {
    const ids = getStoredJobIds()
    if (!ids.includes(jobId)) {
        ids.unshift(jobId)
        localStorage.setItem(STORAGE_KEY, JSON.stringify(ids.slice(0, 50)))
    }
}

export default function JobsPage() {
    const [jobs, setJobs] = useState<Job[]>([])
    const [loading, setLoading] = useState(true)
    const [error, setError] = useState<string | null>(null)

    useEffect(() => {
        async function fetchJobs() {
            const jobIds = getStoredJobIds()
            if (jobIds.length === 0) {
                setLoading(false)
                return
            }

            try {
                const results = await Promise.allSettled(
                    jobIds.map((id) =>
                        fetch(`/jobs/${id}`).then((res) => {
                            if (!res.ok) throw new Error('Not found')
                            return res.json()
                        })
                    )
                )

                const fetchedJobs: Job[] = []
                results.forEach((result) => {
                    if (result.status === 'fulfilled') {
                        fetchedJobs.push(result.value)
                    }
                })

                setJobs(fetchedJobs)
            } catch (err) {
                setError(err instanceof Error ? err.message : 'Failed to load jobs')
            } finally {
                setLoading(false)
            }
        }

        fetchJobs()
        // Poll for updates every 5 seconds
        const interval = setInterval(fetchJobs, 5000)
        return () => clearInterval(interval)
    }, [])

    if (loading) {
        return (
            <div className="flex items-center justify-center py-20">
                <Spinner size="lg" />
            </div>
        )
    }

    return (
        <div>
            <div className="flex items-center justify-between mb-8">
                <div>
                    <h1 className="text-2xl font-bold">任务列表</h1>
                    <p className="text-[--color-text-muted] mt-1">
                        查看和管理您的翻译任务
                    </p>
                </div>
                <Link to="/" className="btn-primary">
                    <span>➕</span> 新建任务
                </Link>
            </div>

            {error && (
                <div className="p-4 rounded-lg bg-red-500/10 border border-red-500/30 text-red-400 mb-6">
                    {error}
                </div>
            )}

            {jobs.length === 0 ? (
                <div className="glass-card p-12 text-center">
                    <div className="text-6xl mb-4">📭</div>
                    <h3 className="text-xl font-semibold mb-2">暂无任务</h3>
                    <p className="text-[--color-text-muted] mb-6">
                        创建您的第一个翻译任务开始使用
                    </p>
                    <Link to="/" className="btn-primary inline-block">
                        创建任务
                    </Link>
                </div>
            ) : (
                <div className="grid gap-4 md:grid-cols-2">
                    {jobs.map((job) => (
                        <JobCard key={job.id} job={job} />
                    ))}
                </div>
            )}
        </div>
    )
}
