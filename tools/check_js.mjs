// Проверка синтаксиса всех клиентских JS (ES-модули) без сборки: node tools/check_js.mjs
// Ловит опечатки, которые иначе всплывут только в браузере (например, сломанная шаблонная строка).
import { readdirSync, readFileSync, statSync } from 'node:fs';
import { join, relative } from 'node:path';
import vm from 'node:vm';

const root = new URL('..', import.meta.url).pathname.replace(/^\/([A-Za-z]:)/, '$1');
const skip = new Set(['vendor']);
let bad = 0;
let n = 0;

function walk(dir) {
  for (const name of readdirSync(dir)) {
    const p = join(dir, name);
    if (statSync(p).isDirectory()) {
      if (!skip.has(name)) walk(p);
    } else if (name.endsWith('.js') || name.endsWith('.mjs')) {
      n++;
      try {
        new vm.SourceTextModule(readFileSync(p, 'utf8'), { identifier: p });
      } catch (e) {
        bad++;
        console.log(`ОШИБКА ${relative(root, p)}: ${e.message}`);
      }
    }
  }
}

// встроенные <script type="module"> в html тоже проверяем
function walkHtml(dir) {
  for (const name of readdirSync(dir)) {
    const p = join(dir, name);
    if (statSync(p).isDirectory()) {
      if (!skip.has(name)) walkHtml(p);
    } else if (name.endsWith('.html')) {
      const html = readFileSync(p, 'utf8');
      for (const m of html.matchAll(/<script type="module">([\s\S]*?)<\/script>/g)) {
        n++;
        try {
          new vm.SourceTextModule(m[1], { identifier: p });
        } catch (e) {
          bad++;
          console.log(`ОШИБКА ${relative(root, p)} (встроенный скрипт): ${e.message}`);
        }
      }
    }
  }
}

walk(join(root, 'web'));
walkHtml(join(root, 'web'));
console.log(`Проверено ${n} скриптов, ошибок: ${bad}`);
process.exit(bad ? 1 : 0);
