'use client';
import type { components } from '../../types/generated';
type S = components['schemas'];
export type ExportActionProps = {
  disabled: boolean;
  sessionId: string;
  pages: S['PageGenerationResult'][];
  context: S['BookContext'];
  appearance: S['AppearanceResponse'];
};
/** Phase 2 supplies the compliance gate and PDF endpoint at this separate action. */
export function ExportAction({ disabled }: ExportActionProps) {
  return <button className="studio-controls" type="button" disabled={disabled} onClick={() => window.print()}>Print draft</button>;
}
