<script setup lang="ts">
// The big animated "watch the agents work" scene: a pixel-art canvas (stations, a walking robot, data packets)
// plus agent cards, live counters and a streaming terminal. Driven entirely by the research state.
const { log, stage, target, startedAt, liveStats } = useResearch()

const AGENTS = [
  { face: '🔭', name: 'Scout', job: 'Finds the developer docs', color: '#5b8cff' },
  { face: '📖', name: 'Reader', job: 'Reads pages and picks the next link', color: '#a78bfa' },
  { face: '✅', name: 'Verifier', job: 'Checks every quote, runs live checks', color: '#34d399' },
  { face: '⚖️', name: 'Judge', job: 'Rates difficulty and the wait', color: '#fbbf24' },
  { face: '✍️', name: 'Writer', job: 'Assembles the guide', color: '#f472b6' }
]
const state = (i: number) => (stage.value > i ? 'done' : stage.value === i ? 'active' : 'idle')
const finished = computed(() => stage.value >= AGENTS.length)

// ---------- pixel scene ----------
const W = 200
const H = 75
const STATION_X = [20, 60, 100, 140, 180]
const ICONS: string[][] = [
  ['...#####...', '..#.....#..', '.#.......#.', '.#.......#.', '.#.......#.', '.#.......#.', '..#.....#..', '...#####...', '........##.', '.........##', '..........#'],
  ['###########', '#....#....#', '#.##.#.##.#', '#....#....#', '#.##.#.##.#', '#....#....#', '#.##.#.##.#', '#....#....#', '###########', '...#####...', '...........'],
  ['###########', '#.........#', '#.......#.#', '#......##.#', '#.#...##..#', '#.##.##...#', '#..###....#', '#...#.....#', '#.........#', '###########', '...........'],
  ['.....#.....', '###########', '#....#....#', '#....#....#', '#....#....#', '###..#..###', '.#...#...#.', '....###....', '....###....', '...#####...', '..#######..'],
  ['..#######..', '..#.....##.', '..#.###.#.#', '..#.....###', '..#.###..#.', '..#.....#..', '..#.###.#..', '..#.....#..', '..#.###.#..', '..#######..', '...........']
]
const ROBOT = ['....a....', '....#....', '.#######.', '#.#e#e#.#', '#.#####.#', '.#######.', '..#####..']
const LEGS_A = ['..#...#..', '..#...#..', '.##...##.']
const LEGS_B = ['...#.#...', '...#.#...', '..##.##..']

const canvas = ref<HTMLCanvasElement | null>(null)
let raf = 0
let last = 0
let t = 0
let robotX = STATION_X[0]
const confetti: { x: number; y: number; c: string; v: number }[] = []

function bitmap(ctx: CanvasRenderingContext2D, rows: string[], x: number, y: number, scale: number, colors: Record<string, string>) {
  rows.forEach((row, ry) => {
    for (let rx = 0; rx < row.length; rx++) {
      const c = colors[row[rx]]
      if (c) { ctx.fillStyle = c; ctx.fillRect(x + rx * scale, y + ry * scale, scale, scale) }
    }
  })
}

