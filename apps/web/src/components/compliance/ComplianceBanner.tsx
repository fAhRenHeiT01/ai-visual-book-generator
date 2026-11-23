import type { components } from '../../types/generated';
/** Phase 2 replaces this independently mounted MVP notice with a compliance ledger. */
export type ComplianceBannerProps = {
  sessionId?: string;
  snapshot?: components['schemas']['SessionSnapshot'];
  onDecision?: () => Promise<void>;
};
export function ComplianceBanner({ sessionId }: ComplianceBannerProps) {
  return <aside className="compliance-banner studio-controls" data-session-id={sessionId} data-feature-state="unavailable">Compliance review · Phase 2. Basic draft printing is available.</aside>;
}
