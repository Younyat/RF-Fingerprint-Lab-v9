import React, { useEffect, useMemo, useState } from 'react';
import { ApiService } from '../../app/services/ApiService';
import { ModelArtifactSummary, TrainingDashboard } from '../../shared/types';
import { formatFileSize } from '../../shared/utils';

const api = new ApiService();

const formatTimestamp = (value?: string | null) => {
  if (!value) return 'not available';
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString();
};

const formatMetric = (value: unknown) => {
  if (typeof value === 'number') {
    return Number.isInteger(value) ? value.toLocaleString() : value.toFixed(4);
  }
  if (Array.isArray(value)) return `${value.length} items`;
  if (typeof value === 'boolean') return value ? 'yes' : 'no';
  if (value && typeof value === 'object') return `${Object.keys(value as Record<string, unknown>).length} fields`;
  return String(value ?? 'n/a');
};

const summarizeModelMetrics = (model: ModelArtifactSummary | null) => {
  const metrics = (model?.metrics ?? {}) as Record<string, unknown>;
  return Object.entries(metrics).slice(0, 8);
};

export const ModelRegistryView: React.FC = () => {
  const [overview, setOverview] = useState<TrainingDashboard | null>(null);
  const [currentModel, setCurrentModel] = useState<ModelArtifactSummary | null>(null);
  const [models, setModels] = useState<ModelArtifactSummary[]>([]);
  const [lastRefresh, setLastRefresh] = useState('');

  useEffect(() => {
    let cancelled = false;

    const refreshRegistry = async () => {
      try {
        const [overviewData, current, modelList] = await Promise.all([
          api.getModelOverview(),
          api.getCurrentModel().catch(() => null),
          api.getTrainingModels(),
        ]);
        if (cancelled) return;
        setOverview(overviewData);
        setCurrentModel(current);
        setModels(modelList);
        setLastRefresh(new Date().toISOString());
      } catch (error) {
        if (!cancelled) console.error('Failed to load model registry', error);
      }
    };

    refreshRegistry();
    const interval = window.setInterval(refreshRegistry, 5000);
    window.addEventListener('rfp-job-started', refreshRegistry);

    return () => {
      cancelled = true;
      window.clearInterval(interval);
      window.removeEventListener('rfp-job-started', refreshRegistry);
    };
  }, []);

  const currentMetrics = useMemo(() => summarizeModelMetrics(currentModel), [currentModel]);
  const currentArtifactInventory = overview?.current_model.file_inventory ?? [];
  const latestSnapshots = overview?.retraining.snapshots?.slice(-8).reverse() ?? [];
  const latestValidation = overview?.validation_reports?.slice(-3).reverse() ?? [];
  const datasetManifest = overview?.current_model.dataset_manifest ?? {};
  const trainConfig = overview?.current_model.train_config ?? {};
  const labelMap = overview?.current_model.label_map ?? {};

  return (
    <div className="app-page p-6">
      <div className="mb-6">
        <div className="text-sm font-semibold uppercase tracking-[0.2em] text-violet-700">Model Registry</div>
        <h1 className="mt-2 font-serif text-4xl" style={{ color: 'var(--app-text)' }}>
          Full model card, lineage, dataset provenance, and operational readiness
        </h1>
        <p className="mt-3 max-w-5xl text-sm leading-7 app-muted-text">
          This registry now exposes the operational model card: current artifact sizes, training configuration, dataset manifest,
          retraining history, validation evidence, and filesystem provenance for the unified RF fingerprinting workflow.
        </p>
        <p className="mt-2 text-sm app-muted-text">Last UI refresh: {formatTimestamp(lastRefresh)}</p>
      </div>

      <div className="grid gap-5 md:grid-cols-2 xl:grid-cols-4">
        {[
          ['Model size', formatFileSize(overview?.filesystem.model_dir_size_bytes ?? 0)],
          ['Train records', overview?.dataset.records ?? 0],
          ['Devices in model', overview?.dataset.devices ?? 0],
          ['Retraining snapshots', overview?.retraining.snapshot_count ?? 0],
        ].map(([label, value]) => (
          <div key={String(label)} className="app-surface-strong rounded-[1.5rem] p-5">
            <div className="text-xs uppercase tracking-[0.18em] app-muted-text">{label}</div>
            <div className="mt-3 text-3xl font-semibold" style={{ color: 'var(--app-text)' }}>{value}</div>
          </div>
        ))}
      </div>

      <div className="mt-5 grid gap-5 xl:grid-cols-[1.05fr_0.95fr]">
        <section className="space-y-5">
          <div className="app-surface rounded-[1.75rem] p-5 shadow-[0_18px_40px_rgba(15,23,42,0.08)]">
            <div className="mb-4 flex items-center justify-between">
              <div>
                <div className="text-sm font-semibold uppercase tracking-[0.18em] app-muted-text">Current model card</div>
                <div className="mt-2 text-2xl font-semibold" style={{ color: 'var(--app-text)' }}>
                  {String(currentModel?.version ?? 'current working model')}
                </div>
              </div>
              <div className="text-right text-xs app-muted-text">
                <div>modified: {formatTimestamp(overview?.current_model.modified_at_utc)}</div>
                <div>path exists: {overview?.current_model.exists ? 'yes' : 'no'}</div>
                <div>best model size: {formatFileSize(overview?.current_model.size_bytes ?? 0)}</div>
              </div>
            </div>
            <div className="grid gap-4 md:grid-cols-2">
              <div className="app-surface-muted rounded-2xl p-4">
                <div className="text-xs uppercase tracking-[0.18em] app-muted-text">Operational readiness</div>
                <div className="mt-3 space-y-2 text-sm" style={{ color: 'var(--app-text)' }}>
                  <div>Model file: {overview?.prediction_readiness.has_model_file ? 'available' : 'missing'}</div>
                  <div>Enrollment profiles: {overview?.prediction_readiness.has_profiles ? 'available' : 'missing'}</div>
                  <div>Dataset manifest: {overview?.prediction_readiness.has_manifest ? 'available' : 'missing'}</div>
                  <div>Validation evidence: {overview?.prediction_readiness.has_validation ? 'available' : 'missing'}</div>
                </div>
              </div>
              <div className="app-surface-muted rounded-2xl p-4">
                <div className="text-xs uppercase tracking-[0.18em] app-muted-text">Training performance</div>
                <div className="mt-3 space-y-2 text-sm" style={{ color: 'var(--app-text)' }}>
                  <div>Best test accuracy: {(overview?.training.best_test_acc ?? 0).toFixed(4)}</div>
                  <div>Last test accuracy: {(overview?.training.last_test_acc ?? 0).toFixed(4)}</div>
                  <div>Last train accuracy: {(overview?.training.last_train_acc ?? 0).toFixed(4)}</div>
                  <div>Best epoch: {overview?.training.best_epoch ?? 'n/a'}</div>
                </div>
              </div>
            </div>
            <div className="mt-4 grid gap-4 md:grid-cols-2">
              <div className="app-surface-muted rounded-2xl p-4">
                <div className="text-xs uppercase tracking-[0.18em] app-muted-text">Dataset provenance</div>
                <div className="mt-3 space-y-2 text-sm" style={{ color: 'var(--app-text)' }}>
                  <div>Records: {overview?.dataset.records ?? 0}</div>
                  <div>Devices: {overview?.dataset.devices ?? 0}</div>
                  <div>Sessions: {overview?.dataset.sessions ?? 0}</div>
                  <div>Labelled devices: {overview?.training.labeled_devices ?? 0}</div>
                </div>
              </div>
              <div className="app-surface-muted rounded-2xl p-4">
                <div className="text-xs uppercase tracking-[0.18em] app-muted-text">Filesystem footprint</div>
                <div className="mt-3 space-y-2 text-sm" style={{ color: 'var(--app-text)' }}>
                  <div>Train dataset: {formatFileSize(overview?.filesystem.train_dataset_size_bytes ?? 0)}</div>
                  <div>Validation dataset: {formatFileSize(overview?.filesystem.val_dataset_size_bytes ?? 0)}</div>
                  <div>Predict dataset: {formatFileSize(overview?.filesystem.predict_dataset_size_bytes ?? 0)}</div>
                  <div>Model directory: {formatFileSize(overview?.filesystem.model_dir_size_bytes ?? 0)}</div>
                </div>
              </div>
            </div>
            <div className="mt-4">
              <div className="mb-3 text-xs font-semibold uppercase tracking-[0.18em] app-muted-text">Primary registered metrics</div>
              <div className="grid gap-3 md:grid-cols-2">
                {currentMetrics.map(([key, value]) => (
                  <div key={key} className="app-surface-muted rounded-2xl p-4">
                    <div className="text-xs uppercase tracking-[0.18em] app-muted-text">{key}</div>
                    <div className="mt-2 text-sm font-semibold" style={{ color: 'var(--app-text)' }}>{formatMetric(value)}</div>
                  </div>
                ))}
                {currentMetrics.length === 0 && <div className="text-sm app-muted-text">No extra model metrics registered.</div>}
              </div>
            </div>
          </div>

          <div className="app-surface rounded-[1.75rem] p-5 shadow-[0_18px_40px_rgba(15,23,42,0.08)]">
            <div className="text-sm font-semibold uppercase tracking-[0.18em] app-muted-text">Artifact inventory</div>
            <div className="mt-4 space-y-3">
              {currentArtifactInventory.map((item) => (
                <div key={item.path} className="app-surface-muted rounded-2xl p-4">
                  <div className="flex flex-wrap items-center justify-between gap-3">
                    <div>
                      <div className="font-semibold" style={{ color: 'var(--app-text)' }}>{item.name}</div>
                      <div className="mt-1 text-xs app-muted-text">{item.path}</div>
                    </div>
                    <div className="text-right text-xs app-muted-text">
                      <div>{formatFileSize(item.size_bytes)}</div>
                      <div>{formatTimestamp(item.modified_at_utc)}</div>
                    </div>
                  </div>
                </div>
              ))}
              {currentArtifactInventory.length === 0 && <div className="text-sm app-muted-text">No artifact inventory available for the current model directory.</div>}
            </div>
          </div>

          <div className="grid gap-5 lg:grid-cols-2">
            <div className="app-surface rounded-[1.75rem] p-5 shadow-[0_18px_40px_rgba(15,23,42,0.08)]">
              <div className="text-sm font-semibold uppercase tracking-[0.18em] app-muted-text">Training configuration</div>
              <pre className="mt-4 h-72 max-w-full overflow-x-auto overflow-y-auto whitespace-pre-wrap break-words rounded-2xl bg-slate-950 p-4 text-xs text-slate-100">
                {JSON.stringify(trainConfig, null, 2)}
              </pre>
            </div>
            <div className="app-surface rounded-[1.75rem] p-5 shadow-[0_18px_40px_rgba(15,23,42,0.08)]">
              <div className="text-sm font-semibold uppercase tracking-[0.18em] app-muted-text">Dataset manifest and label map</div>
              <pre className="mt-4 h-72 max-w-full overflow-x-auto overflow-y-auto whitespace-pre-wrap break-words rounded-2xl bg-slate-950 p-4 text-xs text-slate-100">
                {JSON.stringify({ dataset_manifest: datasetManifest, label_map: labelMap }, null, 2)}
              </pre>
            </div>
          </div>
        </section>

        <section className="space-y-5">
          <div className="app-surface rounded-[1.75rem] p-5 shadow-[0_18px_40px_rgba(15,23,42,0.08)]">
            <div className="text-sm font-semibold uppercase tracking-[0.18em] app-muted-text">Retraining lineage</div>
            <div className="mt-4 space-y-3">
              {latestSnapshots.map((snapshot, index) => (
                <div key={`${snapshot.version ?? snapshot.version_id ?? 'snapshot'}-${index}`} className="app-surface-muted rounded-2xl p-4">
                  <div className="flex flex-wrap items-center justify-between gap-3">
                    <div>
                      <div className="font-semibold" style={{ color: 'var(--app-text)' }}>{String(snapshot.version ?? snapshot.version_id ?? `snapshot_${index + 1}`)}</div>
                      <div className="mt-1 text-xs app-muted-text">{formatTimestamp(String(snapshot.created_at_utc ?? ''))}</div>
                    </div>
                    <div className="text-right text-xs app-muted-text">
                      {Object.entries(snapshot as Record<string, unknown>).slice(0, 3).map(([key, value]) => (
                        <div key={key}>{key}: {formatMetric(value)}</div>
                      ))}
                    </div>
                  </div>
                </div>
              ))}
              {latestSnapshots.length === 0 && <div className="text-sm app-muted-text">No retraining snapshots recorded yet.</div>}
            </div>
          </div>

          <div className="app-surface rounded-[1.75rem] p-5 shadow-[0_18px_40px_rgba(15,23,42,0.08)]">
            <div className="text-sm font-semibold uppercase tracking-[0.18em] app-muted-text">Validation evidence</div>
            <div className="mt-4 space-y-3">
              {latestValidation.map((report, index) => (
                <div key={`validation-${index}`} className="app-surface-muted rounded-2xl p-4">
                  <div className="flex flex-wrap items-center justify-between gap-3">
                    <div className="font-semibold" style={{ color: 'var(--app-text)' }}>Validation report {latestValidation.length - index}</div>
                    <div className="text-xs app-muted-text">{formatMetric((report as Record<string, unknown>).metrics ?? report)}</div>
                  </div>
                  <pre className="mt-3 h-40 max-w-full overflow-x-auto overflow-y-auto whitespace-pre-wrap break-words rounded-xl bg-slate-950 p-3 text-xs text-slate-100">
                    {JSON.stringify(report, null, 2)}
                  </pre>
                </div>
              ))}
              {latestValidation.length === 0 && <div className="text-sm app-muted-text">No validation reports stored yet.</div>}
            </div>
          </div>

          <div className="app-surface rounded-[1.75rem] p-5 shadow-[0_18px_40px_rgba(15,23,42,0.08)]">
            <div className="text-sm font-semibold uppercase tracking-[0.18em] app-muted-text">Registered model versions</div>
            <div className="mt-4 space-y-3">
              {models.map((model, index) => (
                <div key={`${model.version ?? 'model'}-${index}`} className="app-surface-muted rounded-2xl p-4">
                  <div className="flex flex-wrap items-center justify-between gap-3">
                    <div>
                      <div className="font-semibold" style={{ color: 'var(--app-text)' }}>{String(model.version ?? 'unknown_version')}</div>
                      <div className="mt-1 text-xs app-muted-text">{formatTimestamp(String(model.created_at_utc ?? ''))}</div>
                    </div>
                    <div className="text-right text-xs app-muted-text">
                      {Object.entries((model.metrics ?? {}) as Record<string, unknown>).slice(0, 3).map(([key, value]) => (
                        <div key={key}>{key}: {formatMetric(value)}</div>
                      ))}
                    </div>
                  </div>
                </div>
              ))}
              {models.length === 0 && <div className="text-sm app-muted-text">No model versions registered.</div>}
            </div>
          </div>
        </section>
      </div>
    </div>
  );
};
