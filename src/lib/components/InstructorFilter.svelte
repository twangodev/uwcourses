<script lang="ts">
  import { untrack } from "svelte";
  import type { SuggestionsResponse } from "$lib/api/schemas";
  import { courseTitle } from "$lib/format";

  let {
    revision,
    name = null,
    onPick,
  }: {
    revision: string;
    name?: string | null;
    onPick: (uid: string) => void;
  } = $props();

  let text = $state("");
  let items = $state<{ uid: string; name: string }[]>([]);
  let open = $state(false);

  $effect(() => {
    const typed = text.trim();
    if (typed.length < 2) {
      items = [];
      return;
    }
    const controller = new AbortController();
    const timer = setTimeout(async () => {
      try {
        const response = await fetch(
          `/api/suggest?${new URLSearchParams({ q: typed, revision, kind: "instructor" })}`,
          { signal: controller.signal },
        );
        if (!response.ok) return;
        const data = (await response.json()) as SuggestionsResponse;
        if (controller.signal.aborted) return;
        items = data.items.flatMap((row) =>
          "instructor_uid" in row
            ? [{ uid: row.instructor_uid, name: row.name || "Unknown instructor" }]
            : [],
        );
      } catch {
        if (!controller.signal.aborted) items = [];
      }
    }, 180);
    return () => {
      clearTimeout(timer);
      controller.abort();
    };
  });

  function pick(uid: string) {
    text = untrack(() => "");
    items = [];
    open = false;
    onPick(uid);
  }
</script>

<div class="min-w-0">
  <span class="mb-2 block text-[12px] text-muted">Instructor</span>
  {#if name}
    <button
      class="inline-flex max-w-full items-center gap-2 border border-border bg-surface px-2 py-1 text-[12px] text-foreground"
      type="button"
      onclick={() => onPick("")}
    >
      <span class="truncate">{courseTitle(name)}</span>
      <span aria-hidden="true">×</span>
      <span class="sr-only">Clear instructor</span>
    </button>
  {:else}
    <input
      class="w-full min-w-0 border border-border bg-surface px-2 py-1 text-[12px] text-foreground"
      aria-label="Instructor"
      placeholder="A professor’s name…"
      bind:value={text}
      onfocus={() => (open = true)}
      onblur={() => (open = false)}
    />
    {#if open && items.length}
      <ul class="m-0 mt-1 list-none border border-border bg-canvas p-1" role="listbox">
        {#each items as item (item.uid)}
          <li>
            <button
              class="block w-full px-2 py-1 text-left text-[12px]"
              type="button"
              onmousedown={(event) => event.preventDefault()}
              onclick={() => pick(item.uid)}
            >
              {courseTitle(item.name)}
            </button>
          </li>
        {/each}
      </ul>
    {/if}
  {/if}
</div>

<style>
  input,
  button {
    font: inherit;
  }
</style>
