<script lang="ts">
  import "../app.css";
  import { representationUrl, isDocument } from "$lib/documents";
  import { pageSeo, jsonLd } from "$lib/seo";
  import { Sun, Moon, Monitor } from "@lucide/svelte";
  import { page } from "$app/state";
  import { dev } from "$app/environment";
  import { onMount } from "svelte";
  let { data, children } = $props();
  let seo = $derived(pageSeo(page.data, page.url.pathname, page.status));
  const themes = ["system", "light", "dark"] as const;
  let theme = $state<(typeof themes)[number]>("system");
  let nextTheme = $derived(themes[(themes.indexOf(theme) + 1) % themes.length]);
  let themeLabel = $derived(`Color theme: ${theme}. Switch to ${nextTheme}`);
  function cycleTheme() {
    theme = nextTheme;
    apply();
  }
  let fullscreenMap = $derived(
    /^\/explorer\/[^/]+\/?$/.test(page.url.pathname),
  );
  function apply() {
    document.documentElement.classList.toggle(
      "dark",
      theme === "dark" ||
        (theme === "system" &&
          matchMedia("(prefers-color-scheme: dark)").matches),
    );
    try {
      if (theme === "system") localStorage.removeItem("theme");
      else localStorage.setItem("theme", theme);
    } catch {}
  }
  onMount(() => {
    document.documentElement.dataset.hydrated = "true";
    try {
      const saved = localStorage.getItem("theme");
      theme = saved === "light" || saved === "dark" ? saved : "system";
    } catch {}
    const media = matchMedia("(prefers-color-scheme: dark)");
    media.addEventListener("change", apply);
    return () => media.removeEventListener("change", apply);
  });
</script>

