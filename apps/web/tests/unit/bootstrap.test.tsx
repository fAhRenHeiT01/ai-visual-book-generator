import { render, screen } from "@testing-library/react";
import { expect, test } from "vitest";

test("the app exposes an accessible heading", async () => {
  const pages = import.meta.glob("../../src/app/page.tsx", { eager: true });
  const page = pages["../../src/app/page.tsx"] as
    | { default: () => React.ReactNode }
    | undefined;
  expect(page, "the app page must be available").toBeDefined();
  if (!page) return;
  render(<page.default />);
  expect(screen.getByRole("heading", { level: 1, name: "Visual Book Generator" })).toBeTruthy();
});
