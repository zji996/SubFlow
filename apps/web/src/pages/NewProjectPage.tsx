import { useState, type FormEvent } from 'react'
import { useNavigate } from 'react-router-dom'
import { ProjectForm, type ProjectFormValues } from '../components/form/ProjectForm'
import { useProjects } from '../hooks/useProjects'
import { useUpload } from '../hooks/useUpload'

export default function NewProjectPage() {
    const navigate = useNavigate()

    const { createProject, creating, error: createError, clearError } = useProjects({ autoFetch: false })
    const { upload, loading: uploadLoading, error: uploadError, progress: uploadProgress, reset: resetUpload } = useUpload()

    const [values, setValues] = useState<ProjectFormValues>({
        name: '',
        mediaUrl: '',
        selectedFile: null,
        sourceLanguage: '',
        targetLanguage: 'zh',
    })
    const [localError, setLocalError] = useState<string | null>(null)

    const loading = creating || uploadLoading
    const error = localError || uploadError || createError

    const handleChange = (next: Partial<ProjectFormValues>) => {
        setValues((prev) => ({ ...prev, ...next }))
    }

    const handleSubmit = async (e: FormEvent) => {
        e.preventDefault()

        if (!values.selectedFile && !values.mediaUrl.trim()) {
            setLocalError('请选择文件或输入媒体链接')
            return
        }

        setLocalError(null)
        clearError()
        resetUpload()

        try {
            let finalMediaUrl = values.mediaUrl.trim()
            if (values.selectedFile && !finalMediaUrl) {
                const uploadResult = await upload(values.selectedFile)
                finalMediaUrl = uploadResult.media_url
            }

            const project = await createProject({
                name: (values.name.trim() || values.selectedFile?.name?.replace(/\.[^/.]+$/, '') || 'Untitled').slice(0, 100),
                media_url: finalMediaUrl,
                language: values.sourceLanguage || undefined,
                target_language: values.targetLanguage,
            })
            navigate(`/projects/${project.id}`)
        } catch (err) {
            // Hook errors already set; keep local error for non-API validation.
            if (err instanceof DOMException && err.name === 'AbortError') return
        }
    }

    return (
        <ProjectForm
            values={values}
            error={error}
            loading={loading}
            uploadProgress={uploadProgress}
            onChange={handleChange}
            onSubmit={handleSubmit}
            onError={(message) => setLocalError(message)}
        />
    )
}

