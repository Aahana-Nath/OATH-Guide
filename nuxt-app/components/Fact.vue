<script setup lang="ts">
defineProps<{ text: string; claim?: Record<string, any> | null }>()
</script>

<template>
  <div class="fact">
    <span class="t">{{ text }}</span>
    <ClaimPill :claim="claim" />
  </div>
</template>
