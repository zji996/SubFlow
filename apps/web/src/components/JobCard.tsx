import { Link } from 'react-router-dom'
import type { Job } from '../api/jobs'
import { StatusBadge } from './StatusBadge'

interface JobCardProps {
    job: Job
}

export function JobCard({ job }: JobCardProps) {
    return (
        <Link
            to={`/jobs/${job.id}`}
            className="glass-card p-6 block hover:border-indigo-500/50 transition-all hover:-translate-y-1"
        >
            <div className="flex items-start justify-between gap-4">
                <div className="min-w-0 flex-1">
                    <h3 className="text-lg font-semibold text-[--color-text] truncate">
                        任务 #{job.id.slice(0, 8)}
                    </h3>
                    <p className="text-sm text-[--color-text-muted] mt-1">
                        ID: {job.id}
                    </p>
                </div>
                <StatusBadge status={job.status} />
            </div>

            {job.status === 'processing' && (
                <div className="mt-4">
                    <div className="h-2 bg-[--color-bg] rounded-full overflow-hidden">
                        <div className="h-full bg-gradient-to-r from-indigo-500 to-purple-500 rounded-full animate-pulse-glow w-1/2" />
                    </div>
                    <p className="text-xs text-[--color-text-muted] mt-2">正在处理中...</p>
                </div>
            )}

            {job.status === 'completed' && job.result_url && (
                <div className="mt-4 flex items-center gap-2 text-sm text-green-400">
                    <span>📥</span>
                    <span>字幕已生成</span>
                </div>
            )}

            {job.status === 'failed' && job.error && (
                <div className="mt-4 p-3 rounded-lg bg-red-500/10 border border-red-500/20">
                    <p className="text-sm text-red-400">{job.error}</p>
                </div>
            )}
        </Link>
    )
}
