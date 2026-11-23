import { Studio } from '../../../components/studio/Studio';
export default async function SessionPage({ params }: { params: Promise<{ sessionId: string }> }) {
  const { sessionId } = await params;
  return <Studio sessionId={sessionId} />;
}