function draw() {
  const ctx = canvas.value?.getContext('2d')
  if (!ctx) return
  const s = stage.value
  const active = Math.min(Math.max(s, 0), AGENTS.length - 1)

  // background, grid and twinkling stars
  ctx.fillStyle = '#060a18'; ctx.fillRect(0, 0, W, H)
  ctx.fillStyle = 'rgba(91,140,255,0.07)'
  for (let x = 0; x < W; x += 10) ctx.fillRect(x, 0, 1, H)
  for (let y = 0; y < H; y += 10) ctx.fillRect(0, y, W, 1)
  for (let i = 0; i < 26; i++) {
    const sx = (i * 53) % W, sy = (i * 29) % 36
    if ((t + i * 3) % 14 < 8) { ctx.fillStyle = '#9fb4ff'; ctx.fillRect(sx, sy, 1, 1) }
  }

  // path
  const pathY = 63
  ctx.fillStyle = '#1d2749'
  for (let x = 6; x < W - 6; x += 4) ctx.fillRect(x, pathY, 2, 1)
  const progressX = s >= AGENTS.length ? W - 6 : STATION_X[active]
  ctx.fillStyle = '#36c47f'
  for (let x = 6; x < progressX; x += 4) ctx.fillRect(x, pathY, 2, 1)

  // stations
  STATION_X.forEach((x, i) => {
    const st = s > i ? 'done' : s === i ? 'active' : 'idle'
    const col = AGENTS[i].color
    const pulse = st === 'active' ? (Math.sin(t / 3) + 1) / 2 : 0
    ctx.fillStyle = st === 'done' ? '#0d2b20' : st === 'active' ? '#142456' : '#0c1230'
    ctx.fillRect(x - 14, 17, 28, 34)
    ctx.fillStyle = st === 'done' ? '#36c47f' : st === 'active' ? col : '#2d3a6b'
    ctx.fillRect(x - 14, 17, 28, 1); ctx.fillRect(x - 14, 50, 28, 1); ctx.fillRect(x - 14, 17, 1, 34); ctx.fillRect(x + 13, 17, 1, 34)
    if (st === 'active') {
      ctx.globalAlpha = 0.15 + pulse * 0.25; ctx.fillStyle = col; ctx.fillRect(x - 16, 15, 32, 38); ctx.globalAlpha = 1
    }
    bitmap(ctx, ICONS[i], x - 11, 23, 2, { '#': st === 'idle' ? '#3a4880' : st === 'done' ? '#6af0a8' : col })
    ctx.fillStyle = '#1d2749'; ctx.fillRect(x - 15, 52, 30, 2)
    if (st === 'done') { // check badge
      ctx.fillStyle = '#36c47f'; ctx.fillRect(x + 8, 12, 9, 9)
      ctx.fillStyle = '#04120b'; ctx.fillRect(x + 10, 17, 1, 1); ctx.fillRect(x + 11, 18, 1, 1); ctx.fillRect(x + 12, 17, 1, 1); ctx.fillRect(x + 13, 16, 1, 1); ctx.fillRect(x + 14, 15, 1, 1)
    }
  })

  // data packets flowing toward the active station
  if (s > 0 && s < AGENTS.length) {
    const from = STATION_X[s - 1], to = STATION_X[s]
    for (let k = 0; k < 3; k++) {
      const p = ((t * 1.2 + k * 14) % 42) / 42
      ctx.fillStyle = AGENTS[s].color; ctx.fillRect(from + (to - from) * p, pathY - 4, 3, 3)
    }
  }

  // robot walks to the active station and works there
  const targetX = s >= AGENTS.length ? W / 2 : STATION_X[active]
  const walking = Math.abs(robotX - targetX) > 1
  robotX += Math.sign(targetX - robotX) * Math.min(1.6, Math.abs(targetX - robotX))
  const bob = walking ? (t % 4 < 2 ? 0 : -1) : (t % 6 < 3 ? 0 : -1)
  const legs = walking && t % 4 < 2 ? LEGS_B : LEGS_A
  const body = s >= AGENTS.length ? '#6af0a8' : AGENTS[active].color
  const ry = 41 + bob
  bitmap(ctx, [...ROBOT, ...legs], Math.round(robotX) - 9, ry, 2, { '#': body, e: '#ffffff', a: '#ffd84d' })
  if (!walking && s < AGENTS.length) { // sparks while working
    for (let i = 0; i < 4; i++) {
      const px = STATION_X[active] - 10 + ((t * 3 + i * 7) % 22), py = 14 - ((t + i * 5) % 12)
      ctx.fillStyle = i % 2 ? '#ffd84d' : '#ffffff'; ctx.fillRect(px, Math.max(2, py), 1, 1)
    }
  }

  // confetti when done
  if (s >= AGENTS.length) {
    if (confetti.length < 70 && t % 2 === 0) confetti.push({ x: Math.random() * W, y: -2, c: ['#ffd84d', '#5b8cff', '#34d399', '#f472b6', '#fff'][Math.floor(Math.random() * 5)], v: 0.6 + Math.random() })
    confetti.forEach((c) => { c.y += c.v; ctx.fillStyle = c.c; ctx.fillRect(c.x, c.y, 2, 2) })
    for (let i = confetti.length - 1; i >= 0; i--) if (confetti[i].y > H) confetti.splice(i, 1)
  }
}

function frame(ts: number) {
  raf = requestAnimationFrame(frame)
  if (ts - last < 66) return // ~15 fps keeps the chunky, retro feel
  last = ts
  t++
  draw()
}

// ---------- timer and terminal ----------
const now = ref(Date.now())
let timer: ReturnType<typeof setInterval> | undefined
const elapsed = computed(() => {
  const s = Math.max(0, Math.floor((now.value - startedAt.value) / 1000))
  return `${String(Math.floor(s / 60)).padStart(2, '0')}:${String(s % 60).padStart(2, '0')}`
})
const lines = computed(() => log.value.slice(-8))
const status = computed(() => (stage.value >= 0 && stage.value < AGENTS.length ? AGENTS[stage.value].name : 'Scout'))

onMounted(() => {
  draw()
  timer = setInterval(() => (now.value = Date.now()), 1000)
  if (!window.matchMedia('(prefers-reduced-motion: reduce)').matches) raf = requestAnimationFrame(frame)
})
onBeforeUnmount(() => { cancelAnimationFrame(raf); if (timer) clearInterval(timer) })
</script>

<template>
  <section class="aaw" aria-label="The agents are working">
    <div class="aaw-head">
      <div>
        <p class="eyebrow">Live research</p>
        <h2>Watch the agents work</h2>
        <p class="tgt">{{ target }}</p>
      </div>
      <div class="time" aria-label="Elapsed time">{{ elapsed }}</div>
    </div>

    <div class="scene"><canvas ref="canvas" :width="W" :height="H" aria-hidden="true" /></div>

    <div class="agents">
      <div v-for="(a, i) in AGENTS" :key="a.name" class="agent" :class="state(i)">
        <span class="face">{{ a.face }}</span>
        <span class="nm">{{ a.name }}</span>
        <span class="job">{{ a.job }}</span>
        <span class="st">{{ state(i) === 'done' ? '✓ Done' : state(i) === 'active' ? 'Working…' : 'Waiting' }}</span>
      </div>
    </div>

    <div class="counters">
      <div class="counter"><span>Pages read</span><b>{{ liveStats.pages }}</b></div>
      <div class="counter"><span>Claims quoted</span><b>{{ liveStats.claims }}</b></div>
      <div class="counter"><span>Dropped</span><b>{{ liveStats.dropped }}</b></div>
      <div class="counter"><span>Agent steps</span><b>{{ liveStats.steps }}</b></div>
    </div>

    <div class="terminal" aria-hidden="true">
      <p v-for="(l, i) in lines" :key="`${log.length}-${i}`">&gt; {{ l }}</p>
      <p v-if="!lines.length">&gt; waking the agents…</p>
      <p><span class="cursor">█</span></p>
    </div>
    <p class="sr" role="status">{{ finished ? 'Finished' : `${status} is working on ${target}` }}</p>
  </section>
</template>
