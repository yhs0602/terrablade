import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


@dataclass(frozen=True)
class VersionSpec:
    name: str
    base_dir: Path
    decomp_dir: Path
    version_string: str
    tile_frame_important: set[int]
    message_formats: dict


def _read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _infer_version_string(decomp_dir: Path) -> Optional[str]:
    netmessage = decomp_dir / "Terraria" / "NetMessage.cs"
    if not netmessage.exists():
        return None
    text = netmessage.read_text(encoding="utf-8", errors="ignore")
    m = re.search(r"writer\\.Write\\(\"Terraria\" \\+ (\\d+)\\)", text)
    if not m:
        return None
    return f"Terraria{m.group(1)}"


def _load_tile_frame_important(
    profile_name: str, decomp_dir: Path, data_dir: Path
) -> set[int]:
    cache_path = data_dir / f"tile_frame_important_{profile_name}.txt"
    if cache_path.exists():
        text = cache_path.read_text(encoding="utf-8", errors="ignore")
        ids = {
            int(line.strip()) for line in text.splitlines() if line.strip().isdigit()
        }
        if ids:
            return ids

    main_cs = decomp_dir / "Terraria" / "Main.cs"
    if main_cs.exists():
        text = main_cs.read_text(encoding="utf-8", errors="ignore")
        ids = {
            int(m.group(1))
            for m in re.finditer(r"tileFrameImportant\\[(\\d+)\\] = true;", text)
        }
        if ids:
            data_dir.mkdir(exist_ok=True)
            cache_path.write_text(
                "\n".join(map(str, sorted(ids))) + "\n", encoding="utf-8"
            )
            return ids

    return set()


def resolve_spec(
    profile_name: str,
    repo_root: Path,
    decomp_dir_override: Optional[str] = None,
    version_string_override: Optional[str] = None,
) -> VersionSpec:
    specs_dir = repo_root / "protocol" / "specs"
    spec_path = specs_dir / f"{profile_name}.json"
    if not spec_path.exists():
        raise RuntimeError(f"Spec not found: {spec_path}")

    spec = _read_json(spec_path)
    base_dir = repo_root / spec["base_dir"]

    decomp_dir = None
    if decomp_dir_override:
        decomp_dir = Path(decomp_dir_override)
    else:
        # use decomp_dir from spec if present
        decomp_hint = spec.get("decomp_dir")
        if decomp_hint:
            decomp_dir = base_dir / decomp_hint
        else:
            # try to find a decompiled dir within base_dir
            for p in base_dir.glob("*"):
                if (p / "Terraria" / "NetMessage.cs").exists():
                    decomp_dir = p
                    break

    if decomp_dir is None or not (decomp_dir / "Terraria" / "NetMessage.cs").exists():
        raise RuntimeError(
            f"Decompiled source not found for profile '{profile_name}'. "
            f"Pass --decomp-dir or update protocol/specs/{profile_name}.json"
        )

    version_string = version_string_override or spec.get("version_string")
    if not version_string:
        version_string = _infer_version_string(decomp_dir)
    if not version_string:
        raise RuntimeError(
            "Failed to infer version string. Provide --version-string like 'Terraria279'."
        )

    tile_frame_important = _load_tile_frame_important(
        profile_name, decomp_dir, repo_root / "data"
    )

    return VersionSpec(
        name=spec["profile"],
        base_dir=base_dir,
        decomp_dir=decomp_dir,
        version_string=version_string,
        tile_frame_important=tile_frame_important,
        message_formats=spec.get("message_formats", {}),
    )


__all__ = ["VersionSpec", "resolve_spec"]
