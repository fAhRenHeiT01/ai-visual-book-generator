"use client";

import { useEffect, useState, type RefObject } from "react";
import type { components } from "../types/generated";

type Layout = components["schemas"]["PageLayoutAST"];
const densities = ["airy", "normal", "compact", "compact"] as const;
function initialStep(layout: Layout) {
  const step = densities.indexOf(layout.density_scale as typeof densities[number]);
  return step < 0 ? 1 : step;
}

/** Rendering state is local. The persisted AST is never edited during physical-page healing. */
export function useOverflowHeal(ref: RefObject<HTMLElement | null>, layout: Layout, resetKey?: string) {
  const [state, setState] = useState(() => ({ layout, resetKey, step: initialStep(layout), settled: false, overflow: false }));
  const current = state.layout === layout && state.resetKey === resetKey
    ? state : { layout, resetKey, step: initialStep(layout), settled: false, overflow: false };
  const { step } = current;

  useEffect(() => {
    const element = ref.current;
    if (!element) return;
    let cancelled = false;
    let frame: number | undefined;
    const unsubscribe: (() => void)[] = [];
    // Query after fonts settle so images inserted during hydration are included too.
    void Promise.resolve(document.fonts?.ready).then(async () => {
      if (cancelled) return;
      await Promise.all(Array.from(element.querySelectorAll("img")).map((image) => {
        if (image.complete) return Promise.resolve();
        return new Promise<void>((resolve) => {
          const finish = () => { image.removeEventListener("load", finish); image.removeEventListener("error", finish); resolve(); };
          image.addEventListener("load", finish);
          image.addEventListener("error", finish);
          unsubscribe.push(() => { image.removeEventListener("load", finish); image.removeEventListener("error", finish); });
        });
      }));
      if (cancelled) return;
      frame = requestAnimationFrame(() => {
        const verticalOverflow = element.scrollHeight > element.clientHeight;
        const horizontalOverflow = element.scrollWidth > element.clientWidth;
        const overflow = verticalOverflow || horizontalOverflow;
        const nextStep = overflow && step < densities.length - 1 ? step + 1 : step;
        setState({ layout, resetKey, step: nextStep, settled: nextStep === step, overflow });
      });
    });
    return () => { cancelled = true; if (frame !== undefined) cancelAnimationFrame(frame); unsubscribe.forEach((remove) => remove()); };
  }, [ref, layout, resetKey, step]);

  return { density: densities[step], safeFlow: step === densities.length - 1, settled: current.settled, overflow: current.overflow };
}
