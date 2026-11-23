import { act, cleanup, renderHook, waitFor } from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";
import type { RefObject } from "react";
import type { components } from "../../src/types/generated";

type Layout = components["schemas"]["PageLayoutAST"];
type Status = { density: string; safeFlow: boolean; settled: boolean; overflow: boolean };
const modules = import.meta.glob("../../src/engine/useOverflowHeal.ts", { eager: true });
const hook = (modules["../../src/engine/useOverflowHeal.ts"] as { useOverflowHeal: (ref: RefObject<HTMLElement | null>, layout: Layout) => Status } | undefined)?.useOverflowHeal;
function layout(density = "airy"): Layout { return { option_id: "a", archetype: "editorial_asymmetric", column_count: 2, density_scale: density, components: [], rationale: "", strategy_tag: "", surface_role: "paper" }; }
afterEach(() => { cleanup(); vi.restoreAllMocks(); });
function setup(heights: number[], initial = layout(), widths?: number[]) {
  expect(hook, "useOverflowHeal must implement bounded density healing").toBeDefined();
  if (!hook) throw new Error("Missing overflow healer");
  const element = document.createElement("div");
  const measurements: string[] = [];
  let count = 0;
  Object.defineProperty(element, "scrollHeight", { get: () => { measurements.push(`${element.dataset.density}:${element.dataset.safeFlow}`); return heights[Math.min(count++, heights.length - 1)]; } });
  Object.defineProperty(element, "clientHeight", { value: 100 });
  Object.defineProperty(element, "scrollWidth", { get: () => widths?.[Math.min(count - 1, widths.length - 1)] ?? 100 });
  Object.defineProperty(element, "clientWidth", { value: 100 });
  const ref = { current: element };
  const view = renderHook(({ ast }) => { const status = hook(ref, ast); element.dataset.density = status.density; element.dataset.safeFlow = String(status.safeFlow); return status; }, { initialProps: { ast: initial } });
  return { ...view, element, measurements };
}
test("measures airy, normal, compact, then two-column safe flow without modifying the AST", async () => {
  const ast = Object.freeze(layout());
  const before = JSON.stringify(ast);
  const view = setup([200, 160, 120, 90], ast);
  await waitFor(() => expect(view.result.current.settled).toBe(true));
  expect(view.measurements).toEqual(["airy:false", "normal:false", "compact:false", "compact:true"]);
  expect(view.result.current).toMatchObject({ density: "compact", safeFlow: true, overflow: false });
  expect(JSON.stringify(ast)).toBe(before);
});
test.each([[90], [200, 90], [200, 150, 90]])("stops as soon as content fits: %j", async (...heights) => {
  const view = setup(heights);
  await waitFor(() => expect(view.result.current.settled).toBe(true));
  expect(view.measurements).toHaveLength(heights.length);
  expect(view.result.current.overflow).toBe(false);
});
test("settles unhealable overflow without looping", async () => {
  const view = setup([200]);
  await waitFor(() => expect(view.result.current.settled).toBe(true));
  expect(view.measurements).toHaveLength(4);
  await act(async () => { await new Promise((resolve) => setTimeout(resolve, 60)); });
  expect(view.measurements).toHaveLength(4);
  expect(view.result.current).toMatchObject({ safeFlow: true, overflow: true });
});
test("detects horizontal overflow and resets for a new persisted layout", async () => {
  const view = setup([90], layout("compact"), [200]);
  await waitFor(() => expect(view.result.current.settled).toBe(true));
  expect(view.measurements).toEqual(["compact:false", "compact:true"]);
  view.rerender({ ast: layout("normal") });
  await waitFor(() => expect(view.measurements).toHaveLength(5));
  await waitFor(() => expect(view.result.current.settled).toBe(true));
});
test("waits for fonts and pending images before measuring", async () => {
  let fontsReady!: () => void;
  const previous = Object.getOwnPropertyDescriptor(document, "fonts");
  Object.defineProperty(document, "fonts", { configurable: true, value: { ready: new Promise<void>((resolve) => { fontsReady = resolve; }) } });
  const view = setup([90]);
  const image = document.createElement("img");
  Object.defineProperty(image, "complete", { value: false });
  view.element.append(image);
  await act(async () => { fontsReady(); });
  expect(view.measurements).toHaveLength(0);
  await act(async () => { image.dispatchEvent(new Event("load")); });
  await waitFor(() => expect(view.result.current.settled).toBe(true));
  expect(view.measurements).toHaveLength(1);
  if (previous) Object.defineProperty(document, "fonts", previous); else Reflect.deleteProperty(document, "fonts");
});
test("unmount while images are pending cancels listeners and avoids late measurements", async () => {
  const view = setup([90], layout("unrecognized"));
  const image = document.createElement("img");
  Object.defineProperty(image, "complete", { value: false });
  view.element.append(image);
  await act(async () => { await Promise.resolve(); });
  const remove = vi.spyOn(image, "removeEventListener");
  view.unmount();
  expect(remove).toHaveBeenCalledWith("load", expect.any(Function));
  expect(remove).toHaveBeenCalledWith("error", expect.any(Function));
  image.dispatchEvent(new Event("error"));
  expect(view.measurements).toHaveLength(0);
});
