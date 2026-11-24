import type { components } from '../types/generated';
import { apiOrigin } from '../config/env';

type S = components['schemas'];
const prefix = (id: string) => `/api/v1/sessions/${encodeURIComponent(id)}`;
async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(apiOrigin + path, init);
  if (!response.ok) {
    const body = await response.json().catch(() => null);
    throw new Error(typeof body?.detail === 'string' ? body.detail : `Request failed (${response.status}). Please retry.`);
  }
  return response.json() as Promise<T>;
}
const json = (body: unknown, method = 'POST'): RequestInit => ({ method, headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
const draftKey = (id: string) => `bookgen:active-page:${id}`;
function savedDraft(id: string): S['ActivePage'] | undefined {
  try {
    const draft = JSON.parse(window.localStorage.getItem(draftKey(id)) ?? 'null');
    if (draft && typeof draft.page_id === 'string' && typeof draft.text === 'string' && Number.isInteger(draft.page_number) && Array.isArray(draft.asset_ids) && draft.asset_ids.every((value: unknown) => typeof value === 'string')) return draft;
  } catch { /* Server snapshots remain available when browser storage is blocked. */ }
}
export const sessionApi = {
  examples: () => request<S['ExampleCatalog']>('/api/v1/examples'),
  openExample: (id: string) => request<S['SessionSnapshot']>(`/api/v1/examples/${encodeURIComponent(id)}/sessions`, { method: 'POST' }),
  create: (context: S['BookContext']) => request<S['SessionSnapshot']>('/api/v1/sessions', json({ context })),
  load: async (id: string) => {
    const snapshot = await request<S['SessionSnapshot']>(prefix(id));
    const draft = savedDraft(id);
    if (!snapshot.active_page && !snapshot.pending_review && draft && draft.page_number === snapshot.current_page_index && !snapshot.committed_pages?.some(page => page.page_id === draft.page_id)) snapshot.active_page = draft;
    return snapshot;
  },
  remember: (id: string, draft: S['ActivePage']) => {
    try { window.localStorage.setItem(draftKey(id), JSON.stringify(draft)); } catch { /* Recovery also uses the durable server checkpoint. */ }
  },
  debug: (id: string) => request<S['DebugSnapshot']>(prefix(id) + '/debug'),
  debugStart: (id: string, text: string, asset_ids: string[], page_id?: string) => request<S['DebugSnapshot']>(prefix(id) + '/debug/pages', json({ text, asset_ids, page_id })),
  debugStep: (id: string, checkpoint_id: string, response?: string) => request<S['DebugSnapshot']>(prefix(id) + '/debug/step', json({ checkpoint_id, response })),
  appearance: (id: string) => request<S['AppearanceResponse']>(prefix(id) + '/appearance'),
  saveAppearance: (id: string, appearance: S['SessionAppearance']) => request<S['AppearanceResponse']>(prefix(id) + '/appearance', json(appearance, 'PUT')),
  compliance: (id: string) => request<S['ComplianceReport']>(prefix(id) + '/compliance'),
  decide: (id: string, decision: S['ComplianceDecision']) => request<S['ComplianceReport']>(prefix(id) + '/compliance/decisions', json(decision)),
  themes: () => request<S['ThemeListResponse']>('/api/v1/themes'),
  applyTheme: (id: string, theme_id: string) => request<S['AppearanceResponse']>(prefix(id) + '/appearance/theme', json({ theme_id })),
  extractTheme: (url: string, name?: string) => request<S['ThemeExtractResponse']>('/api/v1/themes/extract', json({ url, ...(name ? { name } : {}) })),
  upload: (id: string, files: File[]) => {
    const body = new FormData();
    files.forEach(file => body.append('files', file));
    return request<S['AssetUploadResponse']>(prefix(id) + '/assets', { method: 'POST', body });
  },
  generate: (id: string, text: string, asset_ids: string[], page_id?: string, revise = false) => request<S['PageGenerationResult']>(prefix(id) + '/pages', json({ text, asset_ids, page_id, revise })),
  select: (id: string, page: string, option_id: 'option_a' | 'option_b') => request<S['PageGenerationResult']>(prefix(id) + `/pages/${encodeURIComponent(page)}/selection`, json({ option_id })),
  browserPage: (id: string, page: S['PageGenerationResult'], purpose: 'preview' | 'print' = 'preview'): S['PageGenerationResult'] => ({
    ...page,
    input_assets: page.input_assets.map(asset => {
      const original = apiOrigin + prefix(id) + `/assets/${encodeURIComponent(asset.asset_id)}`;
      return { ...asset, storage_key: original, thumbnail_key: purpose === 'preview' && asset.thumbnail_key ? original + '?thumbnail=true' : null };
    }),
  }),
  review: (id: string, page: string, committed: () => void) => {
    if (typeof EventSource === 'undefined') return () => {};
    const stream = new EventSource(apiOrigin + prefix(id) + `/pages/${encodeURIComponent(page)}/events`);
    stream.addEventListener('committed', committed);
    stream.addEventListener('terminal', () => stream.close());
    return () => stream.close();
  },
};
