<script setup>
import { cn } from "@/lib/utils";

const props = defineProps({
  class: { type: null, required: false },
});
</script>

<template>
  <div
    data-slot="popover-header"
    :class="cn('flex flex-col gap-0.5 text-sm', props.class)"
  >
    <slot />
  </div>
</template>
