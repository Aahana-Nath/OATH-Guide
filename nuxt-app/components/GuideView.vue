<script setup lang="ts">
const props = defineProps<{ guide: Guide; entry: GuideEntry | null }>()

const showAll = ref(false)
provide('showAll', showAll)

const filter = ref('all')
const selType = ref<string | null>(null)
watch(
  () => props.guide,
  (g) => {
    const st = g.setup_types
    selType.value = st ? (st.types.find((t: any) => t.recommended) || st.types[0]).id : null
    filter.value = 'all'
  },
  { immediate: true }
)

const g = computed(() => props.guide)
const st = computed(() => g.value.setup_types)
const claims = computed(() => allClaims(g.value))
const counts = computed(() => claimCounts(claims.value))
const testedExtra = computed(() => (g.value.extras || []).find((x: any) => x.title === TESTED_TITLE))
const otherExtras = computed(() => (g.value.extras || []).filter((x: any) => x.title !== TESTED_TITLE))
const testedByPerson = computed(() => claims.value.filter((c) => c.claim.label === 'tested' && c.claim.source_type === 'manual_test').length)
const testedByAgent = computed(() => claims.value.filter((c) => c.claim.label === 'tested' && c.claim.source_type === 'agent_probe').length)
const total = computed(() => claims.value.length || 1)
const shownClaims = computed(() => claims.value.filter((c) => filter.value === 'all' || c.claim.label === filter.value))
const steps = computed(() => g.value.steps.filter((s: any) => !s.applies_to || s.applies_to === selType.value))
const selTypeName = computed(() => st.value?.types.find((t: any) => t.id === selType.value)?.name || '')
const typeName = (id: string) => st.value?.types.find((t: any) => t.id === id)?.name || id

// Header chips: which parts of the guide actually carry information.
const coverage = computed(() => {
  const x = g.value
  const sourced = claims.value.every((c) => !['official_docs', 'tested'].includes(c.claim.label) || c.claim.source_url || c.claim.source_type === 'manual_test')
  return [
    { name: 'Difficulty', ok: x.difficulty.start.level !== 'unknown' || x.difficulty.public.level !== 'unknown' },
    { name: 'Time & approval wait', ok: x.time.to_approval.display !== 'Not found' || x.time.to_start.display !== 'Unknown' },
    { name: 'Requirements', ok: x.requirements.register.length + x.requirements.go_public.length > 0 },
    { name: 'Blockers', ok: x.blockers.length > 0 },
    { name: 'Agent vs human', ok: x.agent_vs_human.agent.length + x.agent_vs_human.human.length > 0 },
    { name: 'Setup steps', ok: x.steps.some((s: any) => s.claim?.label !== 'inferred') },
    { name: 'Sources on every claim', ok: sourced }
  ]
})
const nav = [
  ['sec-1', 'Difficulty & time'], ['sec-2', 'Path'], ['sec-3', 'Steps'], ['sec-4', 'Needs'],
  ['sec-5', 'Risks'], ['sec-6', 'Who does what'], ['sec-7', 'Trust']
]

// Quick links: smooth-scroll to a section and highlight the one being read.
const activeSection = ref('')
function jump(id: string) {
  if (id === 'top') return window.scrollTo({ top: 0, behavior: 'smooth' })
  document.getElementById(id)?.scrollIntoView({ behavior: 'smooth', block: 'start' })
  activeSection.value = id
}
let spy: IntersectionObserver | null = null
function observe() {
  spy?.disconnect()
  // A section counts as current while it crosses the band just below the sticky bar.
  spy = new IntersectionObserver(
    (entries) => entries.forEach((e) => { if (e.isIntersecting) activeSection.value = e.target.id }),
    { rootMargin: '-80px 0px -65% 0px' }
  )
  nav.forEach(([id]) => { const el = document.getElementById(id); if (el) spy!.observe(el) })
}
onMounted(observe)
watch(g, () => { activeSection.value = ''; nextTick(observe) })
onBeforeUnmount(() => spy?.disconnect())

