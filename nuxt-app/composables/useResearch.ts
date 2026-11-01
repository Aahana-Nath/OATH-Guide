export const STAGES = ['Find the docs', 'Search & read', 'Verify gaps', 'Judge', 'Build guide']

// Which journey stage a log line belongs to.
const STAGE_OF: Record<string, number> = { discover: 0, crawl: 1, extract: 2, verify: 2, agent: 2, probe: 3, judge: 3, validate: 4, done: 4 }

export interface RunStats { pages: number; claims: number; dropped: number; steps: number }

export function useResearch() {
  const running = useState('research-running', () => false)
  const log = useState<string[]>('research-log', () => [])
  const stage = useState('research-stage', () => -1) // index of the stage in progress; STAGES.length once finished
  const error = useState('research-error', () => '')
  const target = useState('research-target', () => '')
  const startedAt = useState('research-started', () => 0)
  const readyKey = useState('research-ready', () => '') // key of a finished guide the user has not opened yet

  const liveStats = computed<RunStats>(() => {
    const pages = new Set<string>()
    let claims = 0, dropped = 0, steps = 0
    for (const l of log.value) {
      // A page counts once, whichever stage first reads it (crawl, seed page, or an agent fetch).
      const url = /^\[crawl\] (?:read|thin page)|^\[agent\] reading seed page|^\[agent\] step \d+\/\d+ fetch_page\(/.test(l) && l.match(/https?:\/\/[^\s)\]:]+(?::\d+)?[^\s)\]]*/)
      if (url) pages.add(url[0].replace(/[/.]+$/, ''))
      if (/^\[agent\] step /.test(l)) steps++
      const v = l.match(/^\[verify\] (\d+) of (\d+)/)
      if (v) { claims += +v[1]; dropped += +v[2] - +v[1] } // each verify line covers one batch of findings
    }
    return { pages: pages.size, claims, dropped, steps }
  })

  async function start(opts: { target: string; model?: string; maxPages: number; maxSeconds: number; maxSteps: number; probes?: boolean }): Promise<string | null> {
    running.value = true
    startedAt.value = Date.now()
    readyKey.value = ''
    error.value = ''
    log.value = []
    stage.value = 0
    target.value = opts.target
    let key: string | null = null
    try {
      const res = await fetch('/api/research', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(opts)
      })
      if (!res.ok || !res.body) {
        const j = await res.json().catch(() => ({}))
        throw new Error(j.statusMessage || j.message || `Request failed (${res.status})`)
      }
      const reader = res.body.getReader()
      const dec = new TextDecoder()
      let buf = ''
      const handle = (line: string) => {
        if (!line.trim()) return
        const m = JSON.parse(line)
        if (m.type === 'log') {
          log.value = [...log.value, m.line]
          const tag = m.line.match(/^\[(\w+)\]/)?.[1]
          if (tag && tag in STAGE_OF) stage.value = Math.max(stage.value, STAGE_OF[tag])
        } else if (m.type === 'done') {
          key = m.key
          readyKey.value = m.key
          stage.value = STAGES.length
        } else if (m.type === 'error') {
          error.value = m.message
        }
      }
      for (;;) {
        const { value, done } = await reader.read()
        if (done) break
        buf += dec.decode(value, { stream: true })
        const lines = buf.split('\n')
        buf = lines.pop() || ''
        lines.forEach(handle)
      }
      handle(buf)
    } catch (e: any) {
      error.value = e.message || String(e)
    } finally {
      running.value = false
    }
    return key
  }

  return { running, log, stage, error, target, startedAt, readyKey, liveStats, start }
}
