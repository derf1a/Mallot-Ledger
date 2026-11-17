import { execSync } from 'node:child_process'
import { readFileSync } from 'node:fs'
import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

const pkg = JSON.parse(readFileSync(new URL('./package.json', import.meta.url), 'utf8')) as { version: string }
let gitSha = 'dev'
try {
  gitSha = execSync('git rev-parse --short HEAD', { stdio: ['ignore', 'pipe', 'ignore'] }).toString().trim()
} catch {
  /* git 이 없으면 dev */
}

// 경로 접두사 — MLG_BASE_PATH(예: /ledger)가 있으면 그 아래에서 돈다 (한 도메인의 /ledger/). 없으면 루트.
const basePath = (process.env.MLG_BASE_PATH ?? '').trim().replace(/^\/+|\/+$/g, '')
const base = basePath ? `/${basePath}/` : '/'

// https://vite.dev/config/
export default defineConfig({
  base,
  plugins: [react()],
  define: {
    __APP_VERSION__: JSON.stringify(pkg.version),
    __GIT_SHA__: JSON.stringify(gitSha),
  },
  server: {
    host: true,
    proxy: {
      // 접두사가 있으면 /ledger/api 를 보낸다 — 백엔드도 같은 MLG_BASE_PATH 로 떼어 받는다
      [`${base}api`]: `http://localhost:${process.env.BACKEND_PORT ?? 8200}`,
    },
  },
})
