<script setup lang="ts">
const route = useRoute()
const router = useRouter()
const { running, error, start, readyKey } = useResearch()
const { data: config } = await useFetch('/api/config')
const { data: guides } = await useFetch<GuideEntry[]>('/api/guides', { key: 'guides' })

const query = ref(String(route.query.q || ''))
const model = ref('')
const maxPages = ref(20)
const maxSeconds = ref(300)
const maxSteps = ref(10)
const liveProbes = ref(true)
watch(() => config.value?.model, (m) => { if (m && !model.value) model.value = m }, { immediate: true })
watch(() => route.query.q, (q) => { if (q) query.value = String(q) })

const EXAMPLES = ['Slack', 'Spotify', 'Calendly', 'Dropbox', 'linear.app']

async function go() {
  const t = query.value.trim()
  if (!t || running.value) return
  const key = await start({ target: t, model: model.value.trim() || undefined, maxPages: maxPages.value, maxSeconds: maxSeconds.value, maxSteps: maxSteps.value, probes: liveProbes.value })
  await refreshNuxtData('guides')
  // Open the new guide, unless the user has already moved to another page while it ran.
  if (key && router.currentRoute.value.path === '/') {
    readyKey.value = ''
    await router.push({ path: '/guide', query: { g: key } })
  }
}

useHead({ title: 'OAuth Guide Agent' })
</script>

<template>
  <div>
    <header class="hero" :class="{ compact: running }">
      <template v-if="!running">
        <p class="eyebrow">AI research agents</p>
        <h1>Get an OAuth setup guide for <em>any app</em>, researched live</h1>
        <p>Paste a website or type an app name. Agents read the developer docs, test them live, and write the guide: how hard it is, how long approval takes, what blocks you, and what you must do yourself.</p>
      </template>
      <form class="bigsearch" autocomplete="off" @submit.prevent="go">
        <div class="bigfield-wrap">
          <span class="ico" aria-hidden="true">🔎</span>
          <input v-model="query" class="bigfield" type="text" spellcheck="false" autofocus placeholder="Paste a website URL or type an app name…" aria-label="Website URL or app name" :disabled="running">
        </div>
        <button class="bigbtn" type="submit" :disabled="running || !query.trim()">{{ running ? 'Researching…' : 'Research →' }}</button>
      </form>

      <div class="row-chips try-row">
        <span class="hint">Try:</span>
        <button v-for="e in EXAMPLES" :key="e" class="topic" type="button" :disabled="running" @click="query = e">{{ e }}</button>
        <details class="panel adv">
          <summary>⚙️ Advanced settings</summary>
          <div class="settings">
            <label>Model <span class="hint">(blank = auto)</span>
              <input v-model="model" class="field small" type="text" spellcheck="false" placeholder="auto-detect">
            </label>
            <label>Max pages <b>{{ maxPages }}</b><input v-model.number="maxPages" type="range" min="3" max="40"></label>
            <label>Max seconds <b>{{ maxSeconds }}</b><input v-model.number="maxSeconds" type="range" min="30" max="600" step="10"></label>
            <label>Agent steps <b>{{ maxSteps }}</b><input v-model.number="maxSteps" type="range" min="0" max="20"></label>
            <label class="inline"><input v-model="liveProbes" type="checkbox"> Live checks <span class="hint">(harmless requests to the provider; never registers anything)</span></label>
            <p class="note">Gemini key: {{ config?.keySource === 'none' ? 'not configured (set GEMINI_API_KEY in .env)' : `from ${config?.keySource}` }}</p>
            <p class="note">Firecrawl: {{ config?.firecrawl ? 'on (search and JavaScript-rendered pages)' : 'off (set FIRECRAWL_API_KEY in .env to enable)' }}</p>
          </div>
        </details>
      </div>
    </header>

    <div class="home-main">
      <section class="home-right" aria-live="polite">
        <AgentsAtWork v-if="running" />
        <div v-else class="empty">
          <div class="big-ico" aria-hidden="true">🔐</div>
          <h2>Paste your website URL above</h2>
          <p>The agents will find the docs, check them live and write your guide. It takes about two to three minutes.</p>
          <p v-if="error" class="error-box" role="alert">{{ error }}</p>
          <span class="or">or</span>
          <NuxtLink to="/guides" class="btn">📚 See saved guides ({{ guides?.length || 0 }})</NuxtLink>
        </div>
      </section>
    </div>

  </div>
</template>
