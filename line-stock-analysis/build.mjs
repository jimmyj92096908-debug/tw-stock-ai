import { build } from 'esbuild';

await build({
  entryPoints: ['index.mjs'],
  platform: 'node',
  target: 'node24',
  format: 'esm',
  bundle: true,
  external: ['pg-native'],
  outfile: 'dist/index.mjs',
  // pg uses CommonJS internally; preserve safe Node builtin require bridging.
  banner: {
    js: "import { createRequire } from 'node:module'; const require = createRequire(import.meta.url);"
  },
  logLevel: 'info',
});
