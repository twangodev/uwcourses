<script lang="ts">
  import type { SuggestionsResponse } from "$lib/api/schemas";
  import { courseTitle } from "$lib/format";
  import { X } from "@lucide/svelte";

  let {
    revision,
    name = null,
    onPick,
  }: {
    revision: string;
    name?: string | null;
    onPick: (uid: string) => void;
  } = $props();
  const id = $props.id();
  let text = $state("");
  let items = $state<{ uid: string; name: string; detail: string }[]>([]);
  let focused = $state(false);
  let dismissed = $state(false);
  let active = $state(-1);
  let pending = $state(false);
  let message = $state("");
  let open = $derived(focused && !dismissed && text.trim().length >= 2);

  $effect(() => {
    const typed = text.trim();
    items = [];
    active = -1;
    message = "";
    if (!open) {
      pending = false;
      return;
    }
    pending = true;
    const controller = new AbortController();
    const timer = setTimeout(async () => {
      try {
        const response = await fetch(
          `/api/suggest?${new URLSearchParams({ q: typed, revision, kind: "instructor" })}`,
          { signal: controller.signal },
        );
        if (!response.ok) throw new Error("Suggestions unavailable");
        const data = (await response.json()) as SuggestionsResponse;
        if (controller.signal.aborted) return;
        items = data.items.flatMap((row) =>
          "instructor_uid" in row
            ? [
                {
                  uid: row.instructor_uid,
                  name: row.name || "Unknown instructor",
                  detail: `${row.current ? "Current teaching recorded" : "Historical teaching recorded"}${row.bayesian_quality != null ? ` · ${row.bayesian_quality.toFixed(1)}/5 adjusted` : ""}`,
                },
              ]
            : [],
        );
        message = items.length
          ? `${items.length} instructors available`
          : "No matching instructors.";
      } catch {
        if (!controller.signal.aborted)
          message = "Suggestions unavailable. Please try again.";
      } finally {
        if (!controller.signal.aborted) pending = false;
      }
    }, 180);
    return () => {
      clearTimeout(timer);
      controller.abort();
    };
  });

  function pick(uid: string) {
    text = "";
    items = [];
    dismissed = true;
    onPick(uid);
  }
  function keydown(event: KeyboardEvent) {
    if (event.key === "Escape") {
      dismissed = true;
      active = -1;
    } else if (event.key === "ArrowDown" || event.key === "ArrowUp") {
      event.preventDefault();
      dismissed = false;
      if (items.length)
        active =
          (active +
            (event.key === "ArrowDown" ? 1 : active < 0 ? 0 : -1) +
            items.length) %
          items.length;
    } else if (event.key === "Enter" && open && active >= 0 && items[active]) {
      event.preventDefault();
      pick(items[active].uid);
    }
  }
</script>

<div class="instructor-filter">
  {#if name}
    <button
      class="selected"
      type="button"
      aria-label="Clear instructor"
      onclick={() => onPick("")}
      ><span>{courseTitle(name)}</span><X
        size={15}
        aria-hidden="true"
      /></button
    >
  {:else}
    <input
      aria-label="Search instructors"
      placeholder="Search instructor names…"
      bind:value={text}
      role="combobox"
      aria-autocomplete="list"
      aria-expanded={open}
      aria-controls={`${id}-suggestions`}
      aria-activedescendant={open && active >= 0
        ? `${id}-${active}`
        : undefined}
      autocomplete="off"
      maxlength="200"
      onfocus={() => (focused = true)}
      onblur={() => (focused = false)}
      oninput={() => (dismissed = false)}
      onkeydown={keydown}
    />
    <span class="sr-only" role="status">{pending ? "Searching…" : message}</span
    >
    {#if open}
      <div class="suggestions">
        <ul
          id={`${id}-suggestions`}
          role="listbox"
          aria-label="Instructor suggestions"
          aria-busy={pending}
        >
          {#each items as item, index (item.uid)}
            <li
              id={`${id}-${index}`}
              role="option"
              aria-selected={active === index}
            >
              <button
                type="button"
                tabindex="-1"
                onpointerdown={(event) => event.preventDefault()}
                onclick={() => pick(item.uid)}
                ><span>{courseTitle(item.name)}</span><small
                  >{item.detail}</small
                ></button
              >
            </li>
          {/each}
        </ul>
        {#if pending || !items.length}<p>
            {pending ? "Searching…" : message}
          </p>{/if}
      </div>
    {/if}
  {/if}
</div>

<style>
  .instructor-filter {
    position: relative;
    width: 100%;
    max-width: 320px;
  }
  input,
  .selected {
    width: 100%;
    min-height: 42px;
    background: var(--bg);
    font-size: 13px;
  }
  .selected {
    display: flex;
    justify-content: space-between;
    align-items: center;
    gap: 12px;
    text-align: left;
  }
  .selected span {
    min-width: 0;
    overflow-wrap: anywhere;
  }
  .selected :global(svg) {
    flex-shrink: 0;
  }
  .suggestions {
    position: absolute;
    z-index: 50;
    width: 100%;
    margin-top: 5px;
    padding: 4px;
    border: 1px solid var(--border);
    border-radius: 6px;
    background: var(--bg);
    box-shadow: var(--surface-shadow);
  }
  ul {
    list-style: none;
    padding: 0;
    margin: 0;
  }
  li button {
    display: grid;
    gap: 3px;
    width: 100%;
    padding: 10px;
    border: 0;
    background: transparent;
    text-align: left;
    font-size: 13px;
  }
  li[aria-selected="true"] button,
  li button:hover {
    background: var(--surface);
  }
  small {
    color: var(--muted);
    font-size: 11px;
  }
  p {
    padding: 10px;
    font-size: 12px;
    color: var(--muted);
  }
</style>
