import { existsSync, readFileSync, readdirSync, statSync } from 'node:fs'
import { join, resolve } from 'node:path'

// The Nuxt app lives in <project>/nuxt-app; the Python agent and guides live one level up.
export const ROOT = process.env.OAUTH_AGENT_ROOT ? resolve(process.env.OAUTH_AGENT_ROOT) : resolve(process.cwd(), '..')
export const AGENT = join(ROOT, 'agent', 'guide_agent.py')
export const PYTHON = existsSync(join(ROOT, '.venv', 'bin', 'python')) ? join(ROOT, '.venv', 'bin', 'python') : 'python3'
// Saved guides (guides/) are bundled into the server build as assets, so they ship with any deployment, including ones that only
// upload nuxt-app/. Guides generated while the app runs are written to out/ on disk and read from there.
const GUIDE_DIRS = ['guides', 'out']
const bundled = () => useStorage('assets:guides')

// The research route runs one agent at a time.
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
  website: string
  summary: string
  approval: string
  mode: string
  model: string
  generated_at: string
  start: string
  public: string
  tested: number
  claims: number
  retested: { ok: number; checked: number } | null
  mtime: number
}

function readJson(path: string) {
  try {
    return JSON.parse(readFileSync(path, 'utf8'))
  } catch {
    return null
  }
}

async function listNames(dir: string): Promise<string[]> {
  if (dir === 'guides') return (await bundled().getKeys()).map((k) => k.replace(/^.*:/, ''))
  const full = join(ROOT, dir)
  return existsSync(full) ? readdirSync(full) : []
}

async function readFrom(dir: string, file: string) {
  if (dir !== 'guides') return readJson(join(ROOT, dir, file))
  const raw = await bundled().getItem(file)
  if (raw == null) return null
  if (typeof raw === 'string') {
    try { return JSON.parse(raw) } catch { return null }
  }
  return raw as any
}

// Count claims (objects with a label, a date and text) and how many are "tested".
function countClaims(node: any, acc = { total: 0, tested: 0 }) {
  if (Array.isArray(node)) node.forEach((n) => countClaims(n, acc))
  else if (node && typeof node === 'object') {
    if (node.label && node.checked_at && node.text) {
      acc.total++
      if (node.label === 'tested') acc.tested++
    } else Object.values(node).forEach((v) => countClaims(v, acc))
  }
  return acc
}

// Every guide JSON (trace and schema files excluded).
export async function scanGuides(): Promise<GuideEntry[]> {
  const found: GuideEntry[] = []
  for (const dir of GUIDE_DIRS) {
    for (const f of await listNames(dir)) {
      if (!f.endsWith('.json') || f.endsWith('.trace.json') || f.endsWith('.schema.json')) continue
      const g = await readFrom(dir, f)
      if (!g || !g.provider || !g.difficulty) continue
      const stem = f.replace(/\.json$/, '')
      const { provider, evidence, ...body } = g
      const c = countClaims(body)
      const sc = (await readFrom(dir, `${stem}.trace.json`))?.savecheck
      found.push({
        key: `${dir}/${stem}`,
        dir,
        stem,
        name: g.provider.name,
        website: g.provider.website,
        summary: g.summary || '',
        approval: g.time?.to_approval?.display || '',
        mode: g.generated_by?.mode || 'agent',
        model: g.generated_by?.model || '',
        generated_at: g.generated_at,
        start: g.difficulty.start.level,
        public: g.difficulty.public.level,
        tested: c.tested,
        claims: c.total,
        retested: sc ? { ok: sc.ok, checked: sc.checked } : null,
        // generated guides use the file time; bundled ones have none, so use the date they were generated
        mtime: dir === 'guides' ? Date.parse(g.generated_at) || 0 : statSync(join(ROOT, dir, f)).mtimeMs
      })
    }
  }
  return found
}

// Saved-guide list: one entry per provider and source (hand-written vs agent), newest run wins.
export async function listGuides(): Promise<GuideEntry[]> {
  const best = new Map<string, GuideEntry>()
  for (const g of await scanGuides()) {
    const id = `${g.name.toLowerCase()}|${g.mode === 'agent' ? 'agent' : 'manual'}`
    const cur = best.get(id)
    if (!cur || g.mtime > cur.mtime) best.set(id, g)
  }
  return [...best.values()].sort((a, b) => a.name.localeCompare(b.name) || a.mode.localeCompare(b.mode))
}

export async function loadGuide(key: string) {
  const entry = (await scanGuides()).find((g) => g.key === key) // whitelist: only files we listed, so no path traversal
  if (!entry) return null
  const file = (name: string) => `${entry.stem}${name}.json`
  return {
    entry,
    guide: await readFrom(entry.dir, file('')),
    trace: await readFrom(entry.dir, file('.trace'))
  }
}
