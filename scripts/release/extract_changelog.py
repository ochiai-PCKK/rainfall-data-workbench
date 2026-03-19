from __future__ import annotations

import argparse
from pathlib import Path


def extract_release_notes(changelog_text: str, version: str) -> str:
    lines = changelog_text.splitlines()
    target_header = f"## [{version}]"
    start_idx = -1

    for i, line in enumerate(lines):
        if line.startswith(target_header):
            start_idx = i
            break

    if start_idx == -1:
        raise ValueError(f"Version section not found in changelog: {version}")

    body_lines: list[str] = []
    for line in lines[start_idx + 1 :]:
        if line.startswith("## ["):
            break
        body_lines.append(line)

    body = "\n".join(body_lines).strip()
    if not body:
        raise ValueError(f"Version section is empty in changelog: {version}")

    return body


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Extract release notes for a specific version from CHANGELOG.md."
    )
    parser.add_argument("--version", required=True, help="Version without 'v' prefix (e.g. 0.2.0)")
    parser.add_argument("--changelog", default="CHANGELOG.md", help="Path to changelog file")
    parser.add_argument("--output", default="release_notes.md", help="Path to output markdown file")
    args = parser.parse_args()

    changelog_path = Path(args.changelog)
    if not changelog_path.exists():
        raise FileNotFoundError(f"Changelog file not found: {changelog_path}")

    text = changelog_path.read_text(encoding="utf-8")
    notes = extract_release_notes(text, args.version)

    output_path = Path(args.output)
    output_path.write_text(notes + "\n", encoding="utf-8")
    print(f"Extracted release notes for {args.version} -> {output_path}")


if __name__ == "__main__":
    main()
