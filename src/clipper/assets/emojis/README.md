# Bundled emoji PNGs

These six 72×72 PNGs are sourced from [Twemoji](https://github.com/twitter/twemoji)
(licensed CC-BY 4.0) and bundled with `clipper` for the `emoji_burst` effect.

| File          | Glyph | Codepoint |
|---------------|-------|-----------|
| `1f602.png`   | 😂    | U+1F602   |
| `1f480.png`   | 💀    | U+1F480   |
| `1f525.png`   | 🔥    | U+1F525   |
| `1f631.png`   | 😱    | U+1F631   |
| `2728.png`    | ✨    | U+2728    |
| `1f44f.png`   | 👏    | U+1F44F   |

These are intentionally a small "general reaction" set, not a literal mapping of
Twitch emote names (KEKW, LULW, ...) to glyphs — `emoji_burst` picks one
deterministically per chat peak based on a hash of the peak's top emote.

Replace these files (keeping the same names) to use a different emoji art style.
