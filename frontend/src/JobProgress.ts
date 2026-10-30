/** Only sampler counters describe a useful percentage; discovered nodes do not. */
export function jobProgressPercent(progress?: Record<string, unknown> | null): number | null {
  if (!progress) return null;
  if (typeof progress.step === 'number' && Number.isFinite(progress.step) && typeof progress.steps === 'number' && Number.isFinite(progress.steps) && progress.steps > 0) {
    return Math.max(0, Math.min(100, Math.round(progress.step / progress.steps * 100)));
  }
  const value = typeof progress.value === 'number' && Number.isFinite(progress.value) ? progress.value : null;
  if ('max' in progress) {
    return value !== null && typeof progress.max === 'number' && Number.isFinite(progress.max) && progress.max > 0
      ? Math.max(0, Math.min(100, Math.round(value / progress.max * 100))) : null;
  }
  return null;
}
