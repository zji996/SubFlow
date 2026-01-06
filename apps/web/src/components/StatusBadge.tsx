import type { Job } from '../api/jobs'

interface StatusBadgeProps {
    status: Job['status']
}

const statusConfig = {
    pending: {
        label: '等待中',
        class: 'badge-pending',
        icon: '⏳',
    },
    processing: {
        label: '处理中',
        class: 'badge-processing',
        icon: '⚙️',
    },
    completed: {
        label: '已完成',
        class: 'badge-completed',
        icon: '✅',
    },
    failed: {
        label: '失败',
        class: 'badge-failed',
        icon: '❌',
    },
}

export function StatusBadge({ status }: StatusBadgeProps) {
    const config = statusConfig[status]
    return (
        <span className={`badge ${config.class}`}>
            <span>{config.icon}</span>
            {config.label}
        </span>
    )
}
