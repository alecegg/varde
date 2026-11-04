async (cap) => {
  if (document.fonts && document.fonts.ready) {
    await Promise.race([document.fonts.ready, new Promise((done) => setTimeout(done, 1500))]);
  }
  const canvas = document.createElement('canvas');
  canvas.width = canvas.height = 1;
  const ctx = canvas.getContext('2d', {willReadFrequently: true});
  const rgba = (css) => {
    ctx.clearRect(0, 0, 1, 1);
    ctx.fillStyle = '#000';
    ctx.fillStyle = css;
    ctx.fillRect(0, 0, 1, 1);
    const d = ctx.getImageData(0, 0, 1, 1).data;
    return 'rgba(' + d[0] + ', ' + d[1] + ', ' + d[2] + ', ' + (d[3] / 255).toFixed(3) + ')';
  };
  const selector = (el) => {
    const parts = [];
    for (let n = el; n && n.nodeType === 1 && parts.length < 4; n = n.parentElement) {
      let part = n.tagName.toLowerCase();
      if (n.id) { parts.push(part + '#' + n.id); break; }
      const cls = (n.getAttribute('class') || '').trim().split(/\s+/).filter(Boolean)[0];
      if (cls) part += '.' + cls;
      parts.push(part);
    }
    return parts.reverse().join(' > ');
  };
  window.__vardeSelector = selector;
  const shown = (el) => {
    const s = getComputedStyle(el);
    const r = el.getBoundingClientRect();
    return s.display !== 'none' && s.visibility === 'visible' && r.width > 0 && r.height > 0;
  };
  const backdrop = (el) => {
    const layers = [];
    let image = 'none';
    let stops = [];
    for (let n = el; n; n = n.parentElement) {
      const s = getComputedStyle(n);
      if (s.backgroundImage !== 'none' && image === 'none') {
        image = s.backgroundImage.includes('gradient(') ? 'gradient' : 'image';
        stops = (s.backgroundImage.match(/(?:rgba?|oklch|oklab|lab|lch|color|hsla?)\([^()]*(?:\([^()]*\)[^()]*)*\)/g) || []).map(rgba);
      }
      const bg = rgba(s.backgroundColor);
      if (!bg.endsWith(', 0.000)')) layers.push(bg);
      if (bg.endsWith(', 1.000)')) break;
    }
    return {layers, image, stops};
  };
  const all = Array.from(document.body ? document.body.querySelectorAll('*') : []);
  const texts = [];
  const controls = [];
  const controlSel = 'a[href],button,input:not([type=hidden]),select,textarea,summary,[role=button],[role=link],[tabindex]:not([tabindex="-1"])';
  let total = 0;
  for (const el of all) {
    const own = Array.from(el.childNodes).some((c) => c.nodeType === 3 && c.textContent.trim());
    const isControl = el.matches(controlSel);
    if (!own && !isControl) continue;
    if (!shown(el)) continue;
    total += 1;
    if (texts.length + controls.length >= cap) continue;
    const s = getComputedStyle(el);
    // A bare checkbox or radio is tapped through its label, so measure that.
    const box = el.matches('input[type=checkbox],input[type=radio]') && el.labels && el.labels[0] ? el.labels[0] : el;
    const r = box.getBoundingClientRect();
    if (own) {
      texts.push({
        selector: selector(el),
        text: el.textContent.trim().slice(0, 40),
        color: rgba(s.color),
        font_px: parseFloat(s.fontSize),
        weight: parseInt(s.fontWeight, 10) || 400,
        font_family: s.fontFamily,
        backdrop: backdrop(el),
      });
    }
    if (isControl) {
      controls.push({
        selector: selector(el),
        tag: el.tagName.toLowerCase(),
        width: r.width,
        height: r.height,
        inline: s.display === 'inline',
      });
    }
  }

  // Text line fragments: one top per visual line, so a count of lines.
  const textRects = (el) => {
    const walker = document.createTreeWalker(el, NodeFilter.SHOW_TEXT);
    const range = document.createRange();
    const tops = [];
    for (let n = walker.nextNode(); n; n = walker.nextNode()) {
      range.selectNodeContents(n);
      for (const r of range.getClientRects()) if (r.width > 0) tops.push(r.top);
    }
    return tops.sort((a, b) => a - b);
  };
  const lineCount = (el, size) => {
    const lines = [];
    for (const t of textRects(el)) if (!lines.length || t - lines[lines.length - 1] > size * 0.5) lines.push(t);
    return lines.length;
  };
  // Characters on the first visual line, counted up to a cap.
  const firstLineChars = (el, size) => {
    const walker = document.createTreeWalker(el, NodeFilter.SHOW_TEXT);
    const range = document.createRange();
    let count = 0;
    let top = null;
    for (let n = walker.nextNode(); n; n = walker.nextNode()) {
      for (let i = 0; i < n.data.length; i++) {
        range.setStart(n, i);
        range.setEnd(n, i + 1);
        const r = range.getClientRects()[0];
        if (!r || r.width === 0) continue;
        if (top === null) top = r.top;
        else if (r.top - top > size * 0.5) return count;
        count += 1;
        if (count >= 200) return count;
      }
    }
    return count;
  };
  const GENERIC = ['serif', 'sans-serif', 'monospace', 'cursive', 'fantasy', 'system-ui',
    'ui-serif', 'ui-sans-serif', 'ui-monospace', 'ui-rounded', 'emoji', 'math', 'fangsong',
    '-apple-system', 'blinkmacsystemfont'];
  const firstFamily = (stack) => stack.split(',')[0].trim().replace(/^["']|["']$/g, '');
  const SAMPLE = 'mmmmmmmmmmlli1WwQq';
  const widthIn = (font) => {
    ctx.font = '72px ' + font;
    return ctx.measureText(SAMPLE).width;
  };
  // true when the first family renders differently from every generic fallback.
  const renders = (name) =>
    ['monospace', 'serif', 'sans-serif'].some((g) => Math.abs(widthIn('"' + name + '", ' + g) - widthIn(g)) > 0.01);
  const fonts = [];
  const seenStacks = new Map();
  for (const t of texts) {
    if (seenStacks.has(t.font_family)) { seenStacks.get(t.font_family).count += 1; continue; }
    const first = firstFamily(t.font_family);
    const entry = {
      selector: t.selector, stack: t.font_family.slice(0, 120), first, count: 1,
      available: GENERIC.includes(first.toLowerCase()) ? null : renders(first),
    };
    seenStacks.set(t.font_family, entry);
    if (fonts.length < 20) fonts.push(entry);
  }
  const headings = [];
  for (const el of Array.from(document.querySelectorAll('h1')).filter(shown).slice(0, 10)) {
    const size = parseFloat(getComputedStyle(el).fontSize);
    headings.push({selector: selector(el), text: el.textContent.trim().slice(0, 40), lines: lineCount(el, size)});
  }
  const paragraphs = [];
  const exempt = 'li,td,th,dd,dt,button,label,nav,summary,[role=button]';
  const reading = Array.from(document.querySelectorAll('p')).filter((el) => shown(el) && !el.closest(exempt));
  for (const el of reading.slice(0, 40)) {
    const size = parseFloat(getComputedStyle(el).fontSize);
    const text = el.textContent.replace(/\s+/g, ' ').trim();
    paragraphs.push({
      selector: selector(el), chars: text.length,
      sentences: (text.match(/[.!?](\s|$)/g) || []).length,
      lines: lineCount(el, size), first_line_chars: firstLineChars(el, size),
    });
  }
  const doc = document.documentElement;
  return {
    doc: {scroll_width: doc.scrollWidth, client_width: doc.clientWidth},
    texts, controls, fonts, headings, paragraphs,
    truncated: total > cap ? {shown: cap, total} : null,
  };
}