<svelte:head>
  {#if !dev && page.url.origin === "https://uwcourses.com"}
    <script
      src="https://rybbit.twango.dev/api/script.js"
      data-site-id="1"
      defer
    ></script>
  {/if}
  <link
    rel="service-desc"
    type="application/vnd.oai.openapi+json"
    href="https://uwcourses.com/openapi.json"
  />
  <link
    rel="api-catalog"
    type="application/linkset+json"
    href="https://uwcourses.com/.well-known/api-catalog"
  />
  <title>{seo.title}</title>
  <meta name="description" content={seo.description} />
  <link rel="canonical" href={seo.canonical} />
  {#if page.status === 200 && isDocument(page.url.pathname)}
    <link
      rel="alternate"
      type="text/markdown"
      href={"https://uwcourses.com" +
        representationUrl(page.url.pathname, "md", page.url.search)}
    />
    <link
      rel="alternate"
      type="application/json"
      href={"https://uwcourses.com" +
        representationUrl(page.url.pathname, "json", page.url.search)}
    />
  {/if}
  <meta
    name="robots"
    content={seo.noindex
      ? "noindex,follow"
      : "index,follow,max-image-preview:large"}
  />
  <meta property="og:type" content={page.data.post ? "article" : "website"} />
  {#if page.data.post}<meta
      property="article:published_time"
      content={page.data.post.date}
    />{/if}
  <meta property="og:site_name" content="UW Courses" />
  <meta property="og:locale" content="en_US" />
  <meta property="og:title" content={seo.title} />
  <meta property="og:description" content={seo.description} />
  <meta property="og:url" content={seo.canonical} />
  <meta property="og:image" content={seo.image} />
  <meta property="og:image:type" content="image/png" />
  <meta property="og:image:width" content="1200" />
  <meta property="og:image:height" content="630" />
  <meta property="og:image:alt" content={seo.imageAlt} />
  <meta name="twitter:card" content="summary_large_image" />
  <meta name="twitter:image" content={seo.image} />
  <meta name="twitter:image:alt" content={seo.imageAlt} />
  <meta name="twitter:title" content={seo.title} />
  <meta name="twitter:description" content={seo.description} />
  {@html `<script type="application/ld+json">${jsonLd(seo.structuredData)}</script>`}
</svelte:head>

<a
  class="fixed top-4 left-4 z-100 bg-canvas border border-accent skip-link py-2 px-4"
  href="#main">Skip to content</a
>
{#if !fullscreenMap}<header class="border-b border-b-border">
    <nav
      class="max-w-345 m-auto flex justify-between items-center gap-4 py-4 px-10"
      aria-label="Main navigation"
    >
      <a
        class="inline-flex items-center gap-0.5 text-[1.6rem] font-[650] tracking-[-0.05em] text-foreground brand"
        href="/"
        ><img
          class="mr-[9px]"
          src="/uwcourses-logo.svg"
          alt=""
          width="28"
          height="28"
        /><span>uwcourses</span></a
      >
      <div class="flex-nowrap row">
        {#each [{ href: "/search", label: "courses", active: /^\/(search|courses)(\/|$)/.test(page.url.pathname) }, { href: "/departments", label: "departments", active: page.url.pathname.startsWith("/departments") }, { href: "/instructors/by-rating-count", label: "instructors", active: page.url.pathname.startsWith("/instructors") }] as link}
          <a href={link.href} aria-current={link.active ? "page" : undefined}
            >{link.label}</a
          >
        {/each}
        <button
          class="border-0 p-0 bg-transparent cursor-pointer rounded-[4px] w-8 h-8 grid place-items-center text-muted theme-control"
          type="button"
          aria-label={themeLabel}
          title={themeLabel}
          onclick={cycleTheme}
        >
          {#if theme === "dark"}<Moon
              size={16}
            />{:else if theme === "light"}<Sun size={16} />{:else}<Monitor
              size={16}
            />{/if}
        </button>
      </div>
    </nav>
  </header>{/if}
<main class="page" class:map-page={fullscreenMap} id="main">
  {#key page.url.pathname}<div class="route-content">
      {@render children()}
    </div>{/key}
</main>
{#if !fullscreenMap}<footer
    class="flex justify-between items-start gap-y-6 gap-x-12 border-t border-t-border text-[0.8rem] pt-6 pb-8 page"
  >
    <div>
      <p class="mt-0 mb-1.5 site-credit mx-0">
        Made by <a href="https://twango.dev/?utm_source=uwcourses.com"
          >James Ding</a
        >
        and
        <a href="https://github.com/twangodev/uwcourses/graphs/contributors"
          >contributors</a
        >.
      </p>
      <p class="muted">
        Not affiliated with or endorsed by the University of Wisconsin–Madison.
      </p>
    </div>
    <div class="shrink-0 text-right footer-resources">
      <nav class="flex justify-end gap-5 footer-links" aria-label="Resources">
        <a class="py-1 px-0" href="/blog">Blog</a>
        <a class="py-1 px-0" href="/stats">Stats</a>
        <a class="py-1 px-0" href="/openapi">API</a>
        <a class="py-1 px-0" href="https://github.com/twangodev/uwcourses"
          >GitHub</a
        >
        <a
          class="py-1 px-0"
          href={`https://huggingface.co/datasets/${data.status.repository}`}
          >Dataset</a
        >
      </nav>
      <p class="mt-1.5 mb-0 muted scan-date mx-0">
        Scanned {data.status.observed_at.slice(0, 10)}
      </p>
    </div>
  </footer>{/if}

<style>
  .page.map-page {
    max-width: none;
    padding: 0;
    margin: 0;
  }
  .map-page .route-content {
    animation: none;
    transform: none;
  }
  .skip-link {
    clip-path: inset(50%);
  }
  .skip-link:focus {
    clip-path: none;
  }
  header nav a[aria-current="page"] {
    color: var(--accent);
  }
  header nav .row {
    font: 14px var(--font-sans);
  }
  .theme-control:hover {
    color: var(--text);
  }
  .theme-control:focus-visible {
    outline: 2px solid var(--accent);
    outline-offset: 2px;
    border-radius: 4px;
  }
  @media (max-width: 640px) {
    footer.page {
      flex-direction: column;
    }
    .footer-resources {
      text-align: left;
    }
    .footer-links {
      justify-content: flex-start;
    }
    header nav {
      padding: 1rem;
      flex-wrap: wrap;
    }
    header nav .row {
      width: 100%;
      justify-content: space-between;
      gap: 12px;
      font-size: 13px;
    }
    .brand {
      font-size: 22px;
    }
    .brand img {
      width: 24px;
      height: 24px;
      margin-right: 6px;
    }
  }
</style>
