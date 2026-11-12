/// <reference types="vite/client" />

interface ImportMetaEnv {
  /** Base URL of the code-atlas API (build time; default http://127.0.0.1:8790). */
  readonly VITE_API_URL?: string;
}
