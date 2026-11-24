import type { components } from '../types/generated';

type Config = components['schemas']['MasterChromeConfig'];
export type ChromeValues = { pageNumber: number; totalPages?: number; chapterTitle?: string };
export function pageChapterTitles(pages: components['schemas']['PageGenerationResult'][]) {
  let chapter = '';
  return pages.map(page => {
    chapter = page.title?.trim() ? page.title : page.input_blocks.find(block => block.kind === 'heading' && block.text.trim())?.text || chapter;
    return chapter;
  });
}
export function chromeBands(config?: Config, suppressed = false) {
  const enabled = !!config?.enabled && !suppressed;
  return { header: enabled && !!(config?.header_left || config?.header_right), footer: enabled && !!(config?.footer_left || config?.footer_center || config?.footer_right) };
}
export function MasterChrome({ config, band, values }: { config: Config; band: 'header' | 'footer'; values: ChromeValues }) {
  const interpolate = (text: string) => text.replaceAll('{page_number}', String(values.pageNumber))
    .replaceAll('{total_pages}', String(values.totalPages ?? '')).replaceAll('{chapter_title}', values.chapterTitle?.trim() ? values.chapterTitle : String(values.pageNumber));
  const contents = band === 'header' ? [config.header_left, '', config.header_right] : [config.footer_left, config.footer_center, config.footer_right];
  const Tag = band === 'header' ? 'header' : 'footer';
  return <Tag className={`master-chrome chrome-${band}`}>{contents.map((text, index) => <span key={index}>{interpolate(text)}</span>)}</Tag>;
}
