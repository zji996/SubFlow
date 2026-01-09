import { defineConfig, loadEnv } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

// https://vite.dev/config/
export default defineConfig(({ mode }) => {
    const env = loadEnv(mode, process.cwd(), '')
    const apiTarget = env.VITE_API_TARGET || 'http://localhost:8100'

    return {
        plugins: [react(), tailwindcss()],
        server: {
            port: 5173,
            proxy: {
                // All API requests go through /api prefix
                '/api': {
                    target: apiTarget,
                    changeOrigin: true,
                    rewrite: (path) => path.replace(/^\/api/, ''),
                },
            },
        },
    }
})
