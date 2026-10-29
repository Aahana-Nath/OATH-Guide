import { spawn } from 'node:child_process'
import { existsSync, mkdirSync } from 'node:fs'
import { join } from 'node:path'
import { PassThrough } from 'node:stream'

// Optional public-hosting protection: minimum seconds between runs from the same IP (0 = off).
const COOLDOWN_MS = Math.max(0, Number(process.env.RESEARCH_COOLDOWN_SECONDS || 0)) * 1000
const lastRunByIp = new Map<string, number>()

const clamp = (v: unknown, lo: number, hi: number, d: number) => {
  const n = Math.trunc(Number(v))
  return Number.isFinite(n) ? Math.min(hi, Math.max(lo, n)) : d
}

export default defineEventHandler(async (event) => {
  const body = await readBody(event)
  const target = String(body?.target || '').trim()
  const model = String(body?.model || '').trim()

  // Spawned without a shell, but still reject anything that could be read as an option or is not a site/app name.
  if (!target || target.length > 200 || target.startsWith('-') || !/^[\w .:/?=&%#@~+-]+$/.test(target)) {
    throw createError({ statusCode: 400, statusMessage: 'Enter an app name or website.' })
  }
  if (model && !/^[\w.-]+$/.test(model)) throw createError({ statusCode: 400, statusMessage: 'Invalid model name.' })
  if (runState.running) throw createError({ statusCode: 409, statusMessage: 'A run is already in progress.' })
  if (COOLDOWN_MS) {
    const ip = getRequestIP(event, { xForwardedFor: true }) || 'unknown'
    const wait = Math.ceil(((lastRunByIp.get(ip) || 0) + COOLDOWN_MS - Date.now()) / 1000)
    if (wait > 0) throw createError({ statusCode: 429, statusMessage: `Please wait ${wait}s before starting another run.` })
    lastRunByIp.set(ip, Date.now())
  }

  const slug =
    target.toLowerCase().replace(/^https?:\/\//, '').replace(/[^a-z0-9]+/g, '-').replace(/^-+|-+$/g, '') || 'guide'
  const outDir = join(ROOT, 'out')
  if (!existsSync(outDir)) mkdirSync(outDir, { recursive: true })

  const args = [
    AGENT,
    '--out', join(outDir, `${slug}.json`),
    '--trace', join(outDir, `${slug}.trace.json`),
    '--max-pages', String(clamp(body?.maxPages, 3, 40, 20)),
    '--max-seconds', String(clamp(body?.maxSeconds, 30, 600, 300)),
    '--max-steps', String(clamp(body?.maxSteps, 0, 20, 10))
  ]
  if (model) args.push('--model', model)
  if (body?.probes === false) args.push('--no-probes')
  args.push('--', target)

  const out = new PassThrough()
  const send = (msg: Record<string, unknown>) => out.writable && out.write(JSON.stringify(msg) + '\n')

  runState.running = true
  const child = spawn(PYTHON, args, { cwd: ROOT, env: { ...process.env, PYTHONUNBUFFERED: '1' } })
  let buf = ''
  let lastLine = ''
  child.stderr.on('data', (d: Buffer) => {
    buf += d.toString()
    const lines = buf.split('\n')
    buf = lines.pop() || ''
    lines.filter(Boolean).forEach((line) => { lastLine = line; send({ type: 'log', line }) })
  })
  child.on('error', (e) => send({ type: 'error', message: `Could not start the agent: ${e.message}` }))
  child.on('close', (code) => {
    runState.running = false
    if (buf.trim()) { lastLine = buf.trim(); send({ type: 'log', line: buf.trim() }) }
    const ok = (code === 0 || code === 2) && existsSync(join(outDir, `${slug}.json`))
    // The agent exits with a plain-language reason for refusals (private address, missing key); pass that on.
    const reason = /^(Refused|No Gemini API key)/.test(lastLine) ? lastLine : `The agent stopped with exit code ${code}.`
    send(ok ? { type: 'done', code, key: `out/${slug}` } : { type: 'error', message: reason })
    out.end()
  })
  // Client left before the run finished: stop the agent so it does not keep spending model calls.
  event.node.res.on('close', () => {
    if (!event.node.res.writableEnded && child.exitCode === null) child.kill()
  })

  setResponseHeader(event, 'Content-Type', 'application/x-ndjson; charset=utf-8')
  setResponseHeader(event, 'Cache-Control', 'no-cache')
  return sendStream(event, out)
})
