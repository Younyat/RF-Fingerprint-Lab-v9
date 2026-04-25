const DEFAULT_SPECTRUM_POLL_INTERVAL_MS = 100;
const DEFAULT_WATERFALL_POLL_INTERVAL_MS = 100;
const DEFAULT_APP_SYNC_INTERVAL_MS = 5000;

const parsePositiveInteger = (value: string | undefined, fallback: number): number => {
  if (!value) {
    return fallback;
  }

  const parsed = Number.parseInt(value, 10);
  if (!Number.isFinite(parsed) || parsed <= 0) {
    return fallback;
  }

  return parsed;
};

export const RUNTIME_CONFIG = {
  appSyncIntervalMs: parsePositiveInteger(
    import.meta.env.VITE_APP_SYNC_INTERVAL_MS,
    DEFAULT_APP_SYNC_INTERVAL_MS,
  ),
  spectrumPollIntervalMs: parsePositiveInteger(
    import.meta.env.VITE_SPECTRUM_POLL_INTERVAL_MS,
    DEFAULT_SPECTRUM_POLL_INTERVAL_MS,
  ),
  waterfallPollIntervalMs: parsePositiveInteger(
    import.meta.env.VITE_WATERFALL_POLL_INTERVAL_MS,
    DEFAULT_WATERFALL_POLL_INTERVAL_MS,
  ),
  remoteUser: import.meta.env.VITE_REMOTE_USER ?? '',
  remoteHost: import.meta.env.VITE_REMOTE_HOST ?? '',
  remoteVenvActivate:
    import.meta.env.VITE_REMOTE_VENV_ACTIVATE ??
    (import.meta.env.VITE_REMOTE_USER ? `/home/${import.meta.env.VITE_REMOTE_USER}/rfenv/bin/activate` : ''),
  radioCondaPython: import.meta.env.VITE_RADIOCONDA_PYTHON ?? '',
} as const;
