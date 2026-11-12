import js from "@eslint/js";
import globals from "globals";
import reactHooks from "eslint-plugin-react-hooks";
import tseslint from "typescript-eslint";

export default tseslint.config(
  { ignores: ["dist", "coverage", "src/api/schema.d.ts", "playwright-report", "test-results", "eslint.config.js"] },
  {
    files: ["**/*.{ts,tsx}"],
    extends: [js.configs.recommended, ...tseslint.configs.strictTypeChecked],
    languageOptions: {
      globals: { ...globals.browser },
      parserOptions: { projectService: true, tsconfigRootDir: import.meta.dirname },
    },
    plugins: { "react-hooks": reactHooks },
    rules: {
      ...reactHooks.configs.recommended.rules,
      "@typescript-eslint/restrict-template-expressions": ["error", { allowNumber: true }],
      // No token nor data in browser storage: everything stays in memory.
      "no-restricted-globals": ["error", "localStorage", "sessionStorage", "indexedDB"],
      "no-restricted-properties": [
        "error",
        { object: "window", property: "localStorage" },
        { object: "window", property: "sessionStorage" },
        { object: "document", property: "cookie" },
      ],
    },
  },
  {
    // vitest spies (vi.fn) are passed to expect() without their object: on purpose.
    files: ["tests/**/*.{ts,tsx}"],
    rules: { "@typescript-eslint/unbound-method": "off" },
  },
  {
    // The e2e journey READS browser storage to check that it stays empty.
    files: ["e2e/**/*.ts"],
    rules: { "no-restricted-properties": "off" },
  },
);
