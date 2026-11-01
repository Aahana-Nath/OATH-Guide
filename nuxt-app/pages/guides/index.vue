<script setup lang="ts">
const { data: guides } = await useFetch<GuideEntry[]>('/api/guides', { key: 'guides' })

const q = ref('')
const mode = ref<'all' | 'agent' | 'manual'>('all')
const isAgent = (g: GuideEntry) => g.mode === 'agent'

const shown = computed(() =>
  (guides.value || []).filter((g) => {
    if (mode.value === 'agent' && !isAgent(g)) return false
    if (mode.value === 'manual' && isAgent(g)) return false
    const s = q.value.trim().toLowerCase()
    return !s || g.name.toLowerCase().includes(s) || g.website.toLowerCase().includes(s) || g.summary.toLowerCase().includes(s)
  })
)
const counts = computed(() => ({
  all: guides.value?.length || 0,
  agent: guides.value?.filter(isAgent).length || 0,
  manual: guides.value?.filter((g) => !isAgent(g)).length || 0
}))

useHead({ title: 'Saved guides · OAuth Guide Agent' })
</script>

<template>
  <div>
    <header class="page-head">
      <div>
        <h1>📚 Saved guides</h1>
        <p>{{ counts.all }} guides researched so far. Open one to read it, or start a new one from Home.</p>
      </div>
      <NuxtLink to="/" class="btn primary">＋ New guide</NuxtLink>
    </header>

    <div class="lib-tools">
      <input v-model="q" class="lib-search" type="search" placeholder="Search saved guides…" aria-label="Search saved guides">
      <button class="pill" type="button" :aria-pressed="mode === 'all'" @click="mode = 'all'">All {{ counts.all }}</button>
      <button class="pill" type="button" :aria-pressed="mode === 'agent'" @click="mode = 'agent'">🤖 Agent {{ counts.agent }}</button>
      <button class="pill" type="button" :aria-pressed="mode === 'manual'" @click="mode = 'manual'">✍️ Hand-tested {{ counts.manual }}</button>
    </div>

    <div v-if="shown.length" class="lib-grid">
      <NuxtLink v-for="g in shown" :key="g.key" class="gcard" :to="{ path: '/guide', query: { g: g.key } }">
        <div class="top">
          <span class="avatar" :style="{ background: avatarColor(g.name) }" aria-hidden="true">{{ g.name[0] }}</span>
          <div>
            <h3>{{ g.name }}</h3>
            <span class="src">{{ isAgent(g) ? '🤖 Researched by the agent' : '✍️ Hand-tested' }} · {{ g.generated_at }}</span>
          </div>
        </div>
        <p class="sum">{{ g.summary }}</p>
        <div class="row-chips">
          <span class="lvl" :class="g.start">Start: {{ LEVELS[g.start] }}</span>
          <span class="lvl" :class="g.public">Public: {{ LEVELS[g.public] }}</span>
        </div>
        <p class="wait"><span class="hint">Approval wait:</span> {{ g.approval && g.approval !== 'Not found' ? g.approval.slice(0, 90) : 'not stated in the docs' }}</p>
        <p class="hint">{{ g.claims }} claims<template v-if="g.tested"> · {{ g.tested }} tested live</template></p>
        <p v-if="g.retested" class="hint" style="color: var(--tested-fg)">✓ {{ g.retested.ok }} of {{ g.retested.checked }} quotes re-tested when saved</p>
        <span class="open">Open guide →</span>
      </NuxtLink>
    </div>
    <div v-else class="empty" style="min-height: 320px">
      <div class="big-ico" aria-hidden="true">📭</div>
      <h2>{{ counts.all ? 'No guides match' : 'No saved guides yet' }}</h2>
      <p>{{ counts.all ? 'Try another search or filter.' : 'Research an app from Home and it will appear here.' }}</p>
      <NuxtLink to="/" class="btn primary">＋ New guide</NuxtLink>
    </div>
  </div>
</template>
