import { useSyncExternalStore } from "react";

import { getLanguage, subscribeLanguage, type Language } from "./i18n";

/** Current language; the calling component renders again when it changes. */
export function useLanguage(): Language {
  return useSyncExternalStore(subscribeLanguage, getLanguage);
}
