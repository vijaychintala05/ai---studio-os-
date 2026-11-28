import { readFile, readdir } from 'node:fs/promises';
import { createRequire } from 'node:module';
import { pathToFileURL } from 'node:url';

const require = createRequire(new URL('./page-script-tools/package.json', import.meta.url));
const { Linter } = require('eslint');
const staticDir = new URL('../studioos/static/', import.meta.url);
const fixtures = new URL('./fixtures/', import.meta.url);
const methods = new Set(['POST', 'PUT', 'PATCH', 'DELETE']);
const bodyWrappers = new Set(['gApi', 'ibApi', 'imApi', 'nwApi', 'rsApi', 'vApi']);
const postWrappers = new Set(['gkDraft', 'mtPost', 'toPost']);
const marker = '{value}';

function propertyName(property) {
  return property.computed ? property.key.value : property.key.name ?? property.key.value;
}

export function collectWriteCalls(source, output = new Set()) {
  const rule = {create(context) {
    function binding(node) {
      for (let scope = context.sourceCode.getScope(node); scope; scope = scope.upper) {
        const variable = scope.set.get(node.name);
        if (!variable) continue;
        return variable.defs.length === 1 && !variable.references.some(ref => ref.isWrite() && !ref.init)
          ? variable.defs[0] : null;
      }
      return null;
    }

    function definition(node) {
      const def = binding(node);
      return def?.type === 'Variable' ? def.node.init : null;
    }

    // Read tuple members returned by a local dispatcher such as salesDraft().
    function returnedElements(call, index) {
      if (call?.type !== 'CallExpression' || call.callee.type !== 'Identifier') return [];
      const fn = binding(call.callee);
      if (fn?.type !== 'FunctionName') return [];
      const elements = [];
      function visit(node) {
        if (!node || node.type.includes('Function')) return;
        if (node.type === 'ReturnStatement') {
          const add = argument => {
            if (argument?.type === 'ArrayExpression') elements.push(argument.elements[index]);
            if (argument?.type === 'ConditionalExpression') {
              add(argument.consequent);
              add(argument.alternate);
            }
          };
          add(node.argument);
        }
        for (const key of context.sourceCode.visitorKeys[node.type] ?? []) {
          if (Array.isArray(node[key])) node[key].forEach(visit);
          else visit(node[key]);
        }
      }
      visit(fn.node.body);
      return elements;
    }

    function branchValues(node) {
      const scope = binding(node);
      function choices(test) {
        if (test.type === 'LogicalExpression' && test.operator === '||') {
          const left = choices(test.left), right = choices(test.right);
          return left.length && right.length ? [...left, ...right] : [];
        }
        if (test.type === 'BinaryExpression' && test.operator === '===' &&
            test.left.type === 'Identifier' && test.left.name === node.name && binding(test.left) === scope &&
            test.right.type === 'Literal' && typeof test.right.value === 'string') return [test.right.value];
        return [];
      }
      for (let child = node, parent = node.parent; parent; child = parent, parent = parent.parent) {
        if (parent.type !== 'IfStatement' || child !== parent.consequent) continue;
        const possible = choices(parent.test);
        if (possible.length) return possible;
      }
      return [];
    }

    function values(node, remaining = 7) {
      if (!node || !remaining) return [];
      const get = child => values(child, remaining - 1);
      const combine = (left, right) => left.flatMap(a => right.map(b => a + b));
      const dynamic = child => {
        const result = get(child);
        return result.length ? result : [marker];
      };
      if (node.type === 'Literal' && typeof node.value === 'string') return [node.value];
      if (node.type === 'Identifier') {
        const bounded = branchValues(node);
        if (bounded.length) return bounded;
        const def = binding(node);
        if (def?.type === 'Variable' && def.node.id.type === 'ArrayPattern') {
          const index = def.node.id.elements.indexOf(def.name);
          return index < 0 ? [] : returnedElements(def.node.init, index).flatMap(get);
        }
        return get(definition(node));
      }
      if (node.type === 'ConditionalExpression') return [...get(node.consequent), ...get(node.alternate)];
      if (node.type === 'BinaryExpression' && node.operator === '+') {
        return combine(dynamic(node.left), dynamic(node.right));
      }
      if (node.type === 'TemplateLiteral') {
        let result = [node.quasis[0].value.cooked];
        for (const [i, expr] of node.expressions.entries()) {
          result = combine(result, dynamic(expr)).map(value => value + node.quasis[i + 1].value.cooked);
        }
        return result;
      }
      if (node.type === 'MemberExpression' && node.object.type === 'Identifier') {
        const object = definition(node.object);
        if (object?.type !== 'ObjectExpression') return [];
        const keys = node.computed ? get(node.property) : [node.property.name];
        return object.properties.filter(p => p.type === 'Property' && (!keys.length || keys.includes(propertyName(p))))
          .flatMap(p => get(p.value));
      }
      return [];
    }

    return {CallExpression(node) {
      const { name } = node.callee;
      const [url, options, override] = node.arguments;
      let verbs = [];
      if (name === 'api' || name === 'fetch') {
        const object = options?.type === 'Identifier' ? definition(options) : options;
        const method = object?.type === 'ObjectExpression'
          ? object.properties.find(p => p.type === 'Property' && propertyName(p) === 'method')
          : null;
        verbs = values(method?.value);
      } else if (postWrappers.has(name) || (bodyWrappers.has(name) && options &&
                 !(options.type === 'Literal' && !options.value))) {
        verbs = ['POST'];
      } else if (name === 'paPost') {
        verbs = override ? values(override) : ['POST'];
      } else if (name === 'aiApi' && override) {
        verbs = values(options);
      }
      for (const verb of verbs.filter(method => methods.has(method))) {
        for (const path of values(url)) {
          if (path.startsWith('/api/')) output.add(verb + ' ' + path.split(/[?#]/)[0]);
        }
      }
    }};
  }};
  const diagnostics = new Linter().verify(source, {
    languageOptions: {sourceType: 'script', ecmaVersion: 'latest'},
    plugins: {studioos: {rules: {calls: rule}}},
    rules: {'studioos/calls': 'error'},
  });
  if (diagnostics.length) throw new Error(diagnostics.map(item => item.message).join('\n'));
  return output;
}

export function covered(route, calls) {
  const pattern = route.split(/\{[^}]+\}/).map(part => part.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')).join('[^/]+');
  const match = new RegExp('^' + pattern + '/?$');
  return [...calls].some(call => match.test(call));
}

async function main() {
  const calls = new Set();
  for (const name of await readdir(staticDir)) {
    if (name.endsWith('.js')) collectWriteCalls(await readFile(new URL(name, staticDir), 'utf8'), calls);
  }
  const snapshot = JSON.parse(await readFile(new URL('api_surface.json', fixtures), 'utf8'));
  const routes = snapshot.registration_order.flatMap(entry => {
    const words = entry.split(' ');
    const path = words.pop();
    return path.startsWith('/api/') ? words.filter(method => methods.has(method)).map(method => method + ' ' + path) : [];
  });
  const baseline = JSON.parse(await readFile(new URL('api_only_routes.json', fixtures), 'utf8')).routes;
  const missing = new Set(routes.filter(route => !covered(route, calls)));
  for (const route of missing) {
    if (baseline[route]?.trim()) continue;
    console.error(`Write route has no frontend call or documented exception: ${route}`);
    process.exitCode = 1;
  }
  for (const route of Object.keys(baseline)) {
    if (missing.has(route)) continue;
    console.error(`Remove the stale write-route exception: ${route}`);
    process.exitCode = 1;
  }
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) await main();
