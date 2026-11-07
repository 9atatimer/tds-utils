<template>
  <p>import nope from 'not-a-script-import'</p>
</template>

<script setup lang="ts">
import { fold } from '@demo/core';
import useFoo from '~/composables/use-foo';
</script>
