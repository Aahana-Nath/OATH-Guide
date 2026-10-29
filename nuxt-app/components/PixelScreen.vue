<script setup lang="ts">
// Big retro screen shown in place of the guide while the agent works.
const { log, stage, target } = useResearch()

const W = 96
const H = 54
const canvas = ref<HTMLCanvasElement | null>(null)
const PALETTE = [[7, 12, 28], [11, 26, 48], [15, 50, 68], [22, 88, 98]]
let raf = 0
let last = 0
let t = 0

function paint() {
  const ctx = canvas.value?.getContext('2d')
  if (!ctx) return
  const img = ctx.createImageData(W, H)
  const sweep = t % (H + 12) // a bright row travelling down, like a scan line
  for (let y = 0; y < H; y++) {
    for (let x = 0; x < W; x++) {
      const v = Math.sin(x * 0.18 + t * 0.15) + Math.sin(y * 0.25 - t * 0.1) + Math.sin((x + y) * 0.12 + t * 0.07)
      let lvl = Math.min(3, Math.max(0, Math.floor(((v + 3) / 6) * 4)))
      if (y === sweep) lvl = Math.min(3, lvl + 1)
      const [r, g, b] = PALETTE[lvl]
      const i = (y * W + x) * 4
      img.data[i] = r; img.data[i + 1] = g; img.data[i + 2] = b; img.data[i + 3] = 255
    }
  }
  ctx.putImageData(img, 0, 0)
}

function frame(ts: number) {
  raf = requestAnimationFrame(frame)
  if (ts - last < 90) return // ~11 fps keeps the chunky, retro feel
  last = ts
  t++
  paint()
}

onMounted(() => {
  paint()
  if (!window.matchMedia('(prefers-reduced-motion: reduce)').matches) raf = requestAnimationFrame(frame)
})
onBeforeUnmount(() => cancelAnimationFrame(raf))

const lines = computed(() => log.value.slice(-9))
const status = computed(() => (stage.value >= 0 && stage.value < STAGES.length ? STAGES[stage.value] : 'Starting'))
const mark = (i: number) => (stage.value > i ? '[x]' : stage.value === i ? '[>]' : '[ ]')
</script>

<template>
  <section class="pixscreen" aria-label="Research in progress">
    <div class="bezel">
      <div class="screen">
        <canvas ref="canvas" class="px-bg" :width="W" :height="H" aria-hidden="true" />
        <div class="px-scan" aria-hidden="true" />
        <div class="px-content">
          <p class="px-title">RESEARCHING<span class="px-dots" aria-hidden="true" /></p>
          <p class="px-target">{{ target }}</p>

          <div class="px-bar" aria-hidden="true">
            <span v-for="(s, i) in STAGES" :key="s" :class="{ on: stage > i, now: stage === i }" />
          </div>
          <ul class="px-stages">
            <li v-for="(s, i) in STAGES" :key="s" :class="{ on: stage > i, now: stage === i }">{{ mark(i) }} {{ s }}</li>
          </ul>

          <div class="px-log" aria-hidden="true">
            <p v-for="(l, i) in lines" :key="`${log.length}-${i}`">&gt; {{ l }}</p>
            <p v-if="!lines.length">&gt; WAKING THE AGENT</p>
            <span class="px-cursor">█</span>
          </div>
        </div>
      </div>
    </div>
    <p class="sr" role="status">Researching {{ target }}. Current stage: {{ status }}.</p>
  </section>
</template>
