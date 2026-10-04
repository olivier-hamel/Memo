import { defineConfig, loadEnv } from 'vite'
import react from '@vitejs/plugin-react'
import { readFileSync, readdirSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { join } from 'node:path'

// Serve PDF.js fonts, CMaps and image decoders locally in dev and production.
function pdfAssets() {
  const directory = fileURLToPath(new URL('./node_modules/pdfjs-dist/', import.meta.url))
  const groups = ['cmaps', 'standard_fonts', 'wasm']
  const assets = new Map<string, string>(groups.flatMap(group => readdirSync(join(directory, group)).map(name =>
    [`/pdf-assets/${group}/${name}`, join(directory, group, name)] as const)))
  return {
    name: 'memo-pdf-assets',
    configureServer(server: import('vite').ViteDevServer) {
      server.middlewares.use((request, response, next) => {
        const path = (request.url || '').split('?')[0]
        const filename = assets.get(path)
        if (!filename) { next(); return }
        response.setHeader('Content-Type', path.endsWith('.wasm') ? 'application/wasm' : 'application/octet-stream')
        response.end(readFileSync(filename))
      })
    },
    generateBundle(this: import('rollup').PluginContext) {
      for (const [path, filename] of assets) this.emitFile({ type: 'asset', fileName: path.slice(1), source: readFileSync(filename) })
    },
  }
}

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, '.', ['VITE_', 'MEMO_'])
  return {
    plugins: [react(), pdfAssets()],
    base: env.VITE_MEMO_BASE || '/',
    server: {
      port: 5173,
      strictPort: true,
      proxy: { '/api': { target: env.MEMO_DEV_API || 'http://127.0.0.1:8000', changeOrigin: false } },
    },
  }
})
