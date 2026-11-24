'use client';
import { useLayoutEffect, useRef, useState, type ReactNode } from 'react';

/** Scale only the presentation wrapper; the print canvas still measures at full size. */
export function PagePreview({ children }: { children: ReactNode }) {
  const frame = useRef<HTMLDivElement>(null);
  const sheet = useRef<HTMLDivElement>(null);
  const [size, setSize] = useState({ scale: 1, height: 0 });
  useLayoutEffect(() => {
    const measure = () => {
      if (!frame.current || !sheet.current || !frame.current.clientWidth || !sheet.current.offsetWidth) return;
      const scale = Math.min(1, frame.current.clientWidth / sheet.current.offsetWidth);
      const height = sheet.current.offsetHeight * scale;
      setSize(previous => previous.scale === scale && previous.height === height ? previous : { scale, height });
    };
    measure();
    if (typeof ResizeObserver === 'undefined') return;
    const observer = new ResizeObserver(measure);
    if (frame.current) observer.observe(frame.current);
    if (sheet.current) observer.observe(sheet.current);
    return () => observer.disconnect();
  }, []);
  return <div ref={frame} className="canvas-scroll page-preview" style={{ height: size.height || undefined }}>
    <div className="preview-clip"><div ref={sheet} className="preview-sheet" style={{ transform: `scale(${size.scale})` }}>{children}</div></div>
  </div>;
}
