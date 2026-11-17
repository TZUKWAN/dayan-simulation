# Bundled Chinese report font

Unmodified **Noto Sans CJK SC Regular** from the official `notofonts/noto-cjk`
repository, licensed under **SIL Open Font License 1.1** in [OFL.txt](OFL.txt).
Copyright attribution is also retained in the original font's name table.

Source: https://raw.githubusercontent.com/notofonts/noto-cjk/main/Sans/OTF/SimplifiedChinese/NotoSansCJKsc-Regular.otf

SHA256: `2c76254f6fc379fddfce0a7e84fb5385bb135d3e399294f6eeb6680d0365b74b`

The application registers this font for Matplotlib in its own process. It does
not change the user's system fonts. DOCX retains Unicode Chinese text and names
this font; install this OFL font on a document viewing machine if it has no
Chinese fallback font. On Linux: copy the OTF to `~/.local/share/fonts/` and run
`fc-cache -f`. A DOCX viewer handles final font substitution; plot PNGs are already
rendered with the bundled font and need no client font installation.
