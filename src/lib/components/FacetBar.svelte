<script lang="ts">
  import { untrack } from "svelte";
  import { Tween, prefersReducedMotion } from "svelte/motion";
  import { cubicOut } from "svelte/easing";
  let {
    x,
    y,
    width,
    height,
    fill,
    opacity = 1,
    vertical = false,
    value,
  }: {
    x: number;
    y: number;
    width: number;
    height: number;
    fill: string;
    opacity?: number;
    vertical?: boolean;
    value: string;
  } = $props();
  const bounds = new Tween(
    untrack(() => ({
      x,
      y: vertical ? y + height : y,
      width: vertical ? width : 0,
      height: vertical ? 0 : height,
    })),
    { easing: cubicOut },
  );
  $effect(() => {
    bounds.set(
      { x, y, width, height },
      {
        duration: prefersReducedMotion.current ? 0 : 240,
      },
    );
  });
</script>

<rect
  x={bounds.current.x}
  y={bounds.current.y}
  width={Math.max(0, bounds.current.width)}
  height={Math.max(0, bounds.current.height)}
  rx={vertical ? 2 : 1.5}
  {fill}
  {opacity}
  data-value={value}
/>
