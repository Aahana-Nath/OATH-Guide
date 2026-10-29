<script setup lang="ts">
// One claim's label as an expandable pill: source, date, exact quote and note.
const props = defineProps<{ claim?: Record<string, any> | null }>()
const showAll = inject<Ref<boolean>>('showAll', ref(false))
const url = computed(() => safeUrl(props.claim?.source_url))
</script>

<template>
  <details v-if="claim" class="claim" :open="showAll">
    <summary :class="claim.label">{{ LABELS[claim.label] }}</summary>
    <div class="cbody">
      <div class="meta">
        {{ SOURCE_TYPES[claim.source_type] || 'No source' }}
        <template v-if="url"> · <a :href="url" target="_blank" rel="noopener">{{ hostOf(url) }}</a></template>
        · checked {{ claim.checked_at }}
      </div>
      <blockquote v-if="claim.evidence_quote">{{ claim.evidence_quote }}</blockquote>
      <div v-if="claim.note">{{ claim.note }}</div>
    </div>
  </details>
</template>
