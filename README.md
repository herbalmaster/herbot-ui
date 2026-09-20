# Herbot UI

The typography stylesheet for TMH's internal tools: font, type scale, line heights and a font-size
control. Published here so the apps can load it over a CDN; **the source of truth is the private
repo `herbalmaster/tmh-design-system` (`app-kit/`), and this repo is a copy at the same tag.**

Nothing brand-related is here: no logos, no brand colours, no product information.

## Use it

```html
<link rel="stylesheet" href="https://cdn.jsdelivr.net/gh/herbalmaster/herbot-ui@v0.9.4/app-kit/herbot-ui.css">
```

Pin a tag, never a branch. For a self-contained page that must work offline, inline the file's
contents at a tag instead, with `/* herbot-ui.css @ vX.Y.Z */` as the first line.

Then paste `app-kit/font-size-control.html` just inside `<body>`, unchanged.

`app-kit/example.html` shows the kit in use.

## Installable apps

`app-kit/icons/<app>/` holds each internal app's icon set and manifest, with `app-kit/sw.js` and
`app-kit/head-snippet.html`. **Serve those from your own origin, not from this CDN**: a manifest,
its icons and a service worker must be same-origin.

## Notes

- The control only scales **rem-based** sizes. Any `px` font-size in your app will not move.
- The chosen size is stored per origin, so each app remembers its own.
- Poppins loads from the stylesheet itself (Fontsource, OFL); no Google Fonts link is needed.

## Versions

Tags here match `tmh-design-system`. A change is made and released there, then copied here at the
same tag. Files are MIT-licensed; Poppins is OFL.
