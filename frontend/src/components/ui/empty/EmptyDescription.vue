<script setup>
import { cn } from "@/lib/utils";

defineProps({
  class: { type: null, required: false },
});
</script>

<template>
  <p
    data-slot="empty-description"
    :class="
      cn(
        'text-sm/relaxed text-muted-foreground [&>a]:underline [&>a]:underline-offset-4 [&>a:hover]:text-primary',
        $attrs.class ?? '',
      )
    "
  >
    <slot />
  </p>
</template>
