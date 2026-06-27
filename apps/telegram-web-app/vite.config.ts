import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    // Allow access through tunnels (serveo, etc.) whose subdomain rotates each
    // session. A leading dot allows all subdomains of the base domain.
    // Set to `true` to allow any host (e.g. when using other tunnel providers).
    allowedHosts: ['.serveousercontent.com'],
  }
})