const copied = ref('')
async function copyLink() {
  try {
    await navigator.clipboard.writeText(location.href)
    copied.value = 'Link copied.'
  } catch {
    copied.value = 'Copy the address bar.'
  }
  setTimeout(() => (copied.value = ''), 2500)
}
</script>

<template>
  <div class="guide">
    <!-- header -->
    <section class="card pad-lg head">
      <div class="head-top">
        <h1>{{ g.provider.name }}</h1>
        <div class="row-chips">
          <button class="btn small" type="button" @click="copyLink">Copy link</button>
          <span v-if="copied" class="note" role="status">{{ copied }}</span>
        </div>
      </div>
      <p class="lead">{{ g.summary }}</p>
      <p class="meta-line">
        <a :href="g.provider.website" target="_blank" rel="noopener">{{ g.provider.website }}</a>
        · generated {{ g.generated_at }} · {{ g.generated_by.mode === 'manual_plus_agent' ? 'hands-on testing plus documentation research' : g.generated_by.mode }}
        <template v-if="g.generated_by.model"> · {{ g.generated_by.model }}</template>
      </p>
      <div class="row-chips">
        <span v-for="c in coverage" :key="c.name" class="cov" :class="{ ok: c.ok }">{{ c.ok ? '✓' : '–' }} {{ c.name }}</span>
      </div>
    </section>

    <div class="quicknav">
      <nav aria-label="Jump to a section">
        <a
          v-for="[id, label] in nav"
          :key="id"
          :href="`#${id}`"
          :class="{ active: activeSection === id }"
          :aria-current="activeSection === id ? 'location' : undefined"
          @click.prevent="jump(id)"
        >{{ label }}</a>
      </nav>
      <div class="qn-right">
        <label class="check"><input v-model="showAll" type="checkbox"> Show all evidence</label>
        <button class="btn small" type="button" @click="jump('top')">↑ Top</button>
      </div>
    </div>

    <!-- 1 -->
    <section id="sec-1" class="block">
      <h2 class="h2">1 · How hard, how long</h2>
      <div class="tiles">
        <div class="tile">
          <span class="eyebrow">Difficulty to get started</span>
          <span class="big" :class="g.difficulty.start.level">{{ LEVELS[g.difficulty.start.level] }}</span>
        </div>
        <div class="tile">
          <span class="eyebrow">Difficulty to go public</span>
          <span class="big" :class="g.difficulty.public.level">{{ LEVELS[g.difficulty.public.level] }}</span>
        </div>
        <div class="tile">
          <span class="eyebrow">Time to get started</span>
          <span class="mid">{{ g.time.to_start.display }}</span>
          <ClaimPill :claim="g.time.to_start.claim" />
        </div>
        <div class="tile">
          <span class="eyebrow">Wait for approval</span>
          <span class="mid">{{ g.time.to_approval.display }}</span>
          <ul v-if="g.time.to_approval.stages.length" class="pre">
            <li v-for="s in g.time.to_approval.stages" :key="s.name"><strong>{{ s.name }}:</strong> {{ s.duration_text }}</li>
          </ul>
          <ClaimPill :claim="g.time.to_approval.claim" />
          <Fact v-if="g.time.to_approval.total_estimate" :text="g.time.to_approval.total_estimate.text" :claim="g.time.to_approval.total_estimate" />
        </div>
      </div>
      <details class="panel wide">
        <summary>Why these ratings</summary>
        <div class="two inner">
          <div><p class="eyebrow">Getting started · {{ LEVELS[g.difficulty.start.level] }}</p><Fact :text="g.difficulty.start.reason.text" :claim="g.difficulty.start.reason" /></div>
          <div><p class="eyebrow">Going public · {{ LEVELS[g.difficulty.public.level] }}</p><Fact :text="g.difficulty.public.reason.text" :claim="g.difficulty.public.reason" /></div>
        </div>
      </details>

      <div class="card pad-lg testbox" :class="{ none: !testedByPerson && !testedByAgent }">
        <h3 class="h3">What was tested, and what wasn't</h3>
        <p v-if="testedByPerson" class="sub">{{ testedByPerson }} claim{{ testedByPerson === 1 ? '' : 's' }} come from someone who ran the setup by hand.</p>
        <template v-if="testedExtra">
          <p class="sub">{{ testedExtra.why_it_matters }}</p>
          <ul class="list"><li v-for="(c, i) in testedExtra.claims" :key="i"><Fact :text="c.text" :claim="c" /></li></ul>
        </template>
        <p v-if="!testedByPerson && !testedByAgent" class="note warn">
          Nothing in this guide was tested. Every statement comes from the provider's documentation or is the model's reasoning from it, so treat it as research, not a verified walkthrough.
        </p>
        <p v-else-if="!testedByPerson" class="sub">
          Everything not listed above comes from documentation or is inferred. Registering, installing and submitting an app were <strong>not</strong> attempted: they need your account.
        </p>
      </div>
    </section>

    <!-- 2 -->
    <section id="sec-2" class="block">
      <h2 class="h2">2 · The path from private to public</h2>
      <p class="sub">Each stage opens up more users and adds a gate. Registering is only the first one.</p>
      <ol class="path">
        <template v-for="(t, i) in g.access_ladder" :key="t.tier">
          <li v-if="i" class="arrow" aria-hidden="true">→</li>
          <li class="stage-card">
            <span class="sub">Stage {{ t.tier }}</span>
            <h3>{{ t.name }}</h3>
            <p>{{ t.allows }}</p>
            <p class="gate">To reach it: {{ t.gate }}</p>
            <div v-if="t.prerequisites.length">
              <p class="eyebrow">Before this stage</p>
              <ul class="pre"><li v-for="p in t.prerequisites" :key="p">{{ p }}</li></ul>
            </div>
            <div class="list"><Fact v-for="(c, j) in t.claims" :key="j" :text="c.text" :claim="c" /></div>
          </li>
        </template>
      </ol>
    </section>

    <!-- 3 -->
    <section id="sec-3" class="block">
      <h2 class="h2">3 · Steps</h2>

      <div v-if="st" class="card pad-lg">
        <h3 class="h3">Pick a setup type</h3>
        <div class="callout">
          <strong>Recommended: {{ typeName(st.recommendation.type_id) }}</strong>
          <Fact :text="st.recommendation.claim.text" :claim="st.recommendation.claim" />
          <ul v-if="st.recommendation.exceptions?.length" class="list">
            <li v-for="(e, i) in st.recommendation.exceptions" :key="i">
              <Fact :text="`If ${e.when.charAt(0).toLowerCase() + e.when.slice(1)}, use ${typeName(e.use_instead_type_id)}.`" :claim="e.claim" />
            </li>
          </ul>
        </div>
        <div class="scroll">
          <table class="cmp">
            <thead>
              <tr>
                <th scope="col" />
                <th v-for="t in st.types" :key="t.id" scope="col" :class="{ sel: t.id === selType }">{{ t.name }}<div class="sub light">{{ t.one_line }}</div></th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="r in st.rows" :key="r.label">
                <th scope="row">{{ r.label }}</th>
                <td v-for="t in st.types" :key="t.id" :class="{ sel: t.id === selType }">
                  <template v-for="c in r.cells.filter((x: any) => x.type_id === t.id)" :key="c.type_id"><Fact :text="c.value" :claim="c.claim" /></template>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
        <div>
          <p id="tablabel" class="eyebrow">Show the steps for</p>
          <div class="tabs" role="tablist" aria-labelledby="tablabel">
            <button v-for="t in st.types" :id="`tab-${t.id}`" :key="t.id" class="tab" role="tab" type="button" :aria-selected="t.id === selType" @click="selType = t.id">
              {{ t.name }} <span v-if="t.recommended" class="chip rec">Recommended</span>
            </button>
          </div>
        </div>
      </div>

      <div v-if="g.creation_paths" class="card pad-lg">
        <h3 class="h3">Ways to create the app</h3>
        <div class="scroll">
          <table class="tbl">
            <thead><tr><th scope="col">Path</th><th scope="col">What you get</th><th scope="col">Use when</th><th scope="col">Evidence</th></tr></thead>
            <tbody>
              <tr v-for="p in g.creation_paths" :key="p.id">
                <th scope="row">{{ p.name }} <span v-if="p.recommended" class="chip rec">Recommended</span></th>
                <td>{{ p.gives }}</td>
                <td>{{ p.use_when }}</td>
                <td><Fact :text="p.claim.text" :claim="p.claim" /></td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>

      <div class="card pad-lg">
        <h3 class="h3">{{ selTypeName ? `Steps · ${selTypeName}` : 'Steps' }}</h3>
        <ol v-if="steps.length" class="steps">
          <li v-for="(s, i) in steps" :key="i" class="step">
            <span class="n">{{ i + 1 }}</span>
            <div class="body">
              <span>{{ s.text }}</span>
              <div class="row-chips"><span class="chip actor" :class="s.actor">{{ ACTOR[s.actor] }}</span></div>
              <ClaimPill :claim="s.claim" />
            </div>
          </li>
        </ol>
        <template v-else>
          <p class="note warn">No steps have been researched for this type yet.</p>
          <div v-if="st" class="row-chips">
            <button v-for="t in st.types.filter((x: any) => g.steps.some((s: any) => s.applies_to === x.id))" :key="t.id" class="btn small" type="button" @click="selType = t.id">Show steps for {{ t.name }}</button>
          </div>
        </template>
      </div>
    </section>

    <!-- 4 -->
    <section id="sec-4" class="block">
      <h2 class="h2">4 · What you need</h2>
      <div class="two">
        <div v-for="[title, list] in [['To register', g.requirements.register], ['To go public', g.requirements.go_public]]" :key="title as string" class="card pad-lg">
          <h3 class="h3">{{ title }}</h3>
          <ul v-if="(list as any[]).length" class="list">
            <li v-for="r in (list as any[])" :key="r.item">
              <div class="rowtop"><strong>{{ r.item }}</strong><span class="chip status" :class="r.status">{{ STATUS[r.status] }}</span></div>
              <Fact :text="r.claim.text" :claim="r.claim" />
            </li>
          </ul>
          <p v-else class="note">Nothing found.</p>
        </div>
      </div>
      <div class="card pad-lg">
        <h3 class="h3">Limits</h3>
        <div v-if="g.limits.length" class="scroll">
          <table class="tbl">
            <thead><tr><th scope="col">Limit</th><th scope="col">Value</th><th scope="col">Evidence</th></tr></thead>
            <tbody>
              <tr v-for="(l, i) in g.limits" :key="i">
                <th scope="row">{{ l.item }}</th><td>{{ l.value }}</td><td><Fact :text="l.claim.text" :claim="l.claim" /></td>
              </tr>
            </tbody>
          </table>
        </div>
        <p v-else class="note">No limits were found.</p>
      </div>
    </section>

    <!-- 5 -->
    <section id="sec-5" class="block">
      <h2 class="h2">5 · What can trip you up</h2>
      <div class="card pad-lg">
        <ul v-if="g.blockers.length" class="list">
          <li v-for="(b, i) in g.blockers" :key="i">
            <strong>{{ b.issue }}</strong>
            <span class="sub">Fix: {{ b.fix }}</span>
            <Fact :text="b.claim.text" :claim="b.claim" />
          </li>
        </ul>
        <p v-else class="note">No blockers were found in the pages read.</p>
      </div>
      <div v-if="otherExtras.length" class="card pad-lg">
        <h3 class="h3">Also worth knowing</h3>
        <ul class="list">
          <li v-for="(x, i) in otherExtras" :key="i">
            <strong>{{ x.title }}</strong>
            <span class="sub">{{ x.why_it_matters }}</span>
            <Fact v-for="(c, j) in x.claims" :key="j" :text="c.text" :claim="c" />
          </li>
        </ul>
      </div>
      <div v-if="g.evidence.conflicts.length" class="card pad-lg">
        <h3 class="h3">Where sources disagree</h3>
        <ul class="list">
          <li v-for="(c, i) in g.evidence.conflicts" :key="i">
            <strong>{{ c.topic }}</strong><span>A: {{ c.a }}</span><span>B: {{ c.b }}</span><span class="sub">{{ c.note }}</span>
          </li>
        </ul>
      </div>
    </section>

    <!-- 6 -->
    <section id="sec-6" class="block">
      <h2 class="h2">6 · Who does what</h2>
      <div class="two">
        <div v-for="[title, list] in [['An agent can do', g.agent_vs_human.agent], ['You have to do', g.agent_vs_human.human]]" :key="title as string" class="card pad-lg">
          <h3 class="h3">{{ title }}</h3>
          <ul v-if="(list as any[]).length" class="list">
            <li v-for="(t, i) in (list as any[])" :key="i"><strong>{{ t.text }}</strong><Fact :text="t.claim.text" :claim="t.claim" /></li>
          </ul>
          <p v-else class="note">Nothing listed.</p>
        </div>
      </div>
    </section>

    <!-- 7 -->
    <section id="sec-7" class="block">
      <h2 class="h2">7 · How far to trust this guide</h2>
      <div class="card pad-lg">
        <div class="meter" role="img" :aria-label="`${claims.length} claims`">
          <span v-for="(n, k) in counts" :key="k" :class="k" :style="{ width: `${(n / total) * 100}%` }" :title="`${LABELS[k]}: ${n}`" />
        </div>
        <ul class="legend">
          <li v-for="(n, k) in counts" :key="k">
            <span class="sw" :style="{ background: `var(--${k === 'official_docs' ? 'official' : k}-solid)` }" />
            <span><strong>{{ LABELS[k] }}</strong><br><span class="hp">{{ LABEL_HELP[k] }}</span></span>
            <span class="ct">{{ n }}</span>
          </li>
        </ul>
        <p class="note">{{ claims.length }} claims in total. Open any label to see its source, quote and date.</p>
      </div>

      <div class="card pad-lg dashed">
        <h3 class="h3">Not verified</h3>
        <ul class="list"><li v-for="(n, i) in g.evidence.not_verified" :key="i"><strong>{{ n.item }}</strong><span class="sub">{{ n.note }}</span></li></ul>
      </div>

      <div class="card pad-lg">
        <h3 class="h3">All claims</h3>
        <div class="filters" role="group" aria-label="Filter claims by label">
          <button v-for="f in ['all', 'tested', 'official_docs', 'inferred', 'unknown']" :key="f" class="tab small" type="button" :aria-pressed="filter === f" @click="filter = f">
            {{ f === 'all' ? 'All' : LABELS[f] }} {{ f === 'all' ? claims.length : counts[f] }}
          </button>
        </div>
        <div class="scroll">
          <table class="tbl">
            <thead><tr><th scope="col">Section</th><th scope="col">Claim</th><th scope="col">Evidence</th></tr></thead>
            <tbody>
              <tr v-for="(c, i) in shownClaims" :key="i"><td>{{ c.where }}</td><td>{{ c.claim.text }}</td><td><ClaimPill :claim="c.claim" /></td></tr>
            </tbody>
          </table>
        </div>
      </div>

      <div class="card pad-lg">
        <h3 class="h3">Sources</h3>
        <ul class="list">
          <li v-for="s in g.evidence.sources" :key="s.url" class="fact">
            <span class="t"><a v-if="safeUrl(s.url)" :href="s.url" target="_blank" rel="noopener">{{ s.title }}</a><template v-else>{{ s.title }}</template></span>
            <span class="sub">{{ SOURCE_KIND[s.type] || s.type }} · {{ hostOf(s.url) }}</span>
          </li>
        </ul>
      </div>

      <p class="foot">Generated {{ g.generated_at }} · {{ g.generated_by.mode }} · schema {{ g.schema_version }}</p>
    </section>
  </div>
</template>
