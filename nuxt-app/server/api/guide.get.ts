export default defineEventHandler((event) => {
  const key = String(getQuery(event).key || '')
  const data = loadGuide(key)
  if (!data) throw createError({ statusCode: 404, statusMessage: 'Guide not found' })
  return data
})
