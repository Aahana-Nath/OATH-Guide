// Defaults for the Settings panel. Never returns the API key itself.
export default defineEventHandler(() => {
  const env = readEnvFile()
  return {
    model: env.GEMINI_MODEL || '',
    keySource: env.GEMINI_API_KEY ? '.env' : 'none',
    firecrawl: !!(env.FIRECRAWL_API_KEY || process.env.FIRECRAWL_API_KEY)
  }
})
