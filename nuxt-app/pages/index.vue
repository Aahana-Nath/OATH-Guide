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
const recent = computed(() => [...(guides.value || [])].sort((a, b) => b.mtime - a.mtime).slice(0, 4))

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

      <div class="row-chips">
        <span class="hint">Try:</span>
        <button v-for="e in EXAMPLES" :key="e" class="topic" type="button" :disabled="running" @click="query = e">{{ e }}</button>
      </div>
    </header>

    <div class="home-grid">
      <aside class="home-left">
        <section>
          <details class="panel">
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
        </section>

        <section v-if="recent.length">
          <p class="eyebrow">Recently saved</p>
          <div class="recent">
            <NuxtLink v-for="g in recent" :key="g.key" :to="{ path: '/guide', query: { g: g.key } }">
              <span class="avatar sm" :style="{ background: avatarColor(g.name) }" aria-hidden="true">{{ g.name[0] }}</span>
              <span>{{ g.name }}</span>
              <span class="lvl" :class="g.public" style="margin-left: auto">Public: {{ LEVELS[g.public] }}</span>
            </NuxtLink>
          </div>
          <NuxtLink to="/guides" class="hint">See all {{ guides?.length }} saved guides →</NuxtLink>
        </section>

        <section>
          <p class="eyebrow">How it works</p>
          <ol class="plain" style="padding-left: 18px">
            <li>Scout finds the developer docs.</li>
            <li>Reader follows links and quotes what it finds.</li>
            <li>Verifier checks every quote against the page, tries the provider's endpoints, and re-tests everything before the guide is saved.</li>
            <li>Judge and Writer turn it into a guide where every claim carries a label and a source.</li>
          </ol>
        </section>
      </aside>

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
