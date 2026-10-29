import { existsSync, readFileSync, readdirSync, statSync } from 'node:fs'
import { join, resolve } from 'node:path'

// The Nuxt app lives in <project>/nuxt-app; the Python agent and guides live one level up.
export const ROOT = process.env.OAUTH_AGENT_ROOT ? resolve(process.env.OAUTH_AGENT_ROOT) : resolve(process.cwd(), '..')
export const AGENT = join(ROOT, 'agent', 'guide_agent.py')
export const PYTHON = existsSync(join(ROOT, '.venv', 'bin', 'python')) ? join(ROOT, '.venv', 'bin', 'python') : 'python3'
const GUIDE_DIRS = ['guides', 'out']

// Shared by the research and reset routes: one agent run at a time, and no reset while one is running.
export const runState = { running: false }

export function readEnvFile(): Record<string, string> {
  const out: Record<string, string> = {}
  const p = join(ROOT, '.env')
  if (!existsSync(p)) return out
  for (const line of readFileSync(p, 'utf8').split('\n')) {
    const i = line.indexOf('=')
    if (i > 0 && !line.trim().startsWith('#')) out[line.slice(0, i).trim()] = line.slice(i + 1).trim().replace(/^["']|["']$/g, '')
  }
  return out
}

export interface GuideEntry {
  key: string
  dir: string
  stem: string
  name: string
  mode: string
  model: string
  generated_at: string
  start: string
  public: string
  mtime: number
}

function readJson(path: string) {
  try {
    return JSON.parse(readFileSync(path, 'utf8'))
  } catch {
    return null
  }
}

// Every guide JSON on disk (trace and schema files excluded), newest first within a folder.
export function scanGuides(): GuideEntry[] {
  const found: GuideEntry[] = []
  for (const dir of GUIDE_DIRS) {
    const full = join(ROOT, dir)
    if (!existsSync(full)) continue
    for (const f of readdirSync(full)) {
      if (!f.endsWith('.json') || f.endsWith('.trace.json') || f.endsWith('.schema.json')) continue
      const path = join(full, f)
      const g = readJson(path)
      if (!g || !g.provider || !g.difficulty) continue
      const stem = f.replace(/\.json$/, '')
      found.push({
        key: `${dir}/${stem}`,
        dir,
        stem,
        name: g.provider.name,
        mode: g.generated_by?.mode || 'agent',
        model: g.generated_by?.model || '',
        generated_at: g.generated_at,
        start: g.difficulty.start.level,
        public: g.difficulty.public.level,
        mtime: statSync(path).mtimeMs
      })
    }
  }
  return found
}

// Saved-guide list: one entry per provider and source (hand-written vs agent), newest run wins.
export function listGuides(): GuideEntry[] {
  const best = new Map<string, GuideEntry>()
  for (const g of scanGuides()) {
    const id = `${g.name.toLowerCase()}|${g.mode === 'agent' ? 'agent' : 'manual'}`
    const cur = best.get(id)
    if (!cur || g.mtime > cur.mtime) best.set(id, g)
  }
  return [...best.values()].sort((a, b) => a.name.localeCompare(b.name) || a.mode.localeCompare(b.mode))
}

export function loadGuide(key: string) {
  const entry = scanGuides().find((g) => g.key === key) // whitelist: only files we listed, so no path traversal
  if (!entry) return null
  const base = join(ROOT, entry.dir, entry.stem)
  return {
    entry,
    guide: readJson(`${base}.json`),
    trace: existsSync(`${base}.trace.json`) ? readJson(`${base}.trace.json`) : null
  }
}
