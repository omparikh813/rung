# Design System Master File

> Generated with the ui-ux-pro-max skill (query: "B2B SaaS operations dashboard data dense"),
> then adjusted for RUNG as described in Section 5 of the PRD. Where the skill's output
> and the RUNG adjustments differ, the RUNG adjustments win. Every template follows this file.

---

**Project:** RUNG
**Generated:** 2026-11-11
**Category:** Analytics Dashboard
**Style:** Data-Dense Dashboard (kept for type and tables, simplified for new workers)

---

## Logo

- Use `static/img/rung_logo.png` exactly as supplied. Do not redraw, stretch, recolor, or crop it.
- Login page: centered above the form at 120 px tall.
- Sidebar: top left at 36 px tall, next to the word RUNG in navy.
- Favicon: `static/img/favicon.png`, the same image at 32 px.
- Keep clear space around the logo of at least one quarter of its height.
- Only place it on white or the page background.

## Color Palette

The skill's colors are replaced by these tokens, taken from the logo. They live in
`static/css/input.css`.

| Token | Value | Use |
|-------|-------|-----|
| `--color-primary` (brand blue) | `#41A9DA` | Primary buttons, active sidebar item, selected tab underline, focus rings, level meters, progress rings, upload drop zone, help level badge, skeleton shimmer tint |
| `--color-on-primary` | `#013055` | Text and icons on brand blue (5.1:1). Never put white text on brand blue (2.7:1 fails). |
| `--color-primary-strong` | `#176F9C` | Brand blue text on white or tinted backgrounds: links, Waiting on Specialist status, numbers in stat cards (5.5:1 on white) |
| `--color-primary-soft` | `#E8F5FC` | Hover rows, selected rows, active nav background, info panels |
| `--color-navy` | `#013055` | Headings, sidebar text, the RUNG wordmark, dark icons |
| `--color-jade` | `#52C299` | Success fills, correct results, Skill Passport progress, level drop toast accent. Text on it uses navy. |
| `--color-jade-strong` | `#187A56` | Jade text on white or soft backgrounds: the Ready status (5.3:1) |
| `--color-jade-soft` | `#E9F8F2` | Ready and success backgrounds |
| `--color-teal` | `#11A0A6` | Sparingly, as a second chart color in the Skill Passport |
| `--color-background` | `#F7FBFE` | Page background |
| `--color-card` | `#FFFFFF` | Cards and panels |
| `--color-text` | `#0F172A` | Body text |
| `--color-muted` | `#475569` | Secondary text |
| `--color-border` | `#D6EAF5` | Borders and table lines |
| `--color-warning` | `#B45309` | Needs Fix and flagged fields |
| `--color-destructive` | `#DC2626` | Denied and errors |

Two soft tints support the status colors: `--color-warning-soft` `#FFFBEB` and
`--color-destructive-soft` `#FEF2F2`. Red text on the red tint is only 4.4:1, so text
on `--color-destructive-soft` stays in `--color-text` with a red icon and border.

### Color balance

- Roughly 60% neutrals (white, background, text), 30% brand blue, and 10% navy, jade,
  teal, and status colors. Brand blue is the color people remember from the site.
- Jade means success or progress only. Never use it for buttons or links.
- Primary buttons are brand blue with navy text. Secondary buttons are white with a
  brand blue border and navy text.

### Status colors

Every status badge shows a word and an icon, never color alone.

| Status | Text | Background | Icon |
|--------|------|------------|------|
| New | `#475569` | `#FFFFFF` with border | circle-dot |
| Denied | `#DC2626` | `#FFFFFF` with red border | circle-x |
| Needs Fix | `#B45309` | `#FFFBEB` | triangle-alert |
| Ready | `#187A56` | `#E9F8F2` | circle-check |
| Waiting on Specialist | `#176F9C` | `#E8F5FC` | clock |
| Submitted | `#475569` | `#FFFFFF` with border | send |
| Closed | `#475569` | `#FFFFFF` with border | archive |

## Typography

- **UI font:** Fira Sans (400, 500, 600, 700)
- **Codes, IDs, and amounts:** Fira Code, so they are easy to compare character by character
- **Google Fonts:** https://fonts.googleapis.com/css2?family=Fira+Code:wght@400;500;600&family=Fira+Sans:wght@400;500;600;700&display=swap
- Body text is 16 px on mobile and never below 14 px in tables.

## Spacing

| Token | Value | Usage |
|-------|-------|-------|
| `--space-xs` | `4px` | Tight gaps |
| `--space-sm` | `8px` | Icon gaps, inline spacing |
| `--space-md` | `16px` | Standard padding |
| `--space-lg` | `24px` | Section padding |
| `--space-xl` | `32px` | Large gaps |

