import type { FormEvent } from 'react'
import { Link } from 'react-router-dom'
import { Spinner } from '../common/Spinner'
import { LLMHealthAlert } from '../common/LLMHealthAlert'
import type { UploadProgress } from '../../types/api'
import { MediaUploader } from './MediaUploader'
import { LanguageSelector } from './LanguageSelector'

export interface ProjectFormValues {
    name: string
    mediaUrl: string
    selectedFile: File | null
    sourceLanguage: string
    targetLanguage: string
}

export interface ProjectFormProps {
    values: ProjectFormValues
    error: string | null
    loading: boolean
    uploadProgress: UploadProgress | null
    onChange: (next: Partial<ProjectFormValues>) => void
    onSubmit: (e: FormEvent) => void
    onError: (message: string | null) => void
}

export function ProjectForm({ values, error, loading, uploadProgress, onChange, onSubmit, onError }: ProjectFormProps) {
    return (
        <div className="max-w-2xl mx-auto animate-fade-in pb-12">
            <div className="mb-6">
                <Link
                    to="/projects"
                    className="inline-flex items-center gap-2 text-[--color-text-muted] hover:text-[--color-text] text-sm transition-colors hover:-translate-x-1 duration-200"
                >
                    <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 19l-7-7 7-7" />
                    </svg>
                    返回项目列表
                </Link>
            </div>

            <form onSubmit={onSubmit} className="glass-card p-8">
                <div className="mb-8">
                    <h1 className="text-2xl font-bold text-gradient mb-2">创建新项目</h1>
                    <p className="text-[--color-text-muted]" />
                </div>

                <div className="mb-6">
                    <LLMHealthAlert />
                </div>

                {error && (
                    <div className="mb-6 p-4 rounded-xl bg-[--color-error]/10 border border-[--color-error]/30 text-[--color-error-light] flex items-start gap-3 animate-scale-in">
                        <svg className="w-5 h-5 shrink-0 mt-0.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 8v4m0 4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
                        </svg>
                        <span>{error}</span>
                    </div>
                )}

                <div className="space-y-6">
                    <MediaUploader
                        name={values.name}
                        mediaUrl={values.mediaUrl}
                        selectedFile={values.selectedFile}
                        disabled={loading}
                        onMediaUrlChange={(v) => onChange({ mediaUrl: v })}
                        onSelectedFileChange={(f) => onChange({ selectedFile: f })}
                        onAutoName={(v) => onChange({ name: v })}
                        onError={onError}
                    />

                    <div className="animate-slide-up" style={{ animationDelay: '150ms' }}>
                        <label htmlFor="name" className="label">
                            项目名称
                        </label>
                        <input
                            id="name"
                            className="input"
                            placeholder="默认使用文件名"
                            value={values.name}
                            onChange={(e) => onChange({ name: e.target.value })}
                            disabled={loading}
                        />
                    </div>

                    <LanguageSelector
                        sourceLanguage={values.sourceLanguage}
                        targetLanguage={values.targetLanguage}
                        disabled={loading}
                        onSourceLanguageChange={(v) => onChange({ sourceLanguage: v })}
                        onTargetLanguageChange={(v) => onChange({ targetLanguage: v })}
                    />

                    <div className="animate-slide-up" style={{ animationDelay: '250ms' }}>
                        <button
                            type="submit"
                            className="btn-primary w-full py-4 text-base"
                            disabled={loading || (!values.selectedFile && !values.mediaUrl.trim())}
                        >
                            {loading ? (
                                <>
                                    <Spinner size="sm" />
                                    <span>{uploadProgress ? `上传中 ${uploadProgress.percent}%` : '创建中...'}</span>
                                </>
                            ) : (
                                <>
                                    <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                        <path
                                            strokeLinecap="round"
                                            strokeLinejoin="round"
                                            strokeWidth={2}
                                            d="M13 10V3L4 14h7v7l9-11h-7z"
                                        />
                                    </svg>
                                    <span>创建项目</span>
                                </>
                            )}
                        </button>
                    </div>

                    {uploadProgress && (
                        <div className="animate-fade-in">
                            <div className="flex justify-between text-xs text-[--color-text-muted] mb-1">
                                <span>上传进度</span>
                                <span>{uploadProgress.percent}%</span>
                            </div>
                            <div className="h-2 rounded-full bg-[--color-bg-elevated] overflow-hidden">
                                <div
                                    className="h-full bg-gradient-to-r from-[--color-primary] to-[--color-accent] transition-all duration-300"
                                    style={{ width: `${uploadProgress.percent}%` }}
                                />
                            </div>
                        </div>
                    )}
                </div>
            </form>

            <div className="mt-6 p-4 rounded-xl bg-[--color-bg-card] border border-[--color-border] animate-slide-up" style={{ animationDelay: '300ms' }}>
                <h3 className="text-sm font-medium text-[--color-text-secondary] mb-2 flex items-center gap-2">
                    <svg className="w-4 h-4 text-[--color-primary-light]" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13 16h-1v-4h-1m1-4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
                    </svg>
                    提示
                </h3>
                <ul className="text-sm text-[--color-text-muted] space-y-1">
                    <li>• 如果服务器与浏览器不在同一台机器，请使用服务器上的本地路径</li>
                    <li>• 支持自动检测源语言，但指定可提高识别准确率</li>
                    <li>• 处理时间取决于视频长度，一般 1 小时视频约需 10-20 分钟</li>
                </ul>
            </div>
        </div>
    )
}

