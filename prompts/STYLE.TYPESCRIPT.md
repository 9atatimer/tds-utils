# TypeScript Style Guide

> Conventions for TypeScript, Vue, and Nuxt code.

## Formatting

- **Prettier**: printWidth 140, singleQuote true, semi true
- **Indentation**: Spaces, not tabs
- **ESLint**: Vue.js Style Guide (Priority A, B, C rules)

## Language

- TypeScript everywhere; JavaScript only where TS isn't feasible
- Strict mode enabled

## Vue Components

- Vue 3 Composition API with `<script setup>`
- Structure: Template first, then script, then style
- Naming: PascalCase for components (`AppLayout.vue`)
- Functions/variables: camelCase

## Imports

- Group: external libraries first, then local components/utils
- Nuxt auto-imports: `ref`, `computed`, `useRoute`, etc.
- Don't add explicit imports for auto-imported composables

## Error Handling

- try/catch with specific error messages
- Log errors appropriately
- Use "Milestone:" comments for significant code sections
