<script setup>
import { cn } from "@/lib/utils";

const props = defineProps({
  class: { type: null, required: false },
});
</script>

<template>
  <div
    data-slot="empty-header"
    :class="cn('gap-2 flex max-w-sm flex-col items-center', props.class)"
  >
    <slot />
  </div>
</template>
