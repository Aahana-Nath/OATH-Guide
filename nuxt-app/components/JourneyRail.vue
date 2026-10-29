<script setup lang="ts">
const props = defineProps<{
  guides: GuideEntry[]
  currentKey: string
  trace: Record<string, any> | null
}>()
const emit = defineEmits<{ open: [key: string]; done: [key: string]; reset: [] }>()

const POPULAR = ['Slack', 'Zoom', 'GitHub', 'Spotify', 'Linear', 'Notion', 'Shopify', 'Google']
const { running, log, stage, error, target: runTarget, liveStats, start, reset: resetRun } = useResearch()
const { data: config } = await useFetch('/api/config')

const query = ref('')
const model = ref('')
const maxPages = ref(20)
const maxSeconds = ref(300)
const maxSteps = ref(10)
const liveProbes = ref(true)
watch(() => config.value?.model, (m) => { if (m && !model.value) model.value = m }, { immediate: true })

const hasRun = computed(() => running.value || log.value.length > 0 || !!error.value)

// Live numbers while an agent runs, otherwise the numbers saved in the open guide's trace.
const stats = computed(() => {
  if (hasRun.value && (running.value || !props.trace)) return liveStats.value
  const f: any[] = props.trace?.findings || []
  return {
    pages: props.trace?.pages?.length ?? 0,
    claims: f.filter((x) => x.verified).length,
    dropped: f.filter((x) => !x.verified).length,
    steps: (props.trace?.steps || []).filter((s: any) => s.action !== 'finish').length
  }
})
const pagesRead: ComputedRef<any[]> = computed(() => props.trace?.pages || [])
const rejected: ComputedRef<any[]> = computed(() => (props.trace?.findings || []).filter((x: any) => !x.verified))
const agentSteps: ComputedRef<any[]> = computed(() => props.trace?.steps || [])
const probes = computed<{ observations: any[]; skipped: any[]; requests: number } | null>(() => props.trace?.probes || null)

async function research(name?: string) {
  const t = (name ?? query.value).trim()
  if (!t || running.value) return
  query.value = t
  const key = await start({ target: t, model: model.value.trim() || undefined, maxPages: maxPages.value, maxSeconds: maxSeconds.value, maxSteps: maxSteps.value, probes: liveProbes.value })
  if (key) emit('done', key)
}

const stageState = (i: number) => (stage.value > i ? 'done' : stage.value === i && running.value ? 'active' : 'idle')

const resetting = ref(false)
const notice = ref('')
async function resetStored() {
  if (!confirm('Delete every guide and trace the agent has generated (the out/ folder)?\n\nHand-researched guides in guides/ are kept. This cannot be undone.')) return
  resetting.value = true
  try {
    const r = await $fetch<{ deleted: number }>('/api/reset', { method: 'DELETE' })
    resetRun()
    notice.value = r.deleted ? `Removed ${r.deleted} stored file${r.deleted === 1 ? '' : 's'}.` : 'Nothing to remove.'
    emit('reset')
  } catch (e: any) {
    notice.value = e?.data?.statusMessage || 'Reset failed.'
  } finally {
    resetting.value = false
  }
}
const logText = computed(() => log.value.join('\n'))
const logBox = ref<HTMLElement | null>(null)
watch(logText, () => nextTick(() => { if (logBox.value) logBox.value.scrollTop = logBox.value.scrollHeight }))
</script>

