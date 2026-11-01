export default defineEventHandler(async (event) => {
  const key = String(getQuery(event).key || '')
  const data = await loadGuide(key)
  if (!data) throw createError({ statusCode: 404, statusMessage: 'Guide not found' })
  return data
})
