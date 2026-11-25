import { onBeforeUnmount, onMounted, ref, watch, type Ref } from "vue";

/**
 * Tracks an element's content width with ResizeObserver, clamped to a minimum width.
 */
export function useElementWidth(target: Ref<HTMLElement | undefined>, initial = 720, minWidth = 240) {
  const width = ref(initial);
  let observer: ResizeObserver | undefined;

  onMounted(() => {
    if (typeof ResizeObserver === "undefined") return;
    observer = new ResizeObserver(([entry]) => {
      if (entry) width.value = Math.max(minWidth, entry.contentRect.width);
    });
    watch(
      target,
      (el, old) => {
        if (old) observer?.unobserve(old);
        if (el) observer?.observe(el);
      },
      { immediate: true },
    );
  });

  onBeforeUnmount(() => {
    observer?.disconnect();
  });

  return width;
}
