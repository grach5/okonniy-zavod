import { defineConfig } from 'astro/config';
import sitemap from '@astrojs/sitemap';

/* Адрес сайта берётся из окружения.
   На демонстрационном стенде он обязан совпадать с фактическим: иначе
   canonical и карта сайта будут указывать на okonniyzavod.ru, то есть
   на чужой домен, и поисковик получит противоречивые сигналы. */
const SITE = process.env.SITE_URL || 'https://okonniyzavod.ru';

/* Базовый путь: '/' в корне домена, '/имя-репозитория/' на GitHub
   Pages. Всё внутреннее собирается через src/lib/url.js.

   Значение принимаем в любом виде: okonniy-zavod, /okonniy-zavod,
   /okonniy-zavod/. Git Bash под Windows подставляет вместо ведущего
   слеша путь к своей файловой системе, и переменная приезжает как
   C:/Program Files/Git/okonniy-zavod — поэтому берём только последний
   сегмент и обрамляем слешами сами. */
const RAW = (process.env.BASE_PATH || '').trim().replace(/^\/+|\/+$/g, '');
const BASE = RAW ? '/' + RAW.split('/').filter(Boolean).pop() + '/' : '/';

export default defineConfig({
  site: SITE,
  base: BASE,
  trailingSlash: 'never',
  integrations: [sitemap({ changefreq: 'weekly', priority: 0.7 })],
  build: { inlineStylesheets: 'auto' },
  compressHTML: true,
  prefetch: { prefetchAll: true, defaultStrategy: 'viewport' },
});
