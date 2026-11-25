import { onBeforeUnmount } from "vue";

/**
 * Coordinates abortable HTTP requests and single-active polling timers across a page lifecycle.
 */
export function useAbortablePolling() {
  let pollTimer: number | undefined;
  let disposed = false;
  let selectionVersion = 0;
  const controllers = new Set<AbortController>();

  function clearPoll() {
    clearTimeout(pollTimer);
    pollTimer = undefined;
  }

  function schedulePoll(fn: () => void, delayMs: number) {
    clearPoll();
    if (!disposed) pollTimer = window.setTimeout(fn, delayMs);
  }

  function nextVersion() {
    return ++selectionVersion;
  }

  function isCurrent(version: number) {
    return !disposed && version === selectionVersion;
  }

  function isDisposed() {
    return disposed;
  }

  function createAbortable(timeoutMs = 15000) {
    const controller = new AbortController();
    controllers.add(controller);
    const timer = window.setTimeout(() => controller.abort(), timeoutMs);
    return {
      controller,
      signal: controller.signal,
      cleanup() {
        clearTimeout(timer);
        controllers.delete(controller);
      },
    };
  }

  onBeforeUnmount(() => {
    disposed = true;
    selectionVersion++;
    clearPoll();
    controllers.forEach((c) => c.abort());
    controllers.clear();
  });

  return {
    clearPoll,
    schedulePoll,
    nextVersion,
    isCurrent,
    isDisposed,
    createAbortable,
  };
}
