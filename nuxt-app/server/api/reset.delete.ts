import { existsSync, readdirSync, unlinkSync } from 'node:fs'
import { join } from 'node:path'

// Removes everything the agent has stored: the generated guides and their traces in out/.
// The hand-researched guides in guides/ are never touched.
export default defineEventHandler(() => {
  if (runState.running) throw createError({ statusCode: 409, statusMessage: 'Wait for the current run to finish before resetting.' })
  const dir = join(ROOT, 'out')
  let deleted = 0
  if (existsSync(dir)) {
    for (const f of readdirSync(dir)) {
      if (!f.endsWith('.json')) continue
      unlinkSync(join(dir, f))
      deleted++
    }
  }
  return { deleted }
})
