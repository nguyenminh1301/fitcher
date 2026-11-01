# Fitcher logo guidelines

## Idea

Six table cells form an **F**. Its rows step 3-2-1 like a ranked "top N" result, and the
round dot is the answer. Data in, answer out, in one small grid.

## Files

| Use | File |
|---|---|
| Symbol (icon logo) | `svg/fitcher-symbol.svg`, `svg/fitcher-symbol-white.svg` |
| Symbol, small-size cut (≤ 32 px) | `svg/fitcher-symbol-small.svg` |
| Wordmark (text logo) | `svg/fitcher-wordmark.svg`, `svg/fitcher-wordmark-white.svg` |
| Horizontal lockup | `svg/fitcher-horizontal.svg`, `svg/fitcher-horizontal-white.svg` |
| Stacked lockup | `svg/fitcher-stacked.svg`, `svg/fitcher-stacked-white.svg` |
| GitHub README banner (1280×320, PNG at 2×) | `banner/fitcher-banner-light.png`, `banner/fitcher-banner-dark.png` |
| Favicon, app and PWA icons | `web/` (with `head-snippet.html` and `site.webmanifest`) |
| Raster masters | `png/` |

All logo SVGs are pure filled shapes: no live text, strokes, filters or raster images.
The banner SVGs use live text for the tagline (system sans-serif). Use the PNG banners so the type renders the same everywhere.

## Colour

| Name | HEX | RGB | Use |
|---|---|---|---|
| Ink | `#111111` | 17, 17, 17 | Logo, primary text, dark backgrounds |
| Paper | `#FFFFFF` | 255, 255, 255 | Light backgrounds, reversed logo |
| Mist | `#E8E8EA` | 232, 232, 234 | Ghost cells, surfaces, dividers |
| Graphite | `#6B6B70` | 107, 107, 112 | Secondary text (5.3:1 on white) |

The logo is always one colour: Ink on light, Paper on dark. Mist is never used for the logo itself.

## Construction and clear space

- Symbol grid: 56-unit cells, 16-unit gaps, 14-unit corner radius, dot radius 24 (on a 256 canvas).
- Wordmark: custom geometric monoline, 22-unit stroke with round terminals, cap height 140.
- Horizontal lockup: the gap between symbol and wordmark is one cell width.
- **Clear space:** keep at least one cell width (the size of one square) free on every side.

## Minimum size

- Symbol: 16 px. Below 32 px, use `fitcher-symbol-small.svg`, whose wider gaps keep the cells apart.
- Horizontal lockup: 96 px wide on screen, 25 mm in print.

## Do not

- Recolour cells individually, add gradients, shadows or outlines.
- Move, add or remove cells, or swap the dot for a square.
- Retype the wordmark in a font. Always use the supplied outlines.
- Stretch, rotate or place the logo on busy photos without a solid panel.

## README usage

```html
<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/brand/banner/fitcher-banner-dark.png">
  <img alt="Fitcher" src="docs/brand/banner/fitcher-banner-light.png" width="100%">
</picture>
```

## Notes

- Trademark clearance has not been checked. Run a trademark and reverse-image search before public launch.
- The wordmark is drawn from geometric primitives, so no font licence applies to it.
