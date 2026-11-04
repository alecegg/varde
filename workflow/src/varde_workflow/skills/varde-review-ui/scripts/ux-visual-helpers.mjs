import path from 'node:path';
import { inflateSync } from 'node:zlib';

export function tileGrid(width, height, maxWidth, maxHeight, overlap = 0, columnAnchor = 0) {
  if (![width, height, maxWidth, maxHeight].every(Number.isFinite)
      || width <= 0 || height <= 0 || maxWidth <= 0 || maxHeight <= 0
      || !Number.isFinite(overlap) || overlap < 0 || overlap >= maxWidth
      || !Number.isFinite(columnAnchor) || columnAnchor < 0 || columnAnchor >= maxWidth) {
    throw new RangeError('Image and tile dimensions must be positive numbers');
  }
  const tiles = [];
  if (overlap) {
    const columns = Math.ceil(width / maxWidth);
    const rows = Math.ceil(height / maxHeight);
    const yStep = rows > 1 ? (height - maxHeight) / (rows - 1) : 0;
    for (let row = 0; row < rows; row += 1) for (let column = 0; column < columns; column += 1) {
      const x = column === 0 ? 0 : Math.min(width - maxWidth, columnAnchor + (column - 1) * (maxWidth - overlap));
      const y = Math.round(row * yStep);
      tiles.push({ x, y, width: Math.min(maxWidth, width - x), height: Math.min(maxHeight, height - y), row, column });
    }
    return tiles;
  }
  for (let y = 0, row = 0; y < height; y += maxHeight, row += 1) {
    const remaining = height - y;
    if (remaining < 200 && tiles.length) {
      const previousRow = tiles.at(-1).row;
      while (tiles.length && tiles.at(-1).row === previousRow) tiles.pop();
      const lastRowY = height - maxHeight;
      for (let x = 0, column = 0; x < width; column += 1) {
        tiles.push({ x, y: lastRowY, width: Math.min(maxWidth, width - x), height: maxHeight, row, column });
        if (x + maxWidth >= width) break;
        x += maxWidth;
      }
      break;
    }
    for (let x = 0, column = 0; x < width; column += 1) {
      tiles.push({ x, y, width: Math.min(maxWidth, width - x), height: Math.min(maxHeight, remaining), row, column });
      if (x + maxWidth >= width) break;
      x += maxWidth;
    }
  }
  return tiles;
}

export function headerHeight(candidates, viewport) {
  const eligible = candidates.filter(({ position, top, width, height }) =>
    (position === 'sticky' || position === 'fixed') && top >= 0
      && top < viewport.height / 3 && width >= viewport.width * 0.5
      && height > 0 && height < viewport.height * 0.3);
  return Math.ceil(Math.max(0, ...eligible.map(({ top, height }) => top + height)));
}

export function hasBottomControls(candidates, viewport) {
  return Boolean(findBottomControls(candidates, viewport));
}

export function findBottomControls(candidates, viewport) {
  return candidates.find(({ position, top, bottom, width, height }) =>
    (position === 'sticky' || position === 'fixed') && height > 0
      && height < viewport.height * 0.3 && top >= viewport.height * 0.6
      && bottom <= viewport.height + 4 && width >= viewport.width * 0.2);
}

export function pngWidth(bytes) {
  return pngDimensions(bytes)?.width || 0;
}

export function pngHeight(bytes) {
  return pngDimensions(bytes)?.height || 0;
}

function pngDimensions(bytes) {
  if (bytes.length < 24 || !bytes.subarray(0, 8).equals(Buffer.from([137, 80, 78, 71, 13, 10, 26, 10]))) return 0;
  return { width: bytes.readUInt32BE(16), height: bytes.readUInt32BE(20) };
}

export function tileViewportPosition(tileY, pageHeight, viewportHeight, headerHeight = 0) {
  const overlap = tileY > 0 ? Math.max(0, headerHeight) : 0;
  return {
    scrollTop: Math.max(0, tileY - overlap),
    clipY: overlap,
    minPageHeight: Math.max(pageHeight, tileY + viewportHeight - overlap),
  };
}

export function jpegWidth(bytes) {
  return jpegDimensions(bytes)?.width || 0;
}

export function jpegHeight(bytes) {
  return jpegDimensions(bytes)?.height || 0;
}

