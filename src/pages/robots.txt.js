/* robots.txt собирается на сборке, а не лежит статикой.
   Причина: на демонстрационном стенде он должен запрещать обход
   целиком, а на боевом домене — разрешать и указывать карту сайта.
   Один файл с жёстко прописанным адресом обслуживал бы только один
   из двух случаев и молча врал бы во втором. */

const DEMO = import.meta.env.PUBLIC_DEMO === '1';

export function GET({ site }) {
  const base = String(site).replace(/\/$/, '');

  const body = DEMO
    ? [
        '# Демонстрационный стенд. Обход запрещён:',
        '# копия с реальными реквизитами не должна попасть в поиск.',
        'User-agent: *',
        'Disallow: /',
        '',
      ].join('\n')
    : [
        'User-agent: *',
        'Allow: /',
        'Disallow: /spasibo',
        '',
        `Sitemap: ${base}/sitemap-index.xml`,
        `Host: ${base}`,
        '',
      ].join('\n');

  return new Response(body, {
    headers: { 'Content-Type': 'text/plain; charset=utf-8' },
  });
}
