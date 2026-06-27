import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// vault-server (backend) origin the dev server proxies API calls to.
const API_TARGET = process.env.VITE_API_TARGET || 'http://localhost:8000'

// Backend route prefixes the web app calls. Proxied through the Vite dev server
// so a single tunnel (e.g. serveo) reaches both the app and the API — the phone
// never needs to resolve the dev machine's localhost. The client uses relative
// URLs (see src/services/api.ts), so these requests land here and get forwarded.
const API_PREFIXES = ['/notes', '/events', '/daily', '/tokens', '/health', '/generate', '/imagery', '/media']

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    // Allow access through tunnels (serveo, etc.) whose subdomain rotates each
    // session. A leading dot allows all subdomains of the base domain.
    // Set to `true` to allow any host (e.g. when using other tunnel providers).
    allowedHosts: ['.serveousercontent.com'],
    proxy: Object.fromEntries(
      API_PREFIXES.map((p) => [p, { target: API_TARGET, changeOrigin: true }]),
    ),
  },
})