function jpegDimensions(bytes) {
  if (bytes.length < 4 || bytes[0] !== 0xff || bytes[1] !== 0xd8) return 0;
  const frameMarkers = new Set([0xc0, 0xc1, 0xc2, 0xc3, 0xc5, 0xc6, 0xc7, 0xc9, 0xca, 0xcb, 0xcd, 0xce, 0xcf]);
  for (let offset = 2; offset + 8 < bytes.length;) {
    if (bytes[offset] !== 0xff) return 0;
    while (bytes[offset] === 0xff) offset += 1;
    const marker = bytes[offset++];
    if (marker === 0xd8 || marker === 0x01 || (marker >= 0xd0 && marker <= 0xd7)) continue;
    if (marker === 0xd9 || offset + 2 > bytes.length) return 0;
    const segmentLength = bytes.readUInt16BE(offset);
    if (segmentLength < 2 || offset + segmentLength > bytes.length) return 0;
    if (frameMarkers.has(marker)) return { height: bytes.readUInt16BE(offset + 3), width: bytes.readUInt16BE(offset + 5) };
    offset += segmentLength;
  }
  return 0;
}

export function routeList(routes, origin) {
  const unique = new Set();
  for (const route of routes) {
    const url = new URL(route, origin);
    if (origin && url.origin !== new URL(origin).origin) continue;
    url.hash = '';
    if (url.pathname.length > 1) url.pathname = url.pathname.replace(/\/+$/, '');
    unique.add(url.href);
  }
  return [...unique].sort();
}

export function selectRouteSamples(routes, requestedRoutes, origin) {
  if (!requestedRoutes?.length) return routes;
  const available = new Set(routeList(routes, origin));
  const selected = routeList(requestedRoutes, origin);
  const missing = selected.filter((route) => !available.has(route));
  if (missing.length) throw new Error(`Requested capture routes were not discovered: ${missing.join(', ')}`);
  return selected;
}

export function routeTemplate(route) {
  const url = new URL(route);
  const parts = url.pathname.split('/').filter(Boolean);
  if (parts[0] === 'plans' && parts.length > 1) parts[1] = '<id>';
  if (parts[0] === 'settings' && parts.length > 1) parts[1] = '<id>';
  if (parts[0] === 'thread' && parts.length > 1) parts[1] = '<id>';
  if (parts[0] === 'threads' && parts.length > 1) parts[1] = '<id>';
  if (parts[0] === 'roles' && parts.length > 1) parts[1] = '<id>';
  if (parts[0] === 'profile' && parts.length > 1) parts[1] = '<id>';
  return `/${parts.join('/')}`;
}

export function tileDimensions(width, height, maxSide = 540) {
  const scale = Math.min(1, maxSide / Math.max(width, height));
  let resultWidth = Math.max(1, Math.round(width * scale));
  let resultHeight = Math.max(1, Math.round(height * scale));
  if (resultWidth > resultHeight * 2) resultWidth = resultHeight * 2;
  if (resultHeight > resultWidth * 2) resultHeight = resultWidth * 2;
  return { width: resultWidth, height: resultHeight };
}

export function tileIsValid({ width, height, bytes }) {
  const ratio = width / height;
  return width > 0 && height > 0 && width <= 540 && height <= 540
    && ratio >= 0.5 && ratio <= 2 && bytes > 0 && bytes <= 150_000;
}

export function normalizePng(bytes) {
  if (pngWidth(bytes) <= 0 || pngHeight(bytes) <= 0) throw new Error('Invalid PNG header');
  const chunks = [];
  const idat = [];
  for (let offset = 8; offset + 12 <= bytes.length;) {
    const length = bytes.readUInt32BE(offset);
    const end = offset + 12 + length;
    if (end > bytes.length) throw new Error('Truncated PNG chunk');
    const type = bytes.toString('ascii', offset + 4, offset + 8);
    const data = bytes.subarray(offset + 8, offset + 8 + length);
    if (type === 'IHDR') chunks.push({ type, data: Buffer.from(data) });
    if (type === 'IDAT') idat.push(data);
    if (type === 'IEND') break;
    offset = end;
  }
  if (!chunks.length || !idat.length) throw new Error('PNG is missing required image chunks');
  const header = chunks[0].data;
  const width = header.readUInt32BE(0);
  const height = header.readUInt32BE(4);
  const channels = ({ 0: 1, 2: 3, 3: 1, 4: 2, 6: 4 })[header[9]];
  const bitsPerPixel = channels * header[8];
  if (!channels || !bitsPerPixel) throw new Error('Unsupported PNG colour type');
  const rowBytes = Math.ceil(width * bitsPerPixel / 8) + 1;
  const raw = inflateSync(Buffer.concat(idat));
  if (raw.length !== rowBytes * height) throw new Error('PNG image data does not match its dimensions');
  const normalized = Buffer.concat([Buffer.from([137, 80, 78, 71, 13, 10, 26, 10]), pngChunk('IHDR', header), pngChunk('IDAT', Buffer.concat(idat)), pngChunk('IEND', Buffer.alloc(0))]);
  return normalized;
}

