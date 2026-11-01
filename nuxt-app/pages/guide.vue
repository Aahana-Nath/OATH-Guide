<script setup lang="ts">
const route = useRoute()
const key = computed(() => String(route.query.g || ''))

// Without a guide key there is nothing to show: go to the library.
if (!key.value) await navigateTo('/guides', { replace: true })

const { data, error } = await useFetch<{ entry: GuideEntry; guide: Guide; trace: Record<string, any> | null }>('/api/guide', {
  query: { key },
  watch: [key]
})

const g = computed(() => data.value?.guide)
const showAll = ref(false)
provide('showAll', showAll)

const claims = computed(() => (g.value ? allClaims(g.value) : []))
const coverage = computed(() => {
  const x = g.value
  if (!x) return []
  const sourced = claims.value.every((c) => !['official_docs', 'tested'].includes(c.claim.label) || c.claim.source_url || c.claim.source_type === 'manual_test')
  return [
    { name: 'Difficulty', ok: x.difficulty.start.level !== 'unknown' || x.difficulty.public.level !== 'unknown' },
    { name: 'Time & approval wait', ok: x.time.to_approval.display !== 'Not found' || x.time.to_start.display !== 'Unknown' },
    { name: 'OAuth setup', ok: (x.oauth_setup || []).length > 0 },
    { name: 'Requirements', ok: x.requirements.register.length + x.requirements.go_public.length > 0 },
    { name: 'Blockers', ok: x.blockers.length > 0 },
    { name: 'Agent vs human', ok: x.agent_vs_human.agent.length + x.agent_vs_human.human.length > 0 },
    { name: 'Setup steps', ok: x.steps.some((s: any) => s.claim?.label !== 'inferred') },
    { name: 'Sources on every claim', ok: sourced }
  ]
})

// Sections nav: smooth-scroll and highlight the section being read.
const activeSection = ref('')
function jump(id: string) {
  document.getElementById(id)?.scrollIntoView({ behavior: 'smooth', block: 'start' })
  activeSection.value = id
}
let spy: IntersectionObserver | null = null
function observe() {
  spy?.disconnect()
  spy = new IntersectionObserver(
    (entries) => entries.forEach((e) => { if (e.isIntersecting) activeSection.value = e.target.id }),
    { rootMargin: '-10% 0px -70% 0px' }
  )
  GUIDE_SECTIONS.forEach(([id]) => { const el = document.getElementById(id); if (el) spy!.observe(el) })
}
onMounted(() => nextTick(observe))
watch(g, () => { activeSection.value = ''; nextTick(observe) })
onBeforeUnmount(() => spy?.disconnect())

const copied = ref('')
async function copyLink() {
  try { await navigator.clipboard.writeText(location.href); copied.value = 'Link copied' } catch { copied.value = 'Copy the address bar' }
  setTimeout(() => (copied.value = ''), 2500)
}
const modeLabel = computed(() => (g.value?.generated_by?.mode === 'manual_plus_agent' ? '✍️ Hand-tested plus documentation research' : '🤖 Researched by the agent'))

useHead({ title: computed(() => (g.value ? `${g.value.provider.name} · OAuth Guide Agent` : 'Guide · OAuth Guide Agent')) })
</script>

<template>
  <div v-if="g">
    <section class="gp-hero">
      <div class="top">
        <span class="avatar" :style="{ background: avatarColor(g.provider.name) }" aria-hidden="true">{{ g.provider.name[0] }}</span>
        <h1>{{ g.provider.name }}</h1>
        <div class="actions">
          <span v-if="copied" class="note" role="status">{{ copied }}</span>
          <button class="btn small" type="button" @click="copyLink">🔗 Copy link</button>
          <NuxtLink class="btn small primary" :to="{ path: '/', query: { q: hostOf(g.provider.website) } }">↻ Research again</NuxtLink>
        </div>
      </div>
      <p class="lead">{{ g.summary }}</p>
      <p class="meta-line">
        <a :href="g.provider.website" target="_blank" rel="noopener">{{ g.provider.website }}</a>
        · {{ modeLabel }} · generated {{ g.generated_at }}<template v-if="g.generated_by.model"> · {{ g.generated_by.model }}</template>
      </p>
      <div class="row-chips">
        <span v-for="c in coverage" :key="c.name" class="cov" :class="{ ok: c.ok }">{{ c.ok ? '✓' : '–' }} {{ c.name }}</span>
      </div>
    </section>

    <div class="gp-grid">
      <nav class="gp-nav" aria-label="Guide sections">
        <p class="eyebrow" style="padding: 4px 12px 8px">Guide sections</p>
        <a v-for="[id, ico, label] in GUIDE_SECTIONS" :key="id" :href="`#${id}`" :class="{ active: activeSection === id }" :aria-current="activeSection === id ? 'location' : undefined" @click.prevent="jump(id)">
          <span aria-hidden="true">{{ ico }}</span> {{ label }}
        </a>
        <label class="check"><input v-model="showAll" type="checkbox"> Show all evidence</label>
      </nav>

      <GuideView :guide="g" />

      <ResearchPanel :guide="g" :trace="data?.trace || null" :entry="data?.entry || null" />
    </div>
  </div>

  <div v-else class="empty" style="min-height: 420px">
    <div class="big-ico" aria-hidden="true">🔍</div>
    <h2>{{ error ? 'That guide could not be found' : 'Loading guide…' }}</h2>
    <p v-if="error">It may have been reset. Pick another from the saved guides, or research a new app.</p>
    <NuxtLink to="/guides" class="btn primary">📚 Saved guides</NuxtLink>
  </div>
</template>
