/* Сборка под GitHub Pages.
   Запуск:  npm run build:pages

   Переменные окружения задаются здесь, а не в строке npm-скрипта:
   синтаксис VAR=value работает в POSIX-оболочках, но не в PowerShell,
   а проект собирают под Windows. */

import { execFileSync } from 'node:child_process';

const owner = process.env.REPO_OWNER || 'grach5';
const repo = process.env.REPO_NAME || 'okonniy-zavod';

execFileSync('npx', ['astro', 'build'], {
  stdio: 'inherit',
  shell: true,
  env: {
    ...process.env,
    BASE_PATH: repo,
    SITE_URL: `https://${owner}.github.io/${repo}`,
    // Стенд закрыт от индексации: копия с реальными реквизитами завода,
    // но расчётными ценами не должна попасть в поиск.
    PUBLIC_DEMO: '1',
  },
});
