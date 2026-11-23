import { PageCanvas } from '../../engine/PageCanvas';
import type { components } from '../../types/generated';
import { ExportAction } from './ExportAction';
type S = components['schemas'];
export function DraftViewer({ sessionId, pages, context, appearance }: { sessionId: string; pages: S['PageGenerationResult'][]; context: S['BookContext']; appearance: S['AppearanceResponse'] }) {
  return <section className="draft-viewer" aria-label="Committed draft">
    <div className="studio-controls"><h2>Draft</h2><p>{pages.length} committed page{pages.length === 1 ? '' : 's'}</p></div>
    <ExportAction disabled={!pages.length} sessionId={sessionId} pages={pages} context={context} appearance={appearance} />
    <div className="draft-pages">{pages.map(page => <div className="draft-page" key={page.page_id}><PageCanvas result={page} tokens={appearance.tokens} pageSize={context.page_size} chrome={{ config: appearance.chrome, pageNumber: page.page_number, totalPages: pages.length, chapterTitle: context.title, isCover: page.page_number === 1 }} /></div>)}</div>
  </section>;
}