<template>
  <aside class="rail" aria-label="The journey">
    <h2 class="rail-title">The journey</h2>

    <section class="step-block">
      <p class="eyebrow">1 · Pick an app</p>
      <div class="topics">
        <button v-for="p in POPULAR" :key="p" class="topic" type="button" :disabled="running" @click="research(p)">{{ p }}</button>
      </div>
      <form class="lookup" autocomplete="off" @submit.prevent="research()">
        <input v-model="query" class="field" type="text" spellcheck="false" placeholder="e.g. Linear, or https://developers.figma.com" aria-label="App name or website" :disabled="running">
        <button class="btn primary" type="submit" :disabled="running || !query.trim()">{{ running ? 'Researching…' : '▶ Research' }}</button>
      </form>
      <details class="panel">
        <summary>Settings</summary>
        <div class="settings">
          <label>Model <span class="hint">(blank = auto)</span>
            <input v-model="model" class="field small" type="text" spellcheck="false" placeholder="auto-detect">
          </label>
          <label>Max pages <b>{{ maxPages }}</b>
            <input v-model.number="maxPages" type="range" min="3" max="40">
          </label>
          <label>Max seconds <b>{{ maxSeconds }}</b>
            <input v-model.number="maxSeconds" type="range" min="30" max="600" step="10">
          </label>
          <label>Agent steps <b>{{ maxSteps }}</b>
            <input v-model.number="maxSteps" type="range" min="0" max="20">
          </label>
          <label class="inline"><input v-model="liveProbes" type="checkbox"> Live checks <span class="hint">(read-only requests to the provider: OAuth metadata, authorize endpoint, sign-in wall; never registers anything)</span></label>
          <p class="note">Gemini key: {{ config?.keySource === 'none' ? 'not configured (set GEMINI_API_KEY or GCP_PROJECT_ID in .env)' : `from ${config?.keySource}` }}</p>
        </div>
      </details>
      <p v-if="error" class="note warn" role="alert">{{ error }}</p>
    </section>

    <section class="step-block">
      <p class="eyebrow">2 · Watch the agent work</p>
      <div class="stages" role="list">
        <span v-for="(s, i) in STAGES" :key="s" class="stage" :class="stageState(i)" role="listitem">
          <template v-if="stageState(i) === 'done'">✓ </template><template v-else-if="stageState(i) === 'active'"><i class="spin" /> </template>{{ s }}
        </span>
      </div>
      <p v-if="running" class="note">Researching <strong>{{ runTarget }}</strong>… this can take a few minutes.</p>
    </section>

    <section class="step-block">
      <p class="eyebrow">3 · What it found</p>
      <dl class="stats">
        <div><dt>Pages read</dt><dd>{{ stats.pages }}</dd></div>
        <div><dt>Claims quoted</dt><dd>{{ stats.claims }}</dd></div>
        <div><dt>Dropped</dt><dd>{{ stats.dropped }}</dd></div>
        <div><dt>Agent steps</dt><dd>{{ stats.steps }}</dd></div>
      </dl>

      <details class="panel">
        <summary>Pages the agent read ({{ pagesRead.length }})</summary>
        <ul v-if="pagesRead.length" class="plain">
          <li v-for="p in pagesRead" :key="p.url">
            <a :href="p.url" target="_blank" rel="noopener">{{ p.url }}</a>
            <span class="hint"> {{ p.chars.toLocaleString() }} chars<template v-if="p.thin"> · thin (needs JavaScript)</template></span>
          </li>
        </ul>
        <p v-else class="note">No trace saved for this guide.</p>
      </details>

      <details class="panel">
        <summary>Claims rejected by the quote check ({{ rejected.length }})</summary>
        <ul v-if="rejected.length" class="plain">
          <li v-for="(r, i) in rejected" :key="i">
            <strong>{{ r.text }}</strong>
            <blockquote class="q">{{ r.quote }}</blockquote>
          </li>
        </ul>
        <p v-else class="note">Nothing was rejected.</p>
      </details>

      <details v-if="agentSteps.length" class="panel">
        <summary>Agent steps ({{ agentSteps.length }})</summary>
        <ol class="plain">
          <li v-for="s in agentSteps" :key="s.step">
            <strong>{{ s.action }}</strong><span v-if="s.arg" class="mono"> ({{ s.arg }})</span>
            <div class="hint">{{ s.thought }}</div>
          </li>
        </ol>
      </details>

      <details v-if="probes" class="panel">
        <summary>Live checks the agent ran ({{ probes.observations.length }})</summary>
        <ul v-if="probes.observations.length" class="plain">
          <li v-for="(o, i) in probes.observations" :key="i">
            <strong>{{ o.text }}</strong>
            <div v-if="o.quote" class="q">{{ o.quote }}</div>
          </li>
        </ul>
        <p class="note">{{ probes.requests }} read-only request{{ probes.requests === 1 ? '' : 's' }}. No login, no registration.</p>
        <template v-if="probes.skipped.length">
          <p class="eyebrow">Not completed</p>
          <ul class="plain"><li v-for="(s, i) in probes.skipped" :key="i"><span class="mono">{{ s.what }}</span><div class="hint">{{ s.why }}</div></li></ul>
        </template>
      </details>

      <details class="panel">
        <summary>Raw log</summary>
        <pre ref="logBox" class="logbox">{{ logText || 'No run yet in this session.' }}</pre>
      </details>
    </section>

    <section class="step-block">
      <p class="eyebrow">Saved guides</p>
      <div class="topics">
        <button
          v-for="g in guides"
          :key="g.key"
          class="topic"
          type="button"
          :class="{ current: g.key === currentKey }"
          :aria-current="g.key === currentKey ? 'page' : undefined"
          @click="emit('open', g.key)"
        >{{ g.name }} {{ g.mode === 'agent' ? '🤖' : '✍️' }}</button>
      </div>
      <p class="note">✍️ researched by hand · 🤖 researched by the agent</p>
      <div class="rail-actions">
        <button class="btn small danger" type="button" :disabled="running || resetting" @click="resetStored">🗑 Reset</button>
        <span class="note" role="status">{{ notice || 'Removes agent-generated guides and traces. Hand-researched guides stay.' }}</span>
      </div>
    </section>
  </aside>
</template>