These map to Tailwind's spacing scale (1, 2, 4, 6, 8).

## Shadows

| Level | Value | Usage |
|-------|-------|-------|
| `--shadow-sm` | `0 1px 2px rgba(1,48,85,0.06)` | Cards |
| `--shadow-md` | `0 4px 6px rgba(1,48,85,0.10)` | Row lift on hover, toasts |
| `--shadow-lg` | `0 10px 15px rgba(1,48,85,0.12)` | Dialogs |

## Layout

- Left sidebar navigation. It collapses to a top menu under 1024 px.
- Top bar with the user's name and role badge.
- The demo data banner on every page: "Demo data only. Do not enter real patient information."
- Page content in a max width container.
- **Simple over dense.** RUNG keeps the data dense style's type and tables, but each
  screen has one primary action and generous spacing, because users are new workers.

## Components

- **Buttons:** 8 px radius, 600 weight, at least 44 px tall. One primary button per screen.
- **Cards:** white, 1 px border in `--color-border`, 12 px radius, `--shadow-sm`. Cards
  do not move on hover unless they are links.
- **Inputs:** 1 px border, 8 px radius, a visible label on every input, focus ring in brand blue.
- **Flagged fields** in the claim form get an amber left border, an icon, and the issue
  text directly under the field.
- **Form errors** appear below the input, linked with `aria-describedby`, and are
  announced with `role="alert"`.
- **Tables:** sticky header, row hover in `--color-primary-soft`, numbers and codes in Fira Code.
- **Dialogs:** centered, dimmed background, 16 px radius, max width 500 px. Escape closes,
  Enter confirms, focus stays inside while open. At most one dialog open at a time.
- **Toasts:** bottom right, auto dismiss after 4 seconds, `aria-live`.
- **Loading:** every AI call shows an inline spinner with the text "Checking claim..."
  using `hx-indicator`. Buttons disable while a request runs.
- **Icons:** Lucide SVG icons from `static/icons/`. No emoji as icons.

## Interaction and Motion

The site should feel fast, responsive, and polished while every screen stays simple:
one primary button, at most one dialog open at a time, and no motion that plays on its own.

| Where | Interaction |
|-------|-------------|
| Everywhere | HTMX swaps fade in over 150 to 200 ms. Alpine `x-transition` on menus and the mobile sidebar. Toasts confirm save, submit, close, request sent, request resolved, and upload complete. |
| My Queue | Tabs and search update the table without a page reload. Sticky table header. Rows lift slightly on hover and open on click or Enter. |
| Claim Workspace | While the AI reviews, the issues panel shows shimmering skeleton lines and "Checking claim...". Flagged fields fade in an amber border. Clicking an issue card scrolls to its field, focuses it, and pulses the highlight once. Show answer expands the card smoothly. The clinical note collapses and expands. The action bar stays fixed at the bottom. |
| Dialogs | Ask a specialist, Submit confirmation, and Close claim open as centered dialogs with a dimmed background. |
| Help Requests | The sidebar count badge updates after a request is sent or resolved. The resolution form reveals the Case Library fields when the checkbox is checked. |
| Skill Passport | Level meters and accuracy rings animate from zero on load, and numbers count up. When a help level drops, a toast says which category improved. |
| Claim Upload | The drop zone highlights while a file is dragged over it. Preview rows slide in, with invalid rows marked in red and their message beside them. |
| Accessibility | All motion is under 300 ms and turns off under `prefers-reduced-motion`. Every interactive element works with the keyboard and has a visible focus ring. |

## Anti-Patterns (Do NOT Use)

- Ornate design
- Emojis as icons
- Missing `cursor: pointer` on clickable elements
- Hovers that shift the layout
- Text contrast below 4.5:1
- Instant state changes with no transition
- Invisible focus states
- White text on brand blue
- Jade on buttons or links
- Color as the only signal for a status

## Pre-Delivery Checklist

- [ ] Text contrast at least 4.5:1
- [ ] Visible focus rings
- [ ] Every control reachable with the keyboard
- [ ] A label on every input
- [ ] No emoji as icons; all icons from Lucide
- [ ] `cursor-pointer` on all clickable elements
- [ ] Hover transitions 150 to 300 ms
- [ ] `prefers-reduced-motion` respected
- [ ] Responsive at 375, 768, 1024, and 1440 px
- [ ] No horizontal scroll on mobile
- [ ] No content hidden behind the sticky action bar
