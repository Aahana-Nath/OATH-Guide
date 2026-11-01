// Defaults for the Settings panel. Never returns an API key itself.
// Real environment variables (Vercel, Docker, a shell) win over the local .env file.
export default defineEventHandler(() => {
  const file = readEnvFile()
  const get = (k: string) => process.env[k] || file[k] || ''
  return {
    model: get('GEMINI_MODEL'),
    keySource: process.env.GEMINI_API_KEY ? 'environment variable' : file.GEMINI_API_KEY ? '.env' : 'none',
    firecrawl: !!get('FIRECRAWL_API_KEY')
  }
})
