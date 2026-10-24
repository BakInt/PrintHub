<script setup>
import { cn } from "@/lib/utils";

const props = defineProps({
  class: { type: null, required: false },
});
</script>

<template>
  <p
    data-slot="popover-description"
    :class="cn('text-muted-foreground', props.class)"
  >
    <slot />
  </p>
</template>
