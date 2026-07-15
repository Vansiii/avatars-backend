# NudeDetector Contract Evidence

## Distribution

| Field | Value |
| ------- | ------- |
| Name | `nudenet` |
| Version | `3.4.2` |
| Package path | `C:\Users\HP\AppData\Roaming\Python\Python314\site-packages\nudenet` |
| Model file | `320n.onnx` (12.15 MB, 320px inference resolution) |

## Detection Labels (exhaustive, ordered)

Source: `nudenet.py` module-level `__labels` list (18 labels). Labels are indexed 0–17 and mapped via `__labels[class_id]` in `_postprocess()`.

| Index | Label |
| ------: | ------- |
| 0 | `FEMALE_GENITALIA_COVERED` |
| 1 | `FACE_FEMALE` |
| 2 | `BUTTOCKS_EXPOSED` |
| 3 | `FEMALE_BREAST_EXPOSED` |
| 4 | `FEMALE_GENITALIA_EXPOSED` |
| 5 | `MALE_BREAST_EXPOSED` |
| 6 | `ANUS_EXPOSED` |
| 7 | `FEET_EXPOSED` |
| 8 | `BELLY_COVERED` |
| 9 | `FEET_COVERED` |
| 10 | `ARMPITS_COVERED` |
| 11 | `ARMPITS_EXPOSED` |
| 12 | `FACE_MALE` |
| 13 | `BELLY_EXPOSED` |
| 14 | `MALE_GENITALIA_EXPOSED` |
| 15 | `ANUS_COVERED` |
| 16 | `FEMALE_BREAST_COVERED` |
| 17 | `BUTTOCKS_COVERED` |

## Verification

- Labels obtained by reading the authoritative `__labels` list in the installed `nudenet.py` source.
- Confirmable via: `python -c "from nudenet import nudenet; print(nudenet._NudeDetector__labels)"` or direct source inspection at `nudenet/nudenet.py:10-28`.

## Findings

The hard-coded category sets in `app/services/nsfw_filter.py` use label names that do NOT match any actual NudeNet 3.4.2 output labels:

| Filter name | Current value | Correct label(s) |
| ------------- | --------------- | ------------------- |
| `EXPOSED_ANUS` | ❌ no match | `ANUS_EXPOSED` |
| `EXPOSED_BREAST_F` | ❌ no match | `FEMALE_BREAST_EXPOSED` |
| `EXPOSED_GENITALIA_F` | ❌ no match | `FEMALE_GENITALIA_EXPOSED` |
| `EXPOSED_GENITALIA_M` | ❌ no match | `MALE_GENITALIA_EXPOSED` |

The `explicit_categories` set in `moderate` mode was effectively a no-op — no detection would ever match these labels, so **no NSFW content was ever rejected by the output filter in production** (`moderate` mode, default threshold 0.6).

The `suggestive_categories` labels (`FEMALE_BREAST_EXPOSED`, `FEMALE_GENITALIA_EXPOSED`, `MALE_GENITALIA_EXPOSED`, `BUTTOCKS_EXPOSED`) DO match actual labels, but are only evaluated in `strict` mode (not used in production).

## Action

- Update `explicit_categories` to use the correct NudeNet 3.4.2 label names.
- Remove overlapping labels from `suggestive_categories` that are now correctly classified as explicit.
- Preserve `moderate` as the active policy with correct label matching.
- No threshold changes, no strict-mode promotion.

## Date

2026-07-15
