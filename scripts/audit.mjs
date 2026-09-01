/* Проверка собранного сайта: мета, заголовки, ссылки, изображения.
   Запуск:  node scripts/audit.mjs
   Работает по dist/, то есть проверяет ровно то, что уедет на хостинг. */

import { readFileSync, readdirSync, statSync, existsSync } from 'node:fs';
import { join, relative } from 'node:path';

const DIST = 'dist';
/* Базовый путь сборки. На GitHub Pages сайт живёт в подпапке, и все
   ссылки начинаются с неё; без учёта этого проверка объявила бы
   битой каждую внутреннюю ссылку. */
const BASE = (process.env.BASE_PATH || '').trim().replace(/^\/+|\/+$/g, '');
const PREFIX = BASE ? '/' + BASE.split('/').filter(Boolean).pop() : '';
const pages = [];

function walk(dir) {
  for (const name of readdirSync(dir)) {
    const p = join(dir, name);
    if (statSync(p).isDirectory()) walk(p);
    else if (name.endsWith('.html')) pages.push(p);
  }
}
walk(DIST);

const problems = [];
const note = (page, kind, text) =>
  problems.push({ page: relative(DIST, page).replace(/\\/g, '/'), kind, text });

const grab = (html, re) => (html.match(re) || [])[1];
const all = (html, re) => [...html.matchAll(re)].map((m) => m[1]);

const routes = new Set(
  pages.map((p) => '/' + relative(DIST, p).replace(/\\/g, '/').replace(/index\.html$/, ''))
);

for (const page of pages) {
  const html = readFileSync(page, 'utf8');
  const isError = page.includes('404');

  const title = grab(html, /<title>([\s\S]*?)<\/title>/);
  if (!title) note(page, 'мета', 'нет <title>');
  else if (title.length > 65) note(page, 'мета', `title длиннее 65 знаков (${title.length})`);

  const desc = grab(html, /<meta\s+name="description"\s+content="([\s\S]*?)"/);
  if (!desc) note(page, 'мета', 'нет description');
  else if (desc.length > 175) note(page, 'мета', `description длиннее 175 знаков (${desc.length})`);

  if (!isError && !/rel="canonical"/.test(html)) note(page, 'мета', 'нет canonical');
  if (!isError && !/property="og:title"/.test(html)) note(page, 'мета', 'нет og:title');
  if (!/<html[^>]+lang="ru"/.test(html)) note(page, 'мета', 'нет lang="ru"');

  const h1 = all(html, /<h1[^>]*>([\s\S]*?)<\/h1>/g);
  if (h1.length === 0) note(page, 'структура', 'нет h1');
  if (h1.length > 1) note(page, 'структура', `h1 больше одного (${h1.length})`);

  for (const img of html.match(/<img[^>]*>/g) || []) {
    if (!/\salt[=\s>]/.test(img)) note(page, 'доступность', 'изображение без alt');
    if (!/\swidth="/.test(img) || !/\sheight="/.test(img))
      note(page, 'скорость', 'изображение без width/height — сдвиг макета');
  }

  // Изображения из public проверяем отдельно: у них абсолютный путь,
  // и в подпапке он ведёт в корень домена. Именно так на публикации
  // отвалились все фотографии в разделе «Работы».
  for (const src of all(html, /<img[^>]+src="(\/[^"?]*)"/g)) {
    if (src.startsWith('/_astro/')) continue;
    const rel = PREFIX && src.startsWith(PREFIX + '/') ? src.slice(PREFIX.length) : src;
    if (PREFIX && !src.startsWith(PREFIX + '/'))
      note(page, 'изображения', `путь мимо базового: ${src}`);
    else if (!existsSync(join(DIST, rel.replace(/^\//, ''))))
      note(page, 'изображения', `файла нет: ${src}`);
  }

  for (const raw of all(html, /href="(\/[^"#?]*)"/g)) {
    if (PREFIX && !raw.startsWith(PREFIX + '/') && raw !== PREFIX) {
      note(page, 'ссылки', `ссылка мимо базового пути: ${raw}`);
      continue;
    }
    const href = PREFIX ? raw.slice(PREFIX.length) || '/' : raw;
    const clean = href.endsWith('/') ? href : href + '/';
    const asFile = join(DIST, href.replace(/^\//, ''));
    const known = routes.has(clean) || routes.has(href) || existsSync(asFile);
    if (!known) {
      note(page, 'ссылки', `битая внутренняя ссылка ${href}`);
      continue;
    }
    // В конфиге trailingSlash: 'never'. Ссылка со слэшем на конце
    // существует в dist как каталог, но сервер по такому адресу отдаст
    // 404 — поэтому проверяем отдельно, иначе ошибка проходит незаметно.
    if (href !== '/' && href.endsWith('/'))
      note(page, 'ссылки', `лишний слэш на конце: ${href}`);
  }
}

console.log(`страниц проверено: ${pages.length}`);
if (!problems.length) {
  console.log('замечаний нет');
} else {
  const byKind = {};
  for (const p of problems) (byKind[p.kind] ||= []).push(p);
  for (const [kind, list] of Object.entries(byKind)) {
    console.log(`\n${kind.toUpperCase()} — ${list.length}`);
    const seen = new Set();
    for (const p of list) {
      const key = p.page + p.text;
      if (seen.has(key)) continue;
      seen.add(key);
      console.log(`  ${p.page.padEnd(46)} ${p.text}`);
    }
  }
  process.exitCode = 1;
}
