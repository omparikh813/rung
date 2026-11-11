# Design System Master File (v2)

> Version 2 replaces the blue, data dense look from the PRD with a green,
> "editorial meets healthcare" look, at the owner's request. Where this file and
> Section 5 of the PRD differ, this file wins. Every template follows it.

**Project:** RUNG
**Style:** Modern editorial meets healthcare: off-white pages, deep green headings,
large rounded cards, soft shadows, playful medical illustrations, bold type.
**Audience:** new billing workers and the clinic owners who employ them.

---

## Logo

- Use `static/img/rung_logo.png` exactly as supplied. Do not redraw, stretch, recolor, or crop it.
- The file has a white background, so it always sits inside a white rounded tile.
- Favicon: `static/img/favicon.png`, the same image at 32 px.

## Color Palette

Tokens live in `static/css/input.css`.

| Token | Value | Use |
|-------|-------|-----|
| `--color-primary` | `#1B7F5F` | Primary buttons, active tabs, focus rings, meters, progress rings. White text on it is 4.9:1. |
| `--color-on-primary` | `#FFFFFF` | Text and icons on primary |
| `--color-primary-strong` | `#14664B` | Green text on white or tinted backgrounds: links, numbers, eyebrows |
| `--color-primary-soft` | `#E3F5EC` | Mint tint: hover rows, info panels, icon tiles |
| `--color-mint` | `#C9ECD9` | Stronger mint for gradients and decoration |
| `--color-forest` | `#0C3B2E` | Headings, the sidebar, dark sections |
| `--color-forest-deep` | `#072A20` | The dark end of forest gradients |
| `--color-sage` | `#9DBBA9` | Decoration and hover borders |
| `--color-sage-soft` | `#EDF3EE` | Table headers, disabled inputs |
| `--color-lime` | `#D8F58B` | The one bright accent: highlighted keywords, the active sidebar link, the demo banner. Text on it is forest. |
| `--color-success` / `-strong` / `-soft` | `#34A777` / `#14664B` / `#E3F5EC` | Correct results and Ready |
| `--color-background` | `#F8FAF5` | Off-white page background |
| `--color-card` | `#FFFFFF` | Cards and panels |
| `--color-text` / `--color-muted` | `#12241D` / `#4B5F56` | Body text / secondary text |
| `--color-border` | `#DCE8E0` | Borders and table lines |
| `--color-info` / `-soft` | `#1D5F8A` / `#E8F2FA` | Waiting on Specialist, so it never looks like Ready |
| `--color-warning` / `-soft` | `#B45309` / `#FFFBEB` | Needs Fix and flagged fields |
| `--color-destructive` / `-soft` | `#DC2626` / `#FEF2F2` | Denied and errors |

### Category pastels

Each skill category has its own pastel so cards are easy to tell apart. Text on a
pastel is always forest or body text.

| Category | Token | Value |
|----------|-------|-------|
| Eligibility | `--color-pastel-sky` | `#E4F0FB` |
| Prior authorization | `--color-pastel-lavender` | `#EEEAFB` |
| Code matching | `--color-pastel-mint` | `#DFF4E8` |
| Modifiers | `--color-pastel-peach` | `#FDEADB` |
| Documentation | `--color-pastel-butter` | `#FBF2CC` |
| Filing rules | `--color-pastel-rose` | `#FBE5EA` |

### Status colors

Every status badge shows a word and an icon, never color alone.

| Status | Text | Background | Icon |
|--------|------|------------|------|
| New | `#4B5F56` | white with border | circle-dot |
| Denied | `#DC2626` | white with red border | circle-x |
| Needs Fix | `#B45309` | `#FFFBEB` | triangle-alert |
| Ready | `#14664B` | `#E3F5EC` | circle-check |
| Waiting on Specialist | `#1D5F8A` | `#E8F2FA` | clock |
| Submitted, Closed | `#4B5F56` | white with border | send, archive |

Red text on the red tint is only 4.4:1, so text on `--color-destructive-soft` stays in
`--color-text` with a red icon and border.

## Typography

- **UI and headings:** Plus Jakarta Sans (400 to 800). Headings are bold or extra bold
  with tight tracking. Page titles are oversized.
- **Codes, IDs, and amounts:** Fira Code, so they are easy to compare character by character.
- **Highlighted keywords** in headings use the `.marker` lime underline.
- **Eyebrows** above headings: small, bold, wide tracking, uppercase.

## Shape and depth

- Cards: 16 px radius. Page banners and dialogs: 24 px radius.
- Buttons and inputs: 12 px radius, at least 44 px tall.
- Shadows are soft and green tinted (`--shadow-sm`, `--shadow-md`, `--shadow-lg`).
- Glass (`.glass`): translucent white with a blur, for stat tiles and floating cards
  on top of gradients. Use it sparingly.

## Layout

- **Public home page** at `/`: sticky glass navigation, a bold hero with an
  illustration, alternating light and deep green sections, wavy dividers, large
  background type, a mission statement, and placeholder contact details.
- **App pages:** a deep green sidebar (it collapses to a top menu under 1024 px), a
  sticky glass top bar, and a mint gradient banner (`.page-hero`) at the top of each
  page with the title, a short line of help, and stat tiles.
- The demo banner is on every page: "Demo data only. Do not enter real patient information."
- One primary action per screen.

## Components

- **Buttons:** primary is green with white text. Secondary is white with a border.
  `.btn-lime` is for the main call to action on dark sections. Buttons lift on hover
  and arrows inside them slide forward.
- **Cards:** white, rounded, soft shadow. Cards that are links lift on hover.
- **Icon tiles:** every card heading has an icon in a rounded, tinted tile.
- **Flagged fields** get an amber left border, an icon, and the issue text directly under the field.
- **Form errors** appear below the input, linked with `aria-describedby`, and are announced with `role="alert"`.
- **Tables:** sticky header, a green bar and tint on row hover, codes in Fira Code.
- **Dialogs:** centered, blurred dark green backdrop. Escape closes, Enter confirms, focus stays inside.
- **Toasts:** bottom right, auto dismiss after 4 seconds, `aria-live`.
- **Progress:** rings for accuracy, three step meters for help level, counting numbers for stats.
- **Expandable cards:** plus and minus icons with a smooth collapse.
- **Icons:** Lucide SVG icons from `static/icons/`. No emoji as icons.
- **Illustrations:** inline SVG drawn for RUNG (capsules, crosses, molecules, shields,
  claim cards). No stock images.

## Interaction and Motion

- Hover: cards and buttons lift, arrows slide, table rows tint, the logo tilts.
- Scroll: sections fade and slide in once (`.reveal`).
- Decoration: floating shapes and slow drifting color blobs on the home page, the
  sidebar, and page banners.
- Feedback: skeleton shimmer and "Checking claim..." during AI calls, toasts for every
  save, submit, close, request, and upload.
- All of it turns off under `prefers-reduced-motion`. Content never depends on motion.

## Accessibility checklist

- [ ] Text contrast at least 4.5:1
- [ ] Visible focus rings
- [ ] Every control reachable with the keyboard
- [ ] A label on every input
- [ ] No emoji as icons
- [ ] `prefers-reduced-motion` respected
- [ ] Responsive at 375, 768, 1024, and 1440 px, with no horizontal scroll
- [ ] Decorative shapes are hidden from screen readers
