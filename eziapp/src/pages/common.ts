export function escapeHtml(value: unknown): string {
  return String(value ?? '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

export function formatCount(value: unknown): string {
  const count = Number(value);
  return Number.isFinite(count) ? Math.max(0, count).toLocaleString('zh-CN') : '0';
}

export function formatBytes(value: unknown): string {
  const bytes = Number(value);
  if (!Number.isFinite(bytes) || bytes <= 0) return '0 B';
  const units = ['B', 'KB', 'MB', 'GB', 'TB'];
  let size = bytes;
  let index = 0;
  while (size >= 1024 && index < units.length - 1) {
    size /= 1024;
    index += 1;
  }
  return `${size >= 100 || index === 0 ? Math.round(size) : size.toFixed(1)} ${units[index]}`;
}

export function errorMessage(error: unknown, fallback: string): string {
  return error instanceof Error && error.message ? error.message : fallback;
}

export function scrollToBottom(element: HTMLElement | null): void {
  if (element) element.scrollTop = element.scrollHeight;
}

export function formatDownloads(value: unknown): string {
  const n = Number(value);
  if (!Number.isFinite(n) || n <= 0) return '—';
  if (n >= 100_000_000) return `${(n / 100_000_000).toFixed(n >= 1_000_000_000 ? 0 : 1).replace('.0', '')}亿`;
  if (n >= 10_000) return `${Math.round(n / 10_000)}万`;
  return String(Math.round(n));
}

export function optionHtml(value: string, label = value, selected = false): string {
  return `<option value="${escapeHtml(value)}"${selected ? ' selected' : ''}>${escapeHtml(label)}</option>`;
}
