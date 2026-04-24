/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_APP_SYNC_INTERVAL_MS?: string;
  readonly VITE_SPECTRUM_POLL_INTERVAL_MS?: string;
  readonly VITE_WATERFALL_POLL_INTERVAL_MS?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
