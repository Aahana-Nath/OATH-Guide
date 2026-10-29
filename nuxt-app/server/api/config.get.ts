// Defaults for the Settings panel. Never returns the API key itself.
export default defineEventHandler(() => {
  const env = readEnvFile()
  return {
    model: env.GEMINI_MODEL || '',
    keySource: env.GCP_PROJECT_ID ? 'Secret Manager' : env.GEMINI_API_KEY ? '.env' : 'none'
  }
})
