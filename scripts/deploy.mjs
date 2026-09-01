/* Публикация собранного сайта в ветку gh-pages.
   Запуск:  npm run deploy

   Почему не GitHub Actions: у токена нет права workflow, а расширять
   доступ ради одного стенда незачем. Исходник живёт в main, собранный
   сайт — отдельной веткой, как и у остальных клиентских сайтов.

   Файл .nojekyll обязателен: без него GitHub Pages пропускает каталоги,
   имя которых начинается с подчёркивания, а Astro складывает туда все
   стили, шрифты и картинки — сайт открылся бы без оформления. */

import { execFileSync } from 'node:child_process';
import { writeFileSync, existsSync } from 'node:fs';
import { join } from 'node:path';

const run = (cmd, args, opts = {}) =>
  execFileSync(cmd, args, { stdio: 'inherit', ...opts });

const repo = process.env.REPO_NAME || 'okonniy-zavod';
const owner = process.env.REPO_OWNER || 'grach5';

if (!existsSync('dist/index.html')) {
  console.error('Нет собранного сайта. Сначала: npm run build:pages');
  process.exit(1);
}

writeFileSync(join('dist', '.nojekyll'), '');

const url = `https://github.com/${owner}/${repo}.git`;
console.log(`Публикация в ${owner}/${repo}, ветка gh-pages…`);

run('git', ['init', '-q'], { cwd: 'dist' });
run('git', ['checkout', '-q', '-B', 'gh-pages'], { cwd: 'dist' });
run('git', ['add', '-A'], { cwd: 'dist' });
run('git', ['-c', 'user.name=grach5', '-c', 'user.email=gra4ik.asatryan@gmail.com',
            'commit', '-q', '-m', 'Сборка стенда'], { cwd: 'dist' });
run('git', ['push', '-q', '--force', url, 'gh-pages'], { cwd: 'dist' });

console.log(`Готово: https://${owner}.github.io/${repo}/`);
