/* Внутренние адреса с учётом базового пути.

   Сайт разворачивается и в корне домена, и в подпапке — на GitHub Pages
   адрес выглядит как grach5.github.io/имя-репозитория/. Абсолютная
   ссылка вида /ceny в подпапке ведёт в корень домена, то есть в никуда,
   и обнаруживается это только после публикации. Поэтому все внутренние
   ссылки собираются через эту функцию.

   Astro подставляет BASE_URL из поля base в конфигурации: '/' по
   умолчанию и '/имя/' при сборке под подпапку. */

const BASE = String(import.meta.env.BASE_URL || '/').replace(/\/+$/, '');

/** Внутренний адрес: url('/ceny') → '/ceny' или '/имя-репозитория/ceny' */
export function url(path = '/') {
  if (!path.startsWith('/')) return path;   // внешние и якорные не трогаем
  return path === '/' ? BASE + '/' : BASE + path;
}

/** Путь текущей страницы без базовой части — для подсветки активного пункта */
export function stripBase(pathname) {
  const p = BASE && pathname.startsWith(BASE) ? pathname.slice(BASE.length) : pathname;
  return p.replace(/\/$/, '') || '/';
}
