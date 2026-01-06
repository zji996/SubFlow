import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

// https://vite.dev/config/
export default defineConfig({
    plugins: [react(), tailwindcss()],
    server: {
        port: 3000,
        proxy: {
            '/projects': {
                target: 'http://localhost:8100',
                changeOrigin: true,
            },
            '/health': {
                target: 'http://localhost:8100',
                changeOrigin: true,
            },
        },
    },
})
