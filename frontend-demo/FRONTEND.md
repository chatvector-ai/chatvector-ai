# ChatVector frontend design system

This document describes how the marketing homepage and navigation are styled so future changes stay consistent with the existing look.

## Color palette

Semantic tokens live in `app/globals.css` under `:root`. They are the single source of truth for the dark UI shell.

| Token | Value | Role |
| --- | --- | --- |
| `--background` | `#0a0c10` | Page backdrop; primary canvas behind sections. |
| `--surface` | `#111418` | Elevated panels: cards, code blocks, inset regions. |
| `--border` | `#1e2530` | Hairlines, outlines, grid lines, and dividers. |
| `--foreground` | `#e8edf5` | Primary text and high-contrast UI chrome. |
| `--muted` | `#6b7685` | Secondary copy, captions, de-emphasized labels. |
| `--accent` | `#00e5a0` | Brand teal: CTAs, active nav, highlights, success emphasis. |
| `--blue` | `#0080ff` | Secondary brand accent; gradients with `--accent`, tags, links tone. |

**Non-token colors:** Fake “IDE” syntax highlighting (keyword, string, comment hues), macOS window dots, and per-feature card icon colors are intentional exceptions. They are not part of the seven semantic tokens; use `rgb(...)` / `rgba(...)` or small inline `style` blocks where they are data-driven.

## Font stack

- **DM Sans** — body copy, headings, and UI text. The root layout uses it for the main page wrapper (`font-[family-name:DM_Sans,sans-serif]` on the homepage container; `globals.css` sets `body` to DM Sans).
- **JetBrains Mono** — monospace accents: section kicker lines (`// …`), filenames on code windows, tags/badges, and the wordmark-style logo treatment. Applied via `font-[family-name:JetBrains_Mono,monospace]` where needed.

## Spacing and layout conventions

- **Content width:** Main column is `max-w-[1100px]` with horizontal padding `px-8` (`2rem`) on sections; the nav uses `max-w-[1100px]` and `px-4` (`1rem`) to match the previous navbar gutters.
- **Vertical rhythm:** Major sections use `py-24` (`6rem`). The hero uses `pt-20` / `pb-16` / `px-8` to preserve the original top-heavy landing spacing.
- **Grids:** Two-column blocks use `grid` with `gap-12` and `md:grid-cols-2`. Feature cards use `grid-cols-[repeat(auto-fit,minmax(240px,1fr))]` with `gap-6`.
- **Cards:** Code samples and pipeline panels use `rounded-xl` (`12px`), `border border-(--border)`, and `p-6` or inner `py-3.5` / `px-6` as before.

## Component patterns

- **Section header:** Kicker (`// label`) in JetBrains Mono, `text-[0.78rem]`, `uppercase`, `tracking-[2px]`, `text-(--accent)`; title `text-[clamp(...)]`, `font-semibold`, `text-(--foreground)`; supporting copy `text-(--muted)` with `font-light` where the original used weight 300.
- **Primary CTA:** Filled `bg-(--accent)`, `text-black`, `rounded-lg`, `px-7 py-3`, hover lift via `hover:-translate-y-0.5` and shadow.
- **Secondary CTA:** `border border-(--border)`, transparent background, `hover:border-[rgb(61,69,85)]`, `hover:bg-(--surface)` (hover border is a fixed RGB lift, not a token).
- **Code window:** Surface background, border, title bar `bg-[rgb(24,28,34)]`, traffic-light dots, filename in mono + `text-(--muted)`.
- **Feature card:** The features section uses `bg-(--surface)`; each card uses `bg-(--background)`, `border-(--border)`, hover `border-[rgb(61,69,85)]` and `-translate-y-[3px]`. Tag pill uses `color-mix` with `var(--blue)` for fill and stroke.
- **Developer checklist row:** `bg-(--surface)`, full border + `border-l-[3px] border-l-(--accent)`, check icon `text-(--accent)` / `stroke="currentColor"`.

## Tailwind vs inline styles

**Default rule:** Prefer Tailwind utilities. Reference tokens with Tailwind v4’s CSS-variable shorthand, e.g. `bg-(--surface)`, `text-(--accent)`, `border-(--border)`, `text-(--muted)`, `from-(--accent)`, `to-(--blue)`. These compile to `var(--surface)`, etc., and stay aligned with `globals.css`.

**`tailwind.config.ts`:** The file maps the same seven names to `var(--…)` under `theme.extend.colors`. In this repo’s Tailwind v4 setup, that file is loaded only if you opt in from CSS (for example `@config "./tailwind.config.ts"` next to `@import "tailwindcss"` in `globals.css`). Until then, the parenthesis form (`bg-(--surface)`) is what the build emits. After opting in, you can also use short names like `bg-surface`, `text-accent`, `border-border`.

**When inline styles are OK:** Use a short JSX comment and keep the smallest possible `style` object when:

- A **radial gradient** or other background cannot be expressed cleanly as utilities.
- You need **exact legacy rgba** values (hero chip, step badge, header scrim) to avoid any visual drift.
- **Two-axis repeating linear gradients** with a CSS variable stroke color.
- Colors are **fully dynamic** from data (syntax-highlight spans, feature icon colors).

Do not introduce new hardcoded hex colors for semantic UI; use the tokens or `rgb()` for non-token accents.
