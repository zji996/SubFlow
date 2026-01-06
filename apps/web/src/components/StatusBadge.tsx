interface StatusBadgeProps {
    status: string
}

const statusConfig: Record<string, { label: string; class: string; icon: string }> = {
    pending: { label: '等待中', class: 'badge-pending', icon: '⏳' },
    processing: { label: '处理中', class: 'badge-processing', icon: '⚙️' },
    paused: { label: '已暂停', class: 'badge-pending', icon: '⏸️' },
    completed: { label: '已完成', class: 'badge-completed', icon: '✅' },
    failed: { label: '失败', class: 'badge-failed', icon: '❌' },
}

export function StatusBadge({ status }: StatusBadgeProps) {
    const config = statusConfig[status] || { label: status, class: 'badge-pending', icon: 'ℹ️' }
    return (
        <span className={`badge ${config.class}`}>
            <span>{config.icon}</span>
            {config.label}
        </span>
    )
}
