import "@testing-library/jest-dom/vitest";
import { cleanup } from "@testing-library/react";
import { afterEach } from "vitest";

import { setLanguage } from "../src/i18n";

afterEach(() => {
  cleanup();
  setLanguage("en");
});
