# Pinyin dictionary source

`basic.json` is a bounded generated projection of
[`rime-pinyin-simp`](https://github.com/rime/rime-pinyin-simp) revision
`0c6861ef7420ee780270ca6d993d18d4101049d0`, derived from Android Pinyin IME.
The dictionary data is licensed under Apache-2.0. The upstream `LICENSE` and
`AUTHORS` files are included under `files/share/licenses/rime-pinyin-simp/`.

Regenerate from an already downloaded checkout without network access:

```sh
python3 scripts/generate_pinyin_dictionary.py \
  --source ../artifacts/external/rime-pinyin-simp/pinyin_simp.dict.yaml
```

The generator keeps the package's small system vocabulary, includes every
legal single-syllable upstream Pinyin key for broad base-character coverage,
then fills the remaining slots by each key's highest upstream weight. The
result is capped at 4,096 keys and 48 candidates per key; the UI exposes at
most 32 candidates through its horizontally scrollable strip. Runtime loading
remains a single bounded JSON read.
