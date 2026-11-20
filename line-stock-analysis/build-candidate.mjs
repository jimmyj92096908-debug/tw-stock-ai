// Build only. Does not deploy, attach credentials, update LINE settings,
// or replace the existing line-stock-analysis/dist/index.mjs artifact.
import { build } from 'esbuild';

await build({
  entryPoints:['single-account-entry.mjs'],
  platform:'node',
  target:'node24',
  format:'esm',
  bundle:true,
  external:['pg-native'],
  outfile:'candidate-dist/index.mjs',
  banner:{
    js:"import { createRequire } from 'node:module'; const require = createRequire(import.meta.url);"
  },
  logLevel:'info'
});
