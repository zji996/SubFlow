import type { Project } from '../../../types/entities'
import { StatusBadge } from '../../common/StatusBadge'

export function ProjectHeader({ project }: { project: Project }) {
    return (
        <div className="flex flex-col md:flex-row md:items-center justify-between gap-4 mb-6">
            <div>
                <h1 className="text-2xl font-bold text-gradient mb-2">
                    {project.name || `项目 #${project.id.slice(0, 8)}`}
                </h1>
                <p className="text-sm text-[--color-text-muted] font-mono">{project.id}</p>
            </div>
            <StatusBadge status={project.status} />
        </div>
    )
}

