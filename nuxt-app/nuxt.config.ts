import { existsSync, readdirSync } from 'node:fs'
import { fileURLToPath } from 'node:url'

// The saved guides ship inside the server build. Fail the build rather than deploy an empty library.
const guidesDir = fileURLToPath(new URL('../guides', import.meta.url))
if (!existsSync(guidesDir) || !readdirSync(guidesDir).some((f) => f.endsWith('.json'))) {
  throw new Error(
    `Saved guides not found at ${guidesDir}. Build with the repository's guides/ folder next to nuxt-app/ ` +
      '(on Vercel: Project Settings > General > "Include source files outside of the Root Directory in the Build Step").'
  )
}

export default defineNuxtConfig({
  compatibilityDate: '2025-01-01',
  devtools: { enabled: false },
  // The saved guides ship inside the server build (see server/utils/project.ts).
  nitro: { serverAssets: [{ baseName: 'guides', dir: guidesDir }] },
  css: ['~/assets/css/main.css'],
  app: {
    head: {
      title: 'OAuth Guide Agent',
      htmlAttrs: { lang: 'en' },
      meta: [{ name: 'viewport', content: 'width=device-width, initial-scale=1' }],
      link: [
        { rel: 'preconnect', href: 'https://fonts.googleapis.com' },
        { rel: 'preconnect', href: 'https://fonts.gstatic.com', crossorigin: '' },
        {
          rel: 'stylesheet',
          href: 'https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;500&family=Inter:wght@400;500;600;700&family=Press+Start+2P&display=swap'
        }
      ]
    }
  }
})
