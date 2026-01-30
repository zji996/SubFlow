import { Select } from '../common/Select'

const languages = [
    { code: 'zh', name: '中文', flag: '🇨🇳' },
    { code: 'en', name: 'English', flag: '🇺🇸' },
    { code: 'ja', name: '日本語', flag: '🇯🇵' },
    { code: 'ko', name: '한국어', flag: '🇰🇷' },
    { code: 'es', name: 'Español', flag: '🇪🇸' },
    { code: 'fr', name: 'Français', flag: '🇫🇷' },
    { code: 'de', name: 'Deutsch', flag: '🇩🇪' },
    { code: 'ru', name: 'Русский', flag: '🇷🇺' },
    { code: 'pt', name: 'Português', flag: '🇵🇹' },
    { code: 'it', name: 'Italiano', flag: '🇮🇹' },
]

export interface LanguageSelectorProps {
    sourceLanguage: string
    targetLanguage: string
    disabled?: boolean
    onSourceLanguageChange: (value: string) => void
    onTargetLanguageChange: (value: string) => void
}

export function LanguageSelector({
    sourceLanguage,
    targetLanguage,
    disabled,
    onSourceLanguageChange,
    onTargetLanguageChange,
}: LanguageSelectorProps) {
    const languageOptions = languages.map((l) => ({ value: l.code, label: l.name, icon: l.flag }))
    const sourceOptions = [{ value: '', label: '自动识别', icon: '🔍' }, ...languageOptions]

    return (
        <div className="grid grid-cols-2 gap-4 animate-slide-up" style={{ animationDelay: '200ms' }}>
            <div>
                <label htmlFor="sourceLanguage" className="label">
                    源语言
                </label>
                <Select
                    value={sourceLanguage}
                    onChange={onSourceLanguageChange}
                    options={sourceOptions}
                    placeholder="自动识别"
                    disabled={disabled}
                    searchable
                />
            </div>
            <div>
                <label htmlFor="targetLanguage" className="label">
                    目标语言
                </label>
                <Select
                    value={targetLanguage}
                    onChange={onTargetLanguageChange}
                    options={languageOptions}
                    disabled={disabled}
                    searchable
                />
            </div>
        </div>
    )
}
