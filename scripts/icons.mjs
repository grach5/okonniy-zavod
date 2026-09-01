/* Иконки из одного SVG: 32×32 для вкладки, 180×180 для iOS,
   192 и 512 для манифеста. iOS не понимает SVG в apple-touch-icon,
   поэтому растр обязателен — иначе на домашнем экране будет пустой квадрат. */
import sharp from 'sharp';
import { readFileSync, writeFileSync } from 'node:fs';

const svg = readFileSync('public/favicon.svg');
const sizes = [
  ['icon-32.png', 32],
  ['apple-touch-icon.png', 180],
  ['icon-192.png', 192],
  ['icon-512.png', 512],
];

for (const [file, n] of sizes) {
  await sharp(svg, { density: 512 })
    .resize(n, n)
    .flatten({ background: '#0A0A0C' })
    .png({ compressionLevel: 9 })
    .toFile('public/' + file);
  console.log(`${file.padEnd(24)} ${n}×${n}`);
}

writeFileSync(
  'public/site.webmanifest',
  JSON.stringify(
    {
      name: 'Оконный завод — окна ПВХ во Владивостоке и Артёме',
      short_name: 'Оконный завод',
      lang: 'ru',
      start_url: '/',
      display: 'minimal-ui',
      background_color: '#F7F5F1',
      theme_color: '#F7F5F1',
      icons: [
        { src: '/icon-192.png', sizes: '192x192', type: 'image/png' },
        { src: '/icon-512.png', sizes: '512x512', type: 'image/png' },
        { src: '/favicon.svg', sizes: 'any', type: 'image/svg+xml' },
      ],
    },
    null,
    2
  ) + '\n'
);
console.log('site.webmanifest         записан');
