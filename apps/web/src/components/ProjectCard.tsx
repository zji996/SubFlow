import { Link } from 'react-router-dom'
import type { Project } from '../api/projects'
import { StatusBadge } from './StatusBadge'

interface ProjectCardProps {
    project: Project
}

export function ProjectCard({ project }: ProjectCardProps) {
    return (
        <Link
            to={`/projects/${project.id}`}
            className="glass-card p-6 block hover:border-indigo-500/50 transition-all hover:-translate-y-1"
        >
            <div className="flex items-start justify-between gap-4">
                <div className="min-w-0 flex-1">
                    <h3 className="text-lg font-semibold text-[--color-text] truncate">
                        {project.name || `项目 #${project.id.slice(0, 8)}`}
                    </h3>
                    <p className="text-xs text-[--color-text-muted] mt-1 font-mono">
                        {project.id}
                    </p>
                    <p className="text-sm text-[--color-text-muted] mt-2 truncate">
                        {project.media_url}
                    </p>
                </div>
                <StatusBadge status={project.status} />
            </div>

            <div className="mt-4 flex items-center justify-between text-xs text-[--color-text-muted]">
                <span>Stage: {project.current_stage}/6</span>
                <span>{project.target_language}</span>
            </div>
        </Link>
    )
}
