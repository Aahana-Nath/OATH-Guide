<script setup lang="ts">
const route = useRoute()
const { data: guides } = await useFetch<GuideEntry[]>('/api/guides', { key: 'guides' })
const { running, readyKey } = useResearch()

const count = computed(() => guides.value?.length || 0)
// Quick links to saved guides, one per app (agent and hand-tested versions of the same app share a link to the newest).
const quick = computed(() => {
  const seen = new Map<string, GuideEntry>()
  for (const g of [...(guides.value || [])].sort((a, b) => b.mtime - a.mtime)) if (!seen.has(g.name.toLowerCase())) seen.set(g.name.toLowerCase(), g)
  return [...seen.values()].sort((a, b) => a.name.localeCompare(b.name))
})
const SHOWN = 8
const expanded = ref(false)
const visible = computed(() => (expanded.value ? quick.value : quick.value.slice(0, SHOWN)))
const hidden = computed(() => quick.value.length - SHOWN)
// Router "exact" matching ignores the query string, so mark the open guide by its key instead.
const isOpen = (g: GuideEntry) => route.path === '/guide' && route.query.g === g.key
</script>

<template>
  <aside class="sidebar" aria-label="Main navigation">
    <NuxtLink to="/" class="brand">
      <span class="brand-mark" aria-hidden="true">🔐</span>
      <span>OAuth Guide Agent</span>
      <span class="beta">Beta</span>
    </NuxtLink>

    <nav class="nav" aria-label="Sections">
      <NuxtLink to="/" class="nav-item"><span class="nav-ico" aria-hidden="true">🏠</span> Home <span v-if="running" class="running-dot" title="A run is in progress" /></NuxtLink>
      <NuxtLink to="/guides" class="nav-item"><span class="nav-ico" aria-hidden="true">📚</span> Saved guides <span class="badge">{{ count }}</span></NuxtLink>
      <NuxtLink v-if="readyKey && !running" :to="{ path: '/guide', query: { g: readyKey } }" class="nav-item"><span class="nav-ico" aria-hidden="true">✨</span> Your guide is ready</NuxtLink>
    </nav>

    <template v-if="quick.length">
      <p class="side-label">Saved guides</p>
      <nav class="nav side-apps" aria-label="Saved guides">
        <NuxtLink v-for="g in visible" :key="g.key" :to="{ path: '/guide', query: { g: g.key } }" class="nav-item app-item" :class="{ active: isOpen(g) }">
          <span class="avatar sm" :style="{ background: avatarColor(g.name) }" aria-hidden="true">{{ g.name[0] }}</span> {{ g.name }}
        </NuxtLink>
        <button v-if="hidden > 0" type="button" class="nav-item more-btn" :aria-expanded="expanded" @click="expanded = !expanded">
          {{ expanded ? 'View less' : `View more (${hidden})` }} <span aria-hidden="true">{{ expanded ? '▴' : '▾' }}</span>
        </button>
      </nav>
    </template>
  </aside>
</template>
