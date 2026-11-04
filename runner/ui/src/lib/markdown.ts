// Minimal markdown to HTML for plan text. All input is escaped first, so the
// output can only contain the tags emitted here.
const escapeHtml = (text: string) =>
  text.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;').replace(/'/g, '&#39;');

const SAFE_URL = /^(https?:\/\/|\/(?!\/)|#)/;

function inlineCode(text: string): string {
  return text.split(/(`[^`]+`)/).map((part, index) => index % 2 ? `<code>${part.slice(1, -1)}</code>` : inlineEmphasis(part)).join('');
}

function inlineEmphasis(text: string): string {
  return text
    .replace(/\[([^\]]+)\]\(([^)\s*]+)\)/g, (whole, label, url) => SAFE_URL.test(url) ? `<a href="${url}" rel="noopener noreferrer">${label}</a>` : whole)
    .replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>')
    .replace(/(^|[^*\w])\*([^*\s][^*]*)\*(?!\w)/g, '$1<em>$2</em>');
}

const inline = (text: string) => inlineCode(escapeHtml(text));
const stripFrontmatter = (text: string) => text.replace(/^---\r?\n[\s\S]*?\r?\n---\r?\n?/, '');
const isTableRow = (line: string) => /^\s*\|.*\|\s*$/.test(line);
const isTableRule = (line: string) => /^\s*\|[\s:|-]+\|\s*$/.test(line);
const tableCells = (line: string) => line.trim().replace(/^\||\|$/g, '').split('|').map((cell) => cell.trim());
const startsBlock = (line: string) => /^(#{1,6}\s|```|>\s?|\s*[-*]\s|\s*\d+[.)]\s|---+\s*$)/.test(line) || isTableRow(line);

function list(lines: string[], start: number, ordered: boolean): [string, number] {
  const marker = ordered ? /^\s*\d+[.)]\s+(.*)$/ : /^\s*[-*]\s+(.*)$/;
  const items: string[] = [];
  let index = start;
  while (index < lines.length && marker.test(lines[index])) {
    const content = lines[index++].replace(marker, '$1');
    const task = ordered ? null : /^\[([ xX])\]\s+(.*)$/.exec(content);
    if (task) {
      const checked = task[1].toLowerCase() === 'x' ? ' checked' : '';
      items.push(`<li class="task-list-item"><input type="checkbox" disabled${checked}> ${inline(task[2])}</li>`);
    } else items.push(`<li>${inline(content)}</li>`);
  }
  const tag = ordered ? 'ol' : 'ul';
  return [`<${tag}>${items.join('')}</${tag}>`, index];
}

function table(lines: string[], start: number): [string, number] {
  const head = tableCells(lines[start]).map((cell) => `<th>${inline(cell)}</th>`).join('');
  let index = start + 2;
  const rows: string[] = [];
  while (index < lines.length && isTableRow(lines[index])) rows.push(`<tr>${tableCells(lines[index++]).map((cell) => `<td>${inline(cell)}</td>`).join('')}</tr>`);
  return [`<div class="table-scroll"><table><thead><tr>${head}</tr></thead><tbody>${rows.join('')}</tbody></table></div>`, index];
}

export function renderMarkdown(source: string): string {
  const lines = stripFrontmatter(source.replace(/\r\n?/g, '\n')).split('\n');
  const html: string[] = [];
  let index = 0;
  while (index < lines.length) {
    const line = lines[index];
    const heading = /^(#{1,6})\s+(.*)$/.exec(line);
    if (!line.trim()) { index++; continue; }
    if (line.startsWith('```')) {
      const code: string[] = [];
      index++;
      while (index < lines.length && !lines[index].startsWith('```')) code.push(lines[index++]);
      index++;
      html.push(`<pre><code>${escapeHtml(code.join('\n'))}</code></pre>`);
    } else if (heading) {
      let next = index + 1;
      while (next < lines.length && !lines[next].trim()) next++;
      const nextHeading = /^(#{1,6})\s+/.exec(lines[next] ?? '');
      if (next === lines.length || (nextHeading && nextHeading[1].length <= heading[1].length)) { index++; continue; }
      const level = Math.min(heading[1].length + 1, 6);
      html.push(`<h${level}>${inline(heading[2])}</h${level}>`);
      index++;
    } else if (/^---+\s*$/.test(line)) { html.push('<hr>'); index++; }
    else if (/^>\s?/.test(line)) {
      const quote: string[] = [];
      while (index < lines.length && /^>\s?/.test(lines[index])) quote.push(lines[index++].replace(/^>\s?/, ''));
      html.push(`<blockquote>${inline(quote.join(' '))}</blockquote>`);
    } else if (/^\s*[-*]\s+/.test(line)) { const [block, next] = list(lines, index, false); html.push(block); index = next; }
    else if (/^\s*\d+[.)]\s+/.test(line)) { const [block, next] = list(lines, index, true); html.push(block); index = next; }
    else if (isTableRow(line) && isTableRule(lines[index + 1] ?? '')) { const [block, next] = table(lines, index); html.push(block); index = next; }
    else {
      const paragraph = [line];
      index++;
      while (index < lines.length && lines[index].trim() && !startsBlock(lines[index])) paragraph.push(lines[index++]);
      html.push(`<p>${inline(paragraph.join(' '))}</p>`);
    }
  }
  return html.join('');
}
