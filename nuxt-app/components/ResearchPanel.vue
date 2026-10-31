<script setup lang="ts">
// Right-hand "Research details" panel: what the agent did to produce this guide.
const props = defineProps<{ guide: Guide; trace: Record<string, any> | null; entry: GuideEntry | null }>()

const findings = computed<any[]>(() => props.trace?.findings || [])
const stats = computed(() => ({
  pages: props.trace?.pages?.length ?? 0,
  claims: findings.value.filter((f) => f.verified).length,
  dropped: findings.value.filter((f) => !f.verified).length,
  steps: (props.trace?.steps || []).filter((s: any) => s.action !== 'finish').length
}))
const rejected = computed(() => findings.value.filter((f) => !f.verified))
const steps = computed<any[]>(() => (props.trace?.steps || []).filter((s: any) => s.action !== 'finish'))
const pages = computed<any[]>(() => props.trace?.pages || [])
const probes = computed(() => props.trace?.probes || null)
const sources = computed<any[]>(() => props.guide.evidence?.sources || [])
const isAgent = computed(() => props.guide.generated_by?.mode === 'agent')
const saveCheck = computed(() => props.trace?.savecheck || null)
</script>

<template>
  <div class="gp-panel">
    <div class="rp-card">
      <h3>🤖 Research summary</h3>
      <template v-if="trace">
        <p class="sub">The agent read the provider's developer docs and quoted what it found. Every quote was checked against the page.</p>
        <dl class="rp-stats">
          <div><dt>Pages read</dt><dd>{{ stats.pages }}</dd></div>
          <div><dt>Claims quoted</dt><dd>{{ stats.claims }}</dd></div>
          <div><dt>Dropped</dt><dd>{{ stats.dropped }}</dd></div>
          <div><dt>Agent steps</dt><dd>{{ stats.steps }}</dd></div>
        </dl>
      </template>
      <p v-else class="sub">
        {{ isAgent ? 'No research trace was saved for this guide.' : 'This guide was researched by a person who tried the setup, with the agent helping read the docs. Claims marked Tested were observed by hand.' }}
      </p>
    </div>

    <div v-if="saveCheck" class="rp-card">
      <h3>✅ Tested before saving</h3>
      <p class="sub">Every page this guide cites was fetched again and every quoted passage re-checked. A quote that is not found is removed.</p>
      <dl class="rp-stats">
        <div><dt>Pages</dt><dd>{{ saveCheck.pages }}</dd></div>
        <div><dt>Re-found</dt><dd>{{ saveCheck.ok }}</dd></div>
        <div><dt>Removed</dt><dd>{{ saveCheck.failed.length }}</dd></div>
        <div><dt>Checked</dt><dd>{{ saveCheck.checked }}</dd></div>
      </dl>
      <p v-if="saveCheck.removed?.length" class="hint">Removed: {{ saveCheck.removed.join('; ') }}</p>
    </div>

    <div v-if="steps.length" class="rp-card">
      <h3>Research steps</h3>
      <ul class="rp-steps">
        <li v-for="s in steps.slice(0, 12)" :key="s.step"><span><b>{{ s.action }}</b><template v-if="s.arg"> · <span class="mono">{{ String(s.arg).slice(0, 38) }}</span></template></span></li>
      </ul>
      <p v-if="steps.length > 12" class="hint">+ {{ steps.length - 12 }} more steps</p>
    </div>

    <div v-if="sources.length" class="rp-card">
      <h3>🔗 Key sources</h3>
      <div class="rp-src">
        <div v-for="s in sources.slice(0, 7)" :key="s.url">
          <a :href="s.url" target="_blank" rel="noopener">{{ s.title }}</a>
          <div class="hint">{{ hostOf(s.url) }}</div>
        </div>
      </div>
      <p v-if="sources.length > 7" class="hint">+ {{ sources.length - 7 }} more in Trust &amp; sources</p>
    </div>

    <div v-if="probes" class="rp-card">
      <h3>🧪 Live checks ({{ probes.observations.length }})</h3>
      <p class="hint">{{ probes.requests }} harmless request{{ probes.requests === 1 ? '' : 's' }}. No login, no registration.</p>
      <ul v-if="probes.observations.length" class="plain">
        <li v-for="(o, i) in probes.observations" :key="i">{{ o.text }}</li>
      </ul>
      <details v-if="probes.skipped.length" class="panel">
        <summary>Not completed ({{ probes.skipped.length }})</summary>
        <ul class="plain"><li v-for="(s, i) in probes.skipped" :key="i"><span class="mono">{{ s.what }}</span><div class="hint">{{ s.why }}</div></li></ul>
      </details>
    </div>

    <div v-if="trace" class="rp-card">
      <h3>Details</h3>
      <details class="panel">
        <summary>Pages the agent read ({{ pages.length }})</summary>
        <ul class="plain">
          <li v-for="p in pages" :key="p.url"><a :href="p.url" target="_blank" rel="noopener">{{ p.url }}</a><span class="hint"> {{ p.chars.toLocaleString() }} chars<template v-if="p.thin"> · thin</template></span></li>
        </ul>
      </details>
      <details class="panel">
        <summary>Claims rejected by the quote check ({{ rejected.length }})</summary>
        <ul v-if="rejected.length" class="plain">
          <li v-for="(r, i) in rejected" :key="i"><strong>{{ r.text }}</strong><div class="q">{{ r.quote }}</div></li>
        </ul>
        <p v-else class="note">Nothing was rejected.</p>
      </details>
    </div>
  </div>
</template>
