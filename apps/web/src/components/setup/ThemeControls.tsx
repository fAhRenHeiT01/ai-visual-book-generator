import type { components } from '../../types/generated';
/** Independent Phase 2 setup mount. Persisted appearance is already passed to every canvas. */
type Appearance = components['schemas']['AppearanceResponse'];
export type ThemeControlsProps = {
  sessionId?: string;
  appearance?: Appearance;
  locked?: boolean;
  onAppearanceChange?: (appearance: Appearance) => void;
};
export function ThemeControls({ appearance }: ThemeControlsProps) {
  return <aside className="theme-controls studio-controls" data-feature-state={appearance?.status ?? 'unavailable'}><p>Theme customization · Phase 2</p><button disabled>Extract website theme</button></aside>;
}
