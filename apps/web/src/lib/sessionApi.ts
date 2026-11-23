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
export const sessionApi = {
  create: (context: S['BookContext']) => request<S['SessionSnapshot']>('/api/v1/sessions', json({ context })),
  load: (id: string) => request<S['SessionSnapshot']>(prefix(id)),
  debug: (id: string) => request<S['DebugSnapshot']>(prefix(id) + '/debug'),
  debugStart: (id: string, text: string, asset_ids: string[]) => request<S['DebugSnapshot']>(prefix(id) + '/debug/pages', json({ text, asset_ids })),
  debugStep: (id: string, checkpoint_id: string, response?: string) => request<S['DebugSnapshot']>(prefix(id) + '/debug/step', json({ checkpoint_id, response })),
  appearance: (id: string) => request<S['AppearanceResponse']>(prefix(id) + '/appearance'),
  saveAppearance: (id: string, appearance: S['SessionAppearance']) => request<S['AppearanceResponse']>(prefix(id) + '/appearance', json(appearance, 'PUT')),
  compliance: (id: string) => request<S['ComplianceReport']>(prefix(id) + '/compliance'),
  decide: (id: string, decision: S['ComplianceDecision']) => request<S['ComplianceReport']>(prefix(id) + '/compliance/decisions', json(decision)),
  extractTheme: (url: string) => request<S['ThemeExtractResponse']>('/api/v1/themes/extract', json({ url })),
  upload: (id: string, files: File[]) => {
    const body = new FormData();
    files.forEach(file => body.append('files', file));
    return request<S['AssetUploadResponse']>(prefix(id) + '/assets', { method: 'POST', body });
  },
  generate: (id: string, text: string, asset_ids: string[]) => request<S['PageGenerationResult']>(prefix(id) + '/pages', json({ text, asset_ids })),
  select: (id: string, page: string, option_id: 'option_a' | 'option_b') => request<S['PageGenerationResult']>(prefix(id) + `/pages/${encodeURIComponent(page)}/selection`, json({ option_id })),
  browserPage: (id: string, page: S['PageGenerationResult']): S['PageGenerationResult'] => ({ ...page, input_assets: page.input_assets.map(asset => ({ ...asset, storage_key: apiOrigin + prefix(id) + `/assets/${encodeURIComponent(asset.asset_id)}` })) }),
  review: (id: string, page: string, committed: () => void) => {
    if (typeof EventSource === 'undefined') return () => {};
    const stream = new EventSource(apiOrigin + prefix(id) + `/pages/${encodeURIComponent(page)}/events`);
    stream.addEventListener('committed', committed);
    stream.addEventListener('terminal', () => stream.close());
    return () => stream.close();
  },
};
