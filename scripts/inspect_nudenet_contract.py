#!/usr/bin/env python3
"""
Inspect the installed NudeDetector distribution and its model label contract.

Records:
- Distribution name, version, location
- Model metadata file (labels) path and SHA-256
- Complete ordered list of detection labels
- Python / platform info

Must be run in the exact Python environment that runs the NSFW filter.
"""

import hashlib
import importlib.metadata
import json
import platform
import sys
from pathlib import Path


def sha256_of(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def get_dist_path(dist):
    """Safely get the distribution path."""
    if hasattr(dist, "_path"):
        return Path(dist._path)
    record_paths = []
    if hasattr(dist, "files"):
        record_paths = dist.files or []
    if record_paths:
        parent = Path(record_paths[0]).parent
        while parent.name != "site-packages" and parent.parent != parent:
            parent = parent.parent
        return parent / dist.metadata["Name"]
    return None


def try_get_labels(detector):
    """Try various attribute names for labels/categories."""
    for attr in ("labels", "categories", "classes", "categories_list"):
        if hasattr(detector, attr):
            return attr, getattr(detector, attr)
    return None, None


def main():
    report = {
        "distribution": {},
        "python": {},
        "model_labels": {},
        "warnings": [],
    }

    # --- Distribution info ---
    try:
        dist = importlib.metadata.distribution("nudenet")
        report["distribution"]["name"] = dist.metadata["Name"]
        report["distribution"]["version"] = dist.metadata["Version"]
    except importlib.metadata.PackageNotFoundError:
        report["warnings"].append("nudenet distribution not found")
        print(json.dumps(report, indent=2))
        sys.exit(1)

    # Locate installed package files
    dist_path = get_dist_path(dist)
    if dist_path and dist_path.exists():
        report["distribution"]["path"] = str(dist_path.resolve())

    # --- Python / platform ---
    report["python"]["version"] = sys.version
    report["python"]["executable"] = sys.executable
    report["python"]["platform"] = platform.platform()

    # --- Model labels via direct import ---
    found_labels = None
    label_source = None

    try:
        import nudenet

        print(f"[INFO] nudenet module location: {nudenet.__file__}", file=sys.stderr)

        detector = nudenet.NudeDetector()
        attr_name, found_labels = try_get_labels(detector)
        if attr_name:
            label_source = f"NudeDetector.{attr_name}"
    except Exception as exc:
        report["warnings"].append(f"NudeDetector() instantiation failed: {exc}")
        print(f"[WARN] Detector init failed: {exc}", file=sys.stderr)

    # Scan distribution for model metadata files
    model_files = []
    if dist_path and dist_path.exists():
        for p in sorted(dist_path.rglob("*")):
            if p.suffix in (".onnx", ".json", ".txt") and ".dist-info" not in str(p):
                try:
                    model_files.append(
                        {
                            "path": str(p.relative_to(dist_path)),
                            "size": p.stat().st_size,
                            "sha256": sha256_of(p),
                        }
                    )
                except (OSError, ValueError):
                    pass

    report["model_files"] = model_files

    if found_labels is not None:
        if isinstance(found_labels, dict):
            report["model_labels"]["source"] = label_source
            ordered = {}
            for k, v in found_labels.items():
                ordered[str(k)] = str(v) if not isinstance(v, (int, float)) else v
            report["model_labels"]["labels"] = ordered
            report["model_labels"]["count"] = len(ordered)
        elif isinstance(found_labels, (list, tuple)):
            report["model_labels"]["source"] = label_source
            report["model_labels"]["labels"] = [str(x) for x in found_labels]
            report["model_labels"]["count"] = len(found_labels)
    else:
        report["model_labels"]["source"] = "not found via API"
        report["model_labels"]["labels"] = None
        report["model_labels"]["count"] = 0

    # --- Try a detect() call on a known benign file ---
    fixture = (
        Path(__file__).parent.parent
        / "tests"
        / "fixtures"
        / "nsfw"
        / "safe-landscape.jpg"
    )
    if fixture.exists():
        try:
            from nudenet import NudeDetector

            detector = NudeDetector()
            result = detector.detect(str(fixture))
            report["detect_test"] = {
                "fixture": str(fixture),
                "result_count": len(result),
                "result": result,
            }
        except Exception as exc:
            report["detect_test"] = {"error": str(exc)}
            print(f"[WARN] Detect test failed: {exc}", file=sys.stderr)

    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
