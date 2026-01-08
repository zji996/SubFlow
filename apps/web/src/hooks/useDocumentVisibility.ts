import { useState, useEffect } from 'react'

/**
 * Hook that returns true when the document is visible, false when hidden.
 * Useful for pausing expensive operations (like polling) when user switches tabs.
 */
export function useDocumentVisibility(): boolean {
    const [isVisible, setIsVisible] = useState(() => {
        if (typeof document === 'undefined') return true
        return document.visibilityState === 'visible'
    })

    useEffect(() => {
        const handleVisibilityChange = () => {
            setIsVisible(document.visibilityState === 'visible')
        }

        document.addEventListener('visibilitychange', handleVisibilityChange)
        return () => {
            document.removeEventListener('visibilitychange', handleVisibilityChange)
        }
    }, [])

    return isVisible
}
