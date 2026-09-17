# Relay Design System — Premium Operations UI

Status: design specification for Phase D. Companion to implementation-plan.md section 9. Goals: look and behave like a paid developer tool while remaining honest, accessible and calm under failure. Nothing here is implemented yet.

## 1. Design principles
1. Credibility through restraint: dense, precise, quiet. No decorative gradients, glassmorphism, confetti or fake activity metrics.
2. The attempt timeline is the hero: execution, retries, lease loss and recovery readable in one view.
3. Never lie: loading is loading, stale is labelled stale, failures are specific. A premium feel comes from truthfulness plus polish.
4. Keyboard-complete: every action reachable and visible; focus never lost.
5. Performance is aesthetics: instant-feel tables, stable layout, no animation of data under investigation.

## 2. Visual identity
- Aesthetic: industrial instrument panel. Fine 1px borders, layered neutral surfaces, one accent color, functional color only for state.
- Draft palette (must pass WCAG AA before freeze; dark-first):
  background #101416, surface #181E21, elevated #222A2E, border #344047,
  text #E7EEF0, text-muted #A6B3B9, accent #65D4C5, success #6FD59A,
  warning #EBC06A, failure #FF8E8E, running #7FB6FF.
- State always = color + icon + text label. Color alone never carries meaning.
- Light theme ships only after full contrast validation; no untested toggle at v1.
- Typography: self-hosted IBM Plex Sans (UI) + IBM Plex Mono (IDs, numbers, code). Verify license files and bundle size before adoption; provide system fallback stacks. No external font CDN calls.
- Elevation: borders and subtle shadows only; shadow values documented as tokens, never ad-hoc.

## 3. Foundations
- Spacing scale: 4/8/12/16/24/32 px. Grid: 12 columns desktop.
- Type scale: 12 (metadata), 13 (secondary), 14 (body/table), 16 (emphasized body), 20 (section), 24 (page). Line height 1.45; tabular numerals for all metrics.
- Radius: 4px controls, 6px cards. Focus ring: 2px accent, 2px offset, always visible.
- Density: jobs table row height 44px desktop; zebra optional, hover subtle, selection clear.
- Motion: 120-180ms ease-out; used for dialog entry, copy confirmation, filter application. Never reorder rows via animation. Full reduced-motion compliance.

## 4. Core components (build these; no UI kit theme purchase)
- Status badge (queued, running, retry-wait, succeeded, failed, canceled, stale-lease) with per-state icon and text.
- Jobs table: native HTML table, aria-sort headers, row link, inline row actions, empty/loading/error variants.
- Attempt timeline: vertical steps with connector; per attempt: number, worker, duration, outcome, retry delay; expandable bounded logs and input/output (preformatted JSON, size-capped, copy button).
- Job detail header: state chip, reason, handler, queue, ID with copy, submitted time, attempt budget, lease age when relevant, actions (cancel/rerun) with confirm dialogs.
- Submit form: handler picker with schema-driven fields for the built-in set; queue, priority, attempts, delay; double-submit protection; idempotency key shown as advanced detail.
- Filter bar: URL-synced state, queue/state/time selects, search by ID/handler, reset.
- Dialogs/menus/tabs via Radix primitives; everything else native elements.
- Empty, skeleton, stale-banner, 401, 409, 5xx and offline states specified per implementation-plan 9.5; every screen ships all of them.

## 5. Accessibility requirements
- Native semantics; no div tables. Keyboard paths for submit/filter/detail/confirm/cancel/rerun.
- Dialogs: focus trap, Escape, focus restore. aria-live only for mutation outcomes, never for polling refreshes.
- All interactive targets >= 40px; do not rely on hover for any essential control.
- Screen-reader smoke pass (NVDA and VoiceOver) recorded in the Phase D gate; axe automated checks plus manual verification.

## 6. Brand and product naming
- Wordmark: "Relay" lowercase-mark style in-app; LOCAL badge always visible in single-install UI.
- Iconography: lucide-react, 16px grid, functional labels.
- Screenshots for docs use seeded demo data labelled as demo; no fabricated performance numbers in any marketing or README image.

## 7. Acceptance checklist (design)
Tokens contrast-validated; both themes (if shipped) tested; all component states implemented; timeline pass with a failed-then-recovered job; 320px, 768px, 1440px reviews; reduced-motion pass; keyboard-only journey pass; screenshot set produced from demo data.
