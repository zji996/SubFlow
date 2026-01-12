import { useState, useRef, useEffect } from 'react'
import { createPortal } from 'react-dom'

export interface SelectOption {
    value: string
    label: string
    icon?: string
}

interface SelectProps {
    value: string
    onChange: (value: string) => void
    options: SelectOption[]
    placeholder?: string
    disabled?: boolean
    className?: string
    searchable?: boolean
}

export function Select({
    value,
    onChange,
    options,
    placeholder = '请选择',
    disabled = false,
    className = '',
    searchable = false
}: SelectProps) {
    const [isOpen, setIsOpen] = useState(false)
    const [searchTerm, setSearchTerm] = useState('')
    const containerRef = useRef<HTMLDivElement>(null)
    const dropdownRef = useRef<HTMLDivElement>(null)
    const [dropdownStyle, setDropdownStyle] = useState<React.CSSProperties>({})

    const selectedOption = options.find(opt => opt.value === value)

    const filteredOptions = searchable && searchTerm
        ? options.filter(opt => opt.label.toLowerCase().includes(searchTerm.toLowerCase()))
        : options

    useEffect(() => {
        const handleClickOutside = (event: MouseEvent) => {
            if (containerRef.current && !containerRef.current.contains(event.target as Node) &&
                dropdownRef.current && !dropdownRef.current.contains(event.target as Node)) {
                setIsOpen(false)
            }
        }

        document.addEventListener('mousedown', handleClickOutside)
        return () => document.removeEventListener('mousedown', handleClickOutside)
    }, [])

    useEffect(() => {
        if (isOpen && containerRef.current) {
            const rect = containerRef.current.getBoundingClientRect()
            const spaceBelow = window.innerHeight - rect.bottom
            const spaceAbove = rect.top
            const dropdownHeight = Math.min(filteredOptions.length * 40 + (searchable ? 50 : 0), 300)

            const showBelow = spaceBelow >= dropdownHeight || spaceBelow > spaceAbove



            setDropdownStyle({
                position: 'fixed',
                top: showBelow ? rect.bottom + 8 : 'auto',
                bottom: showBelow ? 'auto' : window.innerHeight - rect.top + 8,
                left: rect.left,
                width: rect.width,
                zIndex: 9999
            })

            // Focus search input if searchable
            if (searchable) {
                setTimeout(() => {
                    const input = document.getElementById('select-search-input')
                    if (input) input.focus()
                }, 50)
            }
        }
    }, [isOpen, filteredOptions.length, searchable])

    // Close on escape
    useEffect(() => {
        const handleEscape = (e: KeyboardEvent) => {
            if (e.key === 'Escape') setIsOpen(false)
        }
        if (isOpen) {
            document.addEventListener('keydown', handleEscape)
            return () => document.removeEventListener('keydown', handleEscape)
        }
    }, [isOpen])

    return (
        <div ref={containerRef} className={`relative ${className}`}>
            <button
                type="button"
                onClick={() => !disabled && setIsOpen(!isOpen)}
                disabled={disabled}
                className={`
                    w-full flex items-center justify-between px-4 py-3.5 
                    rounded-xl border transition-all duration-200
                    text-left text-[0.9375rem]
                    ${disabled
                        ? 'bg-[--color-bg-input] opacity-60 cursor-not-allowed border-[--color-border]'
                        : isOpen
                            ? 'bg-[rgba(15,23,42,0.8)] border-[--color-primary] shadow-[0_0_0_3px_rgba(99,102,241,0.15)]'
                            : 'bg-[rgba(15,23,42,0.6)] border-[--color-border] hover:border-[--color-border-light]'
                    }
                `}
            >
                <div className="flex items-center gap-2 truncate">
                    {selectedOption?.icon && (
                        <span className="text-lg">{selectedOption.icon}</span>
                    )}
                    <span className={selectedOption ? 'text-[--color-text]' : 'text-[--color-text-dim]'}>
                        {selectedOption ? selectedOption.label : placeholder}
                    </span>
                </div>
                <svg
                    className={`w-4 h-4 text-[--color-text-muted] transition-transform duration-200 ${isOpen ? 'rotate-180' : ''}`}
                    fill="none"
                    stroke="currentColor"
                    viewBox="0 0 24 24"
                >
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
                </svg>
            </button>

            {isOpen && createPortal(
                <div
                    ref={dropdownRef}
                    style={dropdownStyle}
                    className="animate-scale-in overflow-hidden rounded-xl border border-[--color-border-light] bg-[--color-bg-elevated] shadow-xl backdrop-blur-xl"
                >
                    {searchable && (
                        <div className="p-2 border-b border-[--color-border]">
                            <input
                                id="select-search-input"
                                type="text"
                                className="w-full px-3 py-2 bg-[--color-bg-input] rounded-lg text-sm border border-[--color-border] focus:outline-none focus:border-[--color-primary]"
                                placeholder="搜索..."
                                value={searchTerm}
                                onChange={(e) => setSearchTerm(e.target.value)}
                                onClick={(e) => e.stopPropagation()}
                            />
                        </div>
                    )}

                    <div className="max-h-[240px] overflow-y-auto py-1 custom-scrollbar">
                        {filteredOptions.length > 0 ? (
                            filteredOptions.map((option) => (
                                <button
                                    key={option.value}
                                    type="button"
                                    onClick={() => {
                                        onChange(option.value)
                                        setIsOpen(false)
                                        setSearchTerm('')
                                    }}
                                    className={`
                                        w-full flex items-center gap-2 px-4 py-2.5 text-sm transition-colors
                                        ${value === option.value
                                            ? 'bg-[--color-primary]/10 text-[--color-primary-light] font-medium'
                                            : 'text-[--color-text-secondary] hover:bg-[--color-bg-hover] hover:text-[--color-text]'
                                        }
                                    `}
                                >
                                    {option.icon && (
                                        <span className="text-lg">{option.icon}</span>
                                    )}
                                    <span>{option.label}</span>
                                    {value === option.value && (
                                        <svg className="w-4 h-4 ml-auto" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
                                        </svg>
                                    )}
                                </button>
                            ))
                        ) : (
                            <div className="px-4 py-3 text-sm text-[--color-text-dim] text-center">
                                无匹配选项
                            </div>
                        )}
                    </div>
                </div>,
                document.body
            )}
        </div>
    )
}
