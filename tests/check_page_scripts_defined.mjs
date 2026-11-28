import { readFile } from 'node:fs/promises';
import { createRequire } from 'node:module';

const require = createRequire(new URL('./page-script-tools/package.json', import.meta.url));
const { Linter } = require('eslint');
const globals = require('globals');

const staticDir = new URL('../studioos/static/', import.meta.url);
const index = await readFile(new URL('index.html', staticDir), 'utf8');
const scripts = Array.from(index.matchAll(/<script\b[^>]*\bsrc=["']\/static\/([^"']+)["']/g), match => match[1]);
if (!scripts.length) throw new Error('No page scripts found in index.html');

const files = await Promise.all(scripts.map(async (name) => ({
  name,
  source: await readFile(new URL(name, staticDir), 'utf8'),
})));
const combined = files.map(({source}) => source).join('\n;\n');
const result = new Linter().verify(combined, {
  languageOptions: {sourceType: 'script', ecmaVersion: 'latest', globals: globals.browser},
  rules: {'no-undef': ['error', {typeof: false}]},
});

const known = new Set([
  'openCreate', 'setScope',
]);
const seen = new Set();
for (const message of result) {
  const name = /^'([^']+)' is not defined\.$/.exec(message.message)?.[1];
  if (message.ruleId === 'no-undef' && known.has(name)) {
    seen.add(name);
    continue;
  }
  let line = message.line || 1;
  const file = files.find(({source}) => {
    const count = source.split('\n').length + 1;
    if (line <= count) return true;
    line -= count;
    return false;
  });
  console.error(`${file?.name ?? 'index.html'}:${line}:${message.column || 1}: ${message.message}`);
  process.exitCode = 1;
}
for (const name of known) {
  if (seen.has(name)) continue;
  console.error(`Remove the stale undefined name from the exception list: ${name}`);
  process.exitCode = 1;
}