function pngChunk(type, data) {
  const typeBytes = Buffer.from(type, 'ascii');
  const chunk = Buffer.alloc(data.length + 12);
  chunk.writeUInt32BE(data.length, 0);
  typeBytes.copy(chunk, 4);
  data.copy(chunk, 8);
  chunk.writeUInt32BE(pngCrc32(chunk.subarray(4, data.length + 8)), data.length + 8);
  return chunk;
}

function pngCrc32(bytes) {
  let crc = 0xffffffff;
  for (const byte of bytes) {
    crc ^= byte;
    for (let bit = 0; bit < 8; bit += 1) crc = (crc >>> 1) ^ (crc & 1 ? 0xedb88320 : 0);
  }
  return (crc ^ 0xffffffff) >>> 0;
}

export function isNearSingleColour(samples, threshold = 0.9) {
  if (!samples.length) return true;
  const counts = new Map();
  for (const colour of samples) counts.set(colour, (counts.get(colour) || 0) + 1);
  return Math.max(...counts.values()) / samples.length > threshold;
}

export function shouldDropTile(samples, visibleText) {
  const hasContentText = visibleText.trim() && !/^loading\b/i.test(visibleText.trim());
  return !hasContentText && isNearSingleColour(samples);
}

export function countEmptyStateFlashes(emptyFrames, maxDurationFrames = 5) {
  let flashes = 0;
  for (let start = 1; start < emptyFrames.length - 1;) {
    if (!emptyFrames[start]) { start += 1; continue; }
    let end = start;
    while (emptyFrames[end + 1]) end += 1;
    if (!emptyFrames[start - 1] && !emptyFrames[end + 1] && end - start + 1 <= maxDurationFrames) flashes += 1;
    start = end + 1;
  }
  return flashes;
}

export function isEmptyLoadingState(text) {
  return /\b(?:loading(?:\s+\w+){0,4}\.\.\.|no\s+\w+(?:\s+\w+){0,3}\s+yet|all\s+caught\s+up|queue\s+0)\b/i.test(text);
}

export function formatTileIndex(entries) {
  const allFiles = entries.flatMap((entry) => entry.files);
  const unviewable = allFiles.filter((file) => file.jpegSuspicious || file.suspicious).length;
  const truncated = entries.reduce((sum, entry) => sum + (entry.truncatedTiles || 0), 0);
  const dropped = entries.reduce((sum, entry) => sum + (entry.droppedUniformTiles || 0), 0);
  const lines = ['# UX screenshot tiles', '', `- Unviewable tiles: ${unviewable}`, `- Dropped blank or skeleton-only tiles: ${dropped}.`, `- Truncated ${truncated} tiles across captured pages (informational).`, ''];
  for (const entry of entries) {
    lines.push(`## ${entry.route} · ${entry.viewport} · ${entry.scheme}`, '', `- View load: ${entry.loaded === false ? '**still loading (timeout)**' : 'loaded'}`);
    if (entry.truncatedTiles) lines.push(`- Truncated ${entry.truncatedTiles} tiles on this page (informational).`);
    for (const file of entry.files) {
      lines.push(`- ${file.kind || 'PNG'}: [${file.name || file.jpeg}](${file.name || file.jpeg}) (${file.bytes ?? file.jpegBytes} bytes, ${file.width ?? file.jpegWidth}×${file.height ?? file.jpegHeight}px)${file.stickyBottom ? ' · sticky/fixed bottom controls visible' : ''}${file.stillLoading ? ' · **still loading**' : ''}`);
      if (file.jpegSuspicious || file.suspicious) lines.push(`  - WARNING: ${file.kind || 'PNG'} violates viewability limits (ratio 1:2–2:1, long side ≤540px, ≤150000 bytes).`);
    }
    lines.push('');
  }
  return `${lines.join('\n')}\n`;
}

export function formatLoadingReport(routes, routeLimitReached = false) {
  const lines = ['# Loading capture summary', ''];
  if (routeLimitReached) lines.push('> Route discovery reached its configured limit; additional routes may remain queued.', '');
  lines.push('| Route | First content (ms) | Layout shift | Empty-state flashes | Persistent status | Popover trigger | Open on load |', '| --- | ---: | ---: | ---: | --- | --- | --- |');
  for (const route of routes) {
    lines.push(`| ${route.route} | ${route.firstContentMs ?? 'not observed'} | ${route.layoutShift.toFixed(4)} | ${route.emptyStateFlashes} | ${route.persistentStatus ? 'yes' : 'no'} | ${route.popoverTrigger ? 'yes' : 'no'} | ${route.popoverOpenOnLoad ? 'yes' : 'no'} |`);
  }
  return `${lines.join('\n')}\n`;
}
