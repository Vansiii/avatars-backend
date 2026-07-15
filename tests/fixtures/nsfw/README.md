# NSFW Test Fixtures

## Purpose

Real-image regression fixtures for the NSFW output filter (`app/services/nsfw_filter.py`).

## Fixtures

| File | Type | Expected | Status |
|------|------|----------|--------|
| `safe-landscape.jpg` | Benign landscape | No detections, passes | ✅ Works |
| `explicit-minimal.jpg` | Explicit content trigger | ContentRejected | ❌ Blocked |

## Blocked fixture: explicit-minimal.jpg

The current synthetic fixture does not trigger NudeDetector 3.4.2 detections above the 0.6 threshold. A real, licensed image is required for a complete integration test.

**Requirements:**

- License: CC0, CC-BY, or other permissive license allowing repository distribution
- Content: Contains anatomy that NudeDetector 3.4.2 classifies as `FEMALE_BREAST_EXPOSED`, `FEMALE_GENITALIA_EXPOSED`, `MALE_GENITALIA_EXPOSED`, or `ANUS_EXPOSED` with confidence ≥ 0.6
- Size: Under 100KB, metadata stripped
- No PII, no identifiable individuals, no gratuitous material

**Suggested sources:**

- Classical art (public domain) from museum APIs (Rijksmuseum, MET, etc.)
- CC0 medical/anatomical reference images
- Cropped detail from a public domain source that triggers the relevant category

Until a suitable fixture is provided, the real-image explicit rejection test will skip with a clear message.

## Metadata stripping

All fixtures have EXIF/metadata stripped via Pillow save with `exif=b""`.

## License

Synthetic fixtures: CC0 (public domain). No copyright claimed.
Real-image replacements: Per-fixture license as documented in `manifest.json`.
