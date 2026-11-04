// image: opens the picture in a native <dialog> when its link is activated. The figure is
// complete without this script (the link opens the file). Escape closes the dialog and the
// Close button is at least 44px; the page's own markup supplies the alt text and the file.
import { control, make } from './dom.js';

function zoom(small) {
  const dialog = make('dialog', 'vd-image-dialog');
  dialog.setAttribute('aria-label', small.alt);
  const close = control('Close', () => dialog.close(), 'vd-image-close');
  const big = make('img', 'vd-image-zoomed');
  big.src = small.currentSrc || small.src;
  big.alt = small.alt;
  dialog.append(close, big);
  dialog.addEventListener('close', () => dialog.remove());
  document.body.appendChild(dialog);
  dialog.showModal();
}

export function enhanceImage(block) {
  if (!block.classList.contains('vd-image') || typeof HTMLDialogElement === 'undefined') return;
  const link = block.querySelector('a.vd-image-link');
  const small = link && link.querySelector('img');
  if (!small) return;
  link.addEventListener('click', (event) => {
    if (event.button !== 0 || event.ctrlKey || event.metaKey || event.shiftKey) return;
    event.preventDefault();
    zoom(small);
  });
}
