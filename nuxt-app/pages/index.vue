<script setup lang="ts">
const route = useRoute()
const router = useRouter()

const { data: guides, refresh: refreshGuides } = await useFetch<GuideEntry[]>('/api/guides')

// The open guide lives in the address bar (?g=out/slack), so links can be shared.
const currentKey = computed(() => {
  const q = String(route.query.g || '')
  return guides.value?.some((x) => x.key === q) ? q : q && q.startsWith('out/') ? q : guides.value?.[0]?.key || ''
})

const { data, error, refresh } = await useFetch<{ entry: GuideEntry; guide: Guide; trace: Record<string, any> | null }>('/api/guide', {
  query: { key: currentKey },
  watch: [currentKey]
})

function open(key: string) {
  router.push({ query: { g: key } })
}

async function finished(key: string) {
  await refreshGuides()
  if (key === currentKey.value) await refresh() // same file rewritten by a re-run
  open(key)
  document.getElementById('guide')?.scrollIntoView({ behavior: 'smooth' })
}

async function afterReset() {
  await refreshGuides()
  await router.push({ query: {} }) // back to the first saved guide
}

useHead({ title: computed(() => (data.value ? `${data.value.guide.provider.name} · OAuth Guide Agent` : 'OAuth Guide Agent')) })
const { running } = useResearch()
</script>

<template>
  <div class="wrap">
    <header class="top">
      <h1>🔐 OAuth Guide Agent</h1>
      <p>
        Type an app. An agent searches the web, reads the developer docs, and writes the guide a developer needs: how hard it is,
        how long approval takes, what blocks you, and what an AI agent can do versus what you must do. Every claim carries a label and a source.
      </p>
    </header>

    <div class="layout">
      <JourneyRail :guides="guides || []" :current-key="currentKey" :trace="running ? null : data?.trace || null" @open="open" @done="finished" @reset="afterReset" />
      <main id="guide" class="main" aria-live="polite">
        <h2 class="rail-title">{{ running ? 'The agent is working' : 'The guide' }}</h2>
        <PixelScreen v-if="running" />
        <GuideView v-else-if="data?.guide" :guide="data.guide" :entry="data.entry" />
        <section v-else class="card pad-lg">
          <p v-if="error" class="note warn">Could not load that guide. Pick another from Saved guides, or research a new app.</p>
          <p v-else class="note">No guides yet. Pick an app on the left to research one.</p>
        </section>
      </main>
    </div>
  </div>
</template>
