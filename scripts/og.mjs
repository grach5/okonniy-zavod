/* Генератор превью для мессенджеров и соцсетей (Open Graph, 1200×630).
   Запуск:  node scripts/og.mjs

   Зачем отдельным скриптом, а не на лету: превью запрашивают роботы
   WhatsApp, Telegram и поисковиков, им нужен готовый статический файл по
   постоянному адресу. Генерируем один раз и кладём в public/.

   Основа — те же визуализации, что стоят на сайте, плюс затемнение и
   набор. Текст рисуем через SVG: своих шрифтов у sharp нет, поэтому
   берём засечный системный стек — в превью это не критично, а внешних
   зависимостей не добавляет. */

import sharp from 'sharp';
import { mkdirSync } from 'node:fs';
import { join } from 'node:path';

const W = 1200;
const H = 630;
const SRC = 'src/assets/vis';
const OUT = 'public';

mkdirSync(OUT, { recursive: true });

/* Экранирование: амперсанд или кавычка в заголовке ломает SVG молча,
   и превью собирается пустым. */
const esc = (s) =>
  String(s)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');

/* Перенос по словам: длинный заголовок иначе уезжает за край кадра. */
function wrap(text, max) {
  const words = String(text).split(/\s+/);
  const lines = [];
  let line = '';
  for (const w of words) {
    if ((line + ' ' + w).trim().length > max && line) {
      lines.push(line.trim());
      line = w;
    } else {
      line = (line + ' ' + w).trim();
    }
  }
  if (line) lines.push(line);
  return lines;
}

function overlay({ kicker, title, note }) {
  const lines = wrap(title, 26).slice(0, 3);
  const size = lines.length > 2 ? 72 : 86;
  const top = H - 96 - lines.length * (size * 1.06) - (note ? 46 : 0);

  const body = lines
    .map(
      (l, i) =>
        `<text x="72" y="${top + (i + 1) * size * 1.06}" class="t">${esc(l)}</text>`
    )
    .join('');

  return Buffer.from(`<svg xmlns="http://www.w3.org/2000/svg" width="${W}" height="${H}">
  <defs>
    <linearGradient id="scrim" x1="0" y1="1" x2="0" y2="0">
      <stop offset="0%"   stop-color="#0A0A0B" stop-opacity="0.94"/>
      <stop offset="44%"  stop-color="#0A0A0B" stop-opacity="0.72"/>
      <stop offset="80%"  stop-color="#0A0A0B" stop-opacity="0.14"/>
      <stop offset="100%" stop-color="#0A0A0B" stop-opacity="0.06"/>
    </linearGradient>
    <linearGradient id="side" x1="0" y1="0" x2="1" y2="0">
      <stop offset="0%"   stop-color="#0A0A0B" stop-opacity="0.62"/>
      <stop offset="58%"  stop-color="#0A0A0B" stop-opacity="0.10"/>
      <stop offset="100%" stop-color="#0A0A0B" stop-opacity="0"/>
    </linearGradient>
  </defs>
  <style>
    .t { font-family: Georgia, "Times New Roman", serif; font-size: ${size}px;
         font-weight: 700; fill: #F5F2EC; letter-spacing: -0.5px; }
    .k { font-family: "Courier New", monospace; font-size: 21px; font-weight: 700;
         fill: #F0C88C; letter-spacing: 3.4px; }
    .n { font-family: Georgia, serif; font-size: 27px; fill: #ADA79D; }
  </style>
  <rect width="${W}" height="${H}" fill="url(#side)"/>
  <rect width="${W}" height="${H}" fill="url(#scrim)"/>
  <rect x="72" y="${top - 46}" width="64" height="3" fill="#F0C88C"/>
  <text x="72" y="${top - 16}" class="k">${esc(kicker).toUpperCase()}</text>
  ${body}
  ${note ? `<text x="72" y="${H - 62}" class="n">${esc(note)}</text>` : ''}
</svg>`);
}

const cards = [
  {
    file: 'og-default.png',
    img: 'panorama-rassvet.png',
    kicker: 'Оконный завод · Артём',
    title: 'Окна от производителя',
    note: 'Владивосток · Артём · Находка · от 6 900 ₽ за м²',
  },
  {
    file: 'og-uslugi.png',
    img: 'balkonniy-blok.png',
    kicker: 'Направления',
    title: 'Шесть направлений, каждое со своим расчётом',
    note: 'Окна, двери, балконы, дома, панорамы, алюминий',
  },
  {
    file: 'og-goroda.png',
    img: 'interier-obshiy.png',
    kicker: 'География',
    title: 'Работаем в четырёх городах Приморья',
    note: 'Свой цех в Артёме · замер бесплатно',
  },
  {
    file: 'og-ceny.png',
    img: 'panorama-stvorka.png',
    kicker: 'Цены',
    title: 'Смета по пунктам, без «прочих работ»',
    note: 'Расчёт до договора · монтаж по ГОСТ 30971',
  },
];

for (const c of cards) {
  // Кадрируем по центру, а не «по вниманию»: автоматика выбирает самый
  // контрастный участок и на этих кадрах цепляется за тёмный простенок
  // вместо вида в окне. Плюс поднимаем яркость — под затемнением
  // исходник уходит в грязь.
  const base = await sharp(join(SRC, c.img))
    .resize(W, H, { fit: 'cover', position: c.crop || 'center' })
    .modulate({ brightness: 1.16 })
    .toBuffer();

  await sharp(base)
    .composite([{ input: overlay(c), top: 0, left: 0 }])
    .png({ quality: 92, compressionLevel: 9 })
    .toFile(join(OUT, c.file));

  console.log(`${c.file.padEnd(20)} ${c.title}`);
}

console.log(`\nготово: ${cards.length} превью 1200×630 в ${OUT}/`);
