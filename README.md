# Zen Kaku Stencil

漢字を含む 7,792 字を、CAD でそのまま切り抜ける日本語ステンシルフォント。
A Japanese stencil typeface, kanji included, that cuts cleanly in CAD.

**ダウンロード / Download:**
[ZenKakuStencil-Regular.ttf](https://github.com/klxuyfk/zen-kaku-stencil/raw/main/fonts/ttf/ZenKakuStencil-Regular.ttf) ・
[zip（フォント + ライセンス）](https://github.com/klxuyfk/zen-kaku-stencil/releases/latest)

Regular ・ v1.100 ・ 7,792 glyphs（漢字 6,682、かな、ラテン、記号）・ SIL Open Font License 1.1 ・ [Zen Kaku Gothic New](https://github.com/googlefonts/zen-kakugothic) の派生

![specimen](documentation/specimen.png)

[日本語](#日本語) / [English](#english)

---

## 日本語

### 1. なぜこのフォントが必要か

板から文字を切り抜くと、口・日・田・B のような閉じた形の内側は支えを失って抜け落ちる。ステンシル書体は、内側を細い橋（ブリッジ）で外側につないで切り抜けるようにした書体で、看板、刻印、治具の銘板、レーザー加工、3D プリントの文字入れなど、文字を印刷するのではなく製作する場面で使われる。

漢字を含む日本語のステンシル書体を CAD で使おうとすると、次の問題に当たる。

- 漢字が収録されていないか、収録されていても常用漢字の一部で止まっている。工業用途では部品名や注意書きに現れる任意の漢字が必要になる。
- 内側の形を幾何学的に等分してスリットを入れる方式では、同じ部首でも字ごとに切る位置が変わり、読むときに引っかかる。
- フォントとして画面に表示できることと、CAD で「閉じた有効なプロファイル」になることは別の問題である。幅ゼロに近い針状の頂点、画どうしの髪の毛のような隙間、ブリッジの脇に残る薄片や数単位の段差は、CAD のスプライン近似で自己交差や開いた輪郭になるか、加工できない微小な辺として残る。

Zen Kaku Stencil はこの 3 点を解決するために作った。Zen Kaku Gothic New（OFL）の Regular をもとに 7,792 グリフすべてにブリッジを入れ、SolidWorks で入力できる 7,734 文字を 1 字ずつ押し出して確認してある。

### 2. デザイン上の特徴

- ブリッジは書き順で決める。ある画が別の画に突き当たって終わる場所で切り、終わる側の画を接合部の手前で止める。口の右の縦画は底の横画の手前で止まり、日の中央の横画は右の縦画に届かない。楷書で筆を止める形と同じなので、ブリッジが文字の一部として読める。
- 優先順位は、終筆が通過する画に当たる場所 ＞ 終筆どうし ＞ 終筆と次の画の起筆 ＞ 起筆 ＞ 画の途中。画の途中で切るのは、他に手がない内側の部屋だけ。
- 止める画は、その画に直交する面で切る。切り口は相手の画の面からブリッジの幅だけ離し、その間のインクをすべて除く。相手の画の面は削らない。隙間は長方形に見え、どこでも同じ幅になる。
- 斜めの画（ノ・㇏）は切らない。部屋に接する横画か縦画を縮める。
- 同じ部品には同じカット。品の三つの口、門の左右は同じ位置で切れる。
- ラテン文字は縦の幹を残してボウル側を切る（B・D・P・R）。幹に滑らかに合流するボウル（a・b・d・g・p・q）と輪（O・o・0・6・8・9）は、輪の平らな部分の中央に直角の溝を 1 本入れる。かなの輪は、曲がった画を直線の画の手前で止める。
- 込み入った字では、字ごとの画の太さに合わせてブリッジを細くする（画が細く描かれた字ほど細い。下限は標準の半分）。
- 切り口以外の輪郭は Zen Kaku Gothic New のものをそのまま使う。

![カット規則の例（左: 原字、右: ステンシル版）](documentation/cut_rules.png)

### 3. 工業的な特徴

- SolidWorks で全文字を検証済み。入力できる 7,734 文字を、スケッチ文字として挿入 → 分解 → 輪郭検査 → 押し出し の手順で自動検証し、7,734 / 7,734 字が通る。
- ブリッジ幅が寸法として決まる。文字高さを決めれば線幅とブリッジ幅が決まるので（下表）、レーザー、ウォータージェット、CNC、エッチングの加工限界に合わせて高さを選べる。
- 切り込みが作る微小な辺を残さない。切り口に新しくできる辺のうち 12 ユニット（文字高さ 20 mm で 0.34 mm）未満のものを仕上げで除いてあり、全 7,792 グリフの検査で残るのは 1 か所（嗣、8 ユニットの段差）だけである。針状の頂点、輪郭の自己接触、ブリッジ脇の薄片は 0。
- 浮き島（外とつながらない内側の領域）は 0。短辺がブリッジの下限に満たない極小の部屋 23 か所（18 字）は、開けずに埋めてある。
- 押し出し（凸の銘板）でも押し出しカット（抜き板）でも同じ輪郭が使える。

| 文字高さ（キャップハイト） | 線幅 | ブリッジ幅 | 込み入った字の最小ブリッジ |
| --- | --- | --- | --- |
| 10 mm | 1.0 mm | 0.9 mm | 約 0.4 mm |
| 20 mm | 1.9 mm | 1.7 mm | 約 0.9 mm |
| 50 mm | 4.8 mm | 4.3 mm | 約 2.1 mm |

![SolidWorks での押し出し（文字高さ 20 mm、厚さ 3 mm）](documentation/solidworks_regular.png)

### 4. 技術的な特徴

- 完全に自動で再現できる。元フォントと公開されている書き順データ（KanjiVG）から、`scripts/` のパイプラインで再生成できる。手作業で直した字はない。
- 切り込みは部屋の輪郭の角から作る。輪郭の折れ（T 字の接合、画の合流）ごとに「どちらの画を止めるか」の候補を立て、相手の画の面を輪郭から直接測って切り口の位置を決める。
- 書き順データは分類に使う。KanjiVG の画をグリフの枠に合わせ、各候補が終筆・起筆・画の途中のどれに当たるかを判定して費用を付ける。切り口の形の計算には使わない。
- 無駄なカットがない。候補を書き順の費用で評価し、最小全域木で選ぶので、内側の部屋 1 つにつきブリッジ 1 本になる。
- CAD 整合の検査と整形規則を持つ。浮き島、自己交差、輪郭どうしの接触、微小セグメント、針状頂点を検査し（`scripts/lint.py`）、切り込みが作った短い辺と鋭い先端を全字で数える（`scripts/audit_font.py`）。

| 項目 | 値 |
| --- | --- |
| ブリッジのある字 / ブリッジ数 | 5,436 / 17,103 |
| 終筆で止めるもの / 起筆で止めるもの | 12,198 / 3,382（合わせて 91%） |
| 画の途中の溝 | 1,369 |
| 書き順によらず輪郭から置くもの | 154（記号、囲み数字など） |

### 5. 現状の制限

- ウェイトは Regular のみ。Bold は v1.100 に含めていない（[v1.000 からの変更](#8-v1000-からの変更)）。イタリックは元の書体に存在しない。
- 込み入った字では内側の部屋が小さく、ブリッジが細い。小さく切る場合は文字高さを大きく取る。
- 極小の部屋を埋めた 18 字（堯 愛 編 翼 艢 蝙 贄 醤 鴆 鬮 鬯 騙 驚 蘒 鼇 ☝ ☞ ☟）は、その部分が元の字形より黒い。
- 嗣 に 8 ユニットの段差が 1 か所残る。面に沿う溝の端に 40〜45° の角が 9 か所ある。
- 書き順データのない字（記号、一部の互換漢字）は、輪郭の形だけで切る位置を決めている。
- 検証は SolidWorks 2026 で行った。他の CAD での輪郭検査は行っていない。

### 6. 使い方

1. 上のリンクから TTF をインストールする。
2. CAD のスケッチ文字で「Zen Kaku Stencil」を選ぶ。SolidWorks では斜体チェックも使える。太字チェックは使わない（合成太字になり、輪郭が自己交差して押し出せない）。
3. 文字を分解して、押し出すか、押し出しカットする。

### 7. ビルドと再生成

ブリッジ幅などを変える場合は、元フォントと書き順データを取得して生成し直す。

```
pip install -r requirements.txt
python scripts/fetch_inputs.py           # Zen Kaku Gothic New と KanjiVG を取得
python scripts/batch.py out/results.pkl  # 全グリフにブリッジを配置（並列、約 25 分）
python scripts/lint.py out/results.pkl   # 輪郭の検査
python scripts/audit_font.py out/results.pkl > out/audit.log   # 切り込みが作った短い辺・鋭い先端の検査
python scripts/build_font.py base_font/ZenKakuGothicNew-Regular.ttf out/results.pkl fonts/ttf/ZenKakuStencil-Regular.ttf
python scripts/set_names.py              # name テーブル、バージョン、ベンダー ID
python scripts/gf_fixes.py               # .notdef、prep、GDEF の後処理
python scripts/export_ufo.py             # sources/*.ufo を書き出す（gftools でビルドする場合）
```

| 変数 | 既定 | 意味 |
| --- | --- | --- |
| `STENCIL_STROKE_W` | 67 | 線幅（1000 / em） |
| `STENCIL_W` | 60 | ブリッジ幅 |
| `STENCIL_ENGINE` | `corners` | `corners` = v1.100 の切り込み、`bridges` = v1.000 の切り込み |
| `STENCIL_OPTS` | `scripts/release_config.py` の値 | 切り込みの形の選択肢（`scripts/stencil/corners.py` の `OPTS`） |
| `STENCIL_NEEDLE_ARM` | 12 | 針状頂点とみなす腕の長さの上限 |
| `STENCIL_PROCS` | CPU 数 − 1 | 並列数 |

### 8. v1.000 からの変更

- 切り込みの形を改めた。v1.000 は接合部に矩形を置いて減算していたため、相手の画に 0〜30 ユニット食い込み、斜めの接合では隙間の幅が場所によって変わっていた。v1.100 は、止める画を相手の画の面からブリッジの幅だけ手前で直角に切り、相手の画は削らない。
- 込み入った字のブリッジ幅を、字ごとの画の太さに合わせるようにした。
- 斜めの画を切らず、横画・縦画を縮めるようにした。ラテン文字のボウルは輪の平らな部分で切る。
- 切り込みが作る 12 ユニット未満の辺を除く仕上げを加え、全字を検査した。
- Bold を外した。新しい規則を Bold にそのまま当てると、込み入った漢字で規則の通らない部屋と尖った角が残るため、Bold は今後の課題とした。v1.000 の Bold は [Release v1.000](https://github.com/klxuyfk/zen-kaku-stencil/releases/tag/v1.000) にあるが、切り込みの形は v1.100 の Regular と揃っていない。
- 多くの字で切る位置が v1.000 から変わっている。

### 9. ライセンス

- フォント: SIL Open Font License 1.1（`OFL.txt`）。Zen Kaku Gothic New（Copyright 2022 The Zen Project Authors、デザイン 大曲都市）の派生物で、同じライセンスで配布する。
- `scripts/` のコードも OFL の「Font Software」に含まれる。
- ブリッジの位置を決めるために読む KanjiVG（Copyright Ulrich Apel、CC BY-SA 3.0）のデータは、フォントには含まれない。

---

## English

### 1. Why this typeface exists

Cut a letter out of a sheet and the inside of any closed shape, the counters of 口, 日, 田 or B, loses its support and falls out. A stencil typeface keeps those counters attached with thin bridges so the letter can be cut. That is what signs, engraving, fixture labels, laser cutting and lettering on 3D prints need: letters that are made rather than printed.

A Japanese stencil typeface with kanji runs into three problems when it meets CAD.

- No kanji, or only part of the common set. Industrial use needs whatever kanji appear in a part name or a warning label.
- Counters slit geometrically put the cut in a different place in every character, even for the same radical, and the eye stumbles.
- Rendering on screen and dissolving into a valid closed profile in CAD are different things. Near-zero-width needles, hairline gaps between strokes, slivers and steps of a few units beside a bridge become self-intersections or open contours after the CAD spline fit, or stay behind as edges too small to machine.

Zen Kaku Stencil was built to remove all three. It is derived from the Regular of Zen Kaku Gothic New (OFL), every one of the 7,792 glyphs is bridged, and all 7,734 characters that SolidWorks can type were extruded one by one to confirm it.

### 2. Design

- Bridges follow stroke order. A bridge goes where a stroke ends against another stroke, and the ending stroke stops short of the joint: the right vertical of 口 stops above the bottom bar, the middle bar of 日 does not reach the right vertical. This is how a brush stops in kaisho writing, so the bridge reads as part of the letterform.
- Priority: stroke end against a through stroke > end against end > end against the next stroke's start > stroke start > mid-stroke. A mid-stroke cut is used only for inner counters that allow nothing else.
- The ending stroke is cut square to its own axis. The cut face sits one bridge width from the face of the stroke it meets, all ink in between is removed, and the met stroke is never carved. The gap reads as a rectangle of constant width.
- Diagonal sweeps (ノ, ㇏) are not cut; the bar or upright bordering the counter is shortened instead.
- Same component, same cut: the three 口 of 品, both halves of 門.
- Latin letters keep their stems and are cut on the bowl side (B, D, P, R). Bowls that flow smoothly into a stem (a, b, d, g, p, q) and rings (O, o, 0, 6, 8, 9) get one square slot in the middle of the plain part of the ring. Kana loops end the curved stroke short of the straight one.
- In dense characters the bridge narrows with the stroke width the glyph is actually drawn with, down to half the standard width.
- Outside the cuts the outlines are those of Zen Kaku Gothic New, untouched.

### 3. Manufacturing

- Every character verified in SolidWorks. All 7,734 typeable characters were inserted as sketch text, dissolved, profile-checked and extruded by script; 7,734 / 7,734 pass.
- Bridge width is a dimension. Choose the cap height and the stroke and bridge widths follow (table below), so the height can be matched to the limits of laser, waterjet, CNC or etching.
- No micro edges from the cuts. New edges shorter than 12 units (0.34 mm at a 20 mm cap height) beside a cut are removed in a finishing pass; an audit of all 7,792 glyphs finds one left (嗣, an 8-unit step). Needle vertices, self-touching outlines and slivers beside bridges: 0.
- Floating islands: 0. The 23 counters (in 18 characters) whose short side is below the minimum bridge are filled rather than opened.
- The same profiles work for raised lettering (extrude) and stencil plates (extruded cut).

| Cap height | Stroke | Bridge | Smallest bridge in dense kanji |
| --- | --- | --- | --- |
| 10 mm | 1.0 mm | 0.9 mm | about 0.4 mm |
| 20 mm | 1.9 mm | 1.7 mm | about 0.9 mm |
| 50 mm | 4.8 mm | 4.3 mm | about 2.1 mm |

### 4. Technical

- Fully automatic and reproducible. The font regenerates from the parent font and the public KanjiVG stroke data with the pipeline in `scripts/`. No glyph was edited by hand.
- Cuts are built from the corners of the counter outline. Every bend of the outline (a T joint, two strokes merging) yields candidates for which stroke to stop; the face of the met stroke is measured from the outline itself and fixes where the cut goes.
- Stroke data classifies, geometry decides. KanjiVG strokes are fitted to each glyph and tell whether a candidate is a stroke end, a stroke start or mid-stroke, which sets its cost. They are not used to compute the shape of the cut.
- No superfluous cuts. Candidates are scored by the stroke-order cost and selected as a minimum spanning tree: one bridge per counter.
- CAD-conformance checks and cleanup rules. Islands, self-intersections, touching contours, micro segments and needle vertices are checked (`scripts/lint.py`); short new edges and sharp tips made by the cuts are counted over the whole font (`scripts/audit_font.py`).

| Item | Value |
| --- | --- |
| Glyphs with bridges / bridges | 5,436 / 17,103 |
| Stroke-end cuts / stroke-start cuts | 12,198 / 3,382 (91% together) |
| Mid-stroke slots | 1,369 |
| Placed from the outline alone, without stroke order | 154 (symbols, enclosed numerals, …) |

### 5. Current limitations

- Regular only. Bold is not part of v1.100 (see [Changes since v1.000](#8-changes-since-v1000)). The parent typeface has no italic.
- Dense characters have small counters and therefore narrow bridges. Use a larger cap height when cutting them small.
- The 18 characters with filled counters (堯 愛 編 翼 艢 蝙 贄 醤 鴆 鬮 鬯 騙 驚 蘒 鼇 ☝ ☞ ☟) are blacker there than the parent typeface.
- One 8-unit step remains in 嗣, and nine corners of 40 to 45 degrees remain at the ends of slots that run along a face.
- Characters without stroke data (symbols, some compatibility ideographs) are cut by the shape of the outline alone.
- Verified in SolidWorks 2026; other CAD systems were not tested.

### 6. Usage

1. Install the TTF from the link at the top.
2. Choose "Zen Kaku Stencil" for sketch text in your CAD. In SolidWorks the italic checkbox works; do not use the bold checkbox (it synthesises a bold whose outlines self-intersect and cannot be extruded).
3. Dissolve the text, then extrude or extruded-cut.

### 7. Building and regenerating

To change the bridge width or anything else, fetch the parent font and the stroke data and rebuild.

```
pip install -r requirements.txt
python scripts/fetch_inputs.py           # Zen Kaku Gothic New and KanjiVG
python scripts/batch.py out/results.pkl  # place bridges on every glyph (multiprocess, about 25 min)
python scripts/lint.py out/results.pkl   # outline checks
python scripts/audit_font.py out/results.pkl > out/audit.log   # short edges and sharp tips made by the cuts
python scripts/build_font.py base_font/ZenKakuGothicNew-Regular.ttf out/results.pkl fonts/ttf/ZenKakuStencil-Regular.ttf
python scripts/set_names.py              # name table, version, vendor ID
python scripts/gf_fixes.py               # .notdef, prep and GDEF post-processing
python scripts/export_ufo.py             # write sources/*.ufo (for a gftools build)
```

| Variable | Default | Meaning |
| --- | --- | --- |
| `STENCIL_STROKE_W` | 67 | stroke width (units per 1000 em) |
| `STENCIL_W` | 60 | bridge width |
| `STENCIL_ENGINE` | `corners` | `corners` = the cuts of v1.100, `bridges` = the cuts of v1.000 |
| `STENCIL_OPTS` | the value in `scripts/release_config.py` | options for the shape of the cuts (`OPTS` in `scripts/stencil/corners.py`) |
| `STENCIL_NEEDLE_ARM` | 12 | longest arm still treated as a needle vertex |
| `STENCIL_PROCS` | CPU count − 1 | worker processes |

### 8. Changes since v1.000

- New cut geometry. v1.000 subtracted a rectangle at each joint, which bit 0 to 30 units into the met stroke and left gaps of varying width at oblique joints. v1.100 cuts the ending stroke square, one bridge width short of the met stroke's face, and leaves the met stroke whole.
- Bridge width in dense characters now follows the stroke width of the glyph.
- Diagonal sweeps are no longer cut; bars and uprights are shortened instead. Latin bowls are cut in the plain part of the ring.
- A finishing pass removes new edges shorter than 12 units, and the whole font is audited for them.
- Bold was dropped. Applied to Bold as they are, the new rules leave counters they cannot open and sharp corners in dense kanji, so Bold is future work. The Bold of v1.000 remains available in [Release v1.000](https://github.com/klxuyfk/zen-kaku-stencil/releases/tag/v1.000), with the old cut geometry.
- Many characters are cut in a different place than in v1.000.

### 9. License

- Fonts: SIL Open Font License 1.1 (`OFL.txt`). Zen Kaku Stencil is a derivative of Zen Kaku Gothic New (Copyright 2022 The Zen Project Authors, designed by Yoshimichi Ohira) and is distributed under the same license.
- The code in `scripts/` is part of the Font Software under the OFL.
- The KanjiVG data (Copyright Ulrich Apel, CC BY-SA 3.0) read to place the bridges is not embedded in the fonts.
