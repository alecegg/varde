// Contents nav: scroll-spy sets aria-current="location" on the link of the
// heading nearest above the top of the page, and the <details> stays open from
// 64rem (the rail). ES module loaded by app.js; without it the links are plain anchors.
const RAIL_MIN_WIDTH = 64 * 16;

export function mountToc(root = document) {
  const nav = root.querySelector('nav.doc-toc');
  if (!nav) return;
  const links = Array.from(nav.querySelectorAll('a[href^="#h-"]'));
  const heads = links.map((a) => root.getElementById(a.getAttribute('href').slice(1)));
  keepOpenOnRail(nav);
  if (!('IntersectionObserver' in window)) return;
  const above = new Set();
  const mark = () => {
    let active = -1;
    heads.forEach((h, i) => { if (h && above.has(h)) active = i; });
    links.forEach((a, i) => {
      if (i === active) a.setAttribute('aria-current', 'location');
      else a.removeAttribute('aria-current');
    });
  };
  const observer = new IntersectionObserver((entries) => {
    for (const e of entries) {
      const passed = !e.isIntersecting && e.boundingClientRect.top < 0;
      if (e.isIntersecting || passed) above.add(e.target);
      else above.delete(e.target);
    }
    mark();
  }, { rootMargin: '0px 0px -75% 0px' });
  heads.forEach((h) => { if (h) observer.observe(h); });
}

function keepOpenOnRail(nav) {
  const details = nav.querySelector('details');
  const main = nav.closest('main');
  if (!details || !main || !('ResizeObserver' in window)) return;
  new ResizeObserver(() => {
    if (main.clientWidth >= RAIL_MIN_WIDTH) details.open = true;
  }).observe(main);
}
