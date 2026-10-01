<script module lang="ts">
  export type SelectOption = {
    value: string;
    label: string;
    disabled?: boolean;
    title?: string;
  };
</script>

<script lang="ts">
  import type { Snippet } from "svelte";
  import { Select } from "bits-ui";
  import { Check, ChevronDown } from "@lucide/svelte";
  let {
    value = $bindable(""),
    options,
    label,
    onChange,
    variant = "default",
    width = "auto",
    onOpenChange,
    header,
    children,
    optionContent,
  }: {
    value?: string;
    options: SelectOption[];
    label: string;
    onChange?: (value: string) => void;
    variant?: "default" | "compact" | "segmented";
    width?: "auto" | "filter";
    onOpenChange?: (open: boolean) => void;
    header?: Snippet;
    children?: Snippet<[Snippet<[SelectOption]>]>;
    optionContent?: Snippet<[SelectOption]>;
  } = $props();
  const variants = {
    default: "border border-border rounded-control bg-surface py-1",
    compact:
      "h-7.5 box-border border border-border rounded-control bg-surface py-0",
    segmented:
      "h-7 border-0 border-x border-border rounded-none bg-transparent py-0",
  };
</script>

{#snippet optionRow(option: SelectOption)}
  <Select.Item
    value={option.value || "__all"}
    label={option.label}
    disabled={option.disabled}
    aria-label={option.label}
    title={option.title}
    class="course-select-item flex cursor-pointer items-center justify-between gap-2 rounded-[3px] px-[9px] py-[7px] text-[12px] leading-[18px] outline-none data-highlighted:bg-border data-disabled:cursor-default data-disabled:opacity-60"
  >
    {#snippet children({ selected })}
      {#if optionContent}{@render optionContent(option)}{:else}<span
          class="min-w-0 truncate">{option.label}</span
        >{/if}
      <span class="select-check" aria-hidden="true"
        >{#if selected}<Check size={14} class="text-accent" />{/if}</span
      >
    {/snippet}
  </Select.Item>
{/snippet}

<Select.Root
  {onOpenChange}
  type="single"
  value={value || "__all"}
  onValueChange={(next) => {
    value = next === "__all" ? "" : next;
    onChange?.(value);
  }}
>
  <Select.Trigger
    class={`course-select-trigger inline-flex items-center justify-between gap-4 px-2.5 text-[12px] leading-[18px] text-foreground cursor-pointer focus-visible:outline-2 focus-visible:outline-accent focus-visible:outline-offset-2 ${variants[variant]} ${width === "filter" ? "max-w-60 [@media(max-width:600px)]:max-w-full" : "max-w-full"}`}
    aria-label={label}
  >
    <span class="truncate"
      >{options.find((option) => option.value === value)?.label || label}</span
    ><ChevronDown size={14} class="shrink-0 text-muted" />
  </Select.Trigger>
  <Select.Portal>
    <Select.Content
      class="course-select-content z-100 min-w-(--bits-select-anchor-width) max-w-[min(360px,calc(100vw-24px))] max-h-[min(320px,var(--bits-select-content-available-height))] overflow-y-auto rounded-[6px] border border-border bg-surface p-1 text-foreground shadow-[0_8px_24px_#0002]"
      sideOffset={5}
    >
      {#if header}<div class="select-header">{@render header()}</div>{/if}
      <Select.Viewport>
        {#if children}{@render children(
            optionRow,
          )}{:else}{#each options as option (option.value)}{@render optionRow(
              option,
            )}{/each}{/if}
      </Select.Viewport>
    </Select.Content>
  </Select.Portal>
</Select.Root>

<style>
  .select-check {
    width: 14px;
    height: 14px;
    flex-shrink: 0;
  }
  .select-header {
    padding: 4px 8px 6px;
    border-bottom: 1px solid var(--border);
    margin-bottom: 4px;
  }
</style>
