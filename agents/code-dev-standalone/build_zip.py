"""Build a reproducible, plugin-free ZIP using only the declared bundle files."""
import argparse
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

ROOT = Path(__file__).resolve().parent
FILES = ("README.md", "LICENSE", "NOTICE.md", "install.py", "build_zip.py",
         ".claude/agents/ax-code-dev.md", ".claude/agents/ax-wiki-explorer.md",
         ".claude/agents/ax-code-explorer.md", ".claude/agents/ax-code-architect.md",
         ".claude/agents/ax-code-reviewer.md")


def build(output):
    output = Path(output).absolute()
    if output.is_symlink():
        raise ValueError("Output cannot be a symlink")
    output = output.resolve()
    contents = []
    for relative in sorted(FILES):
        source = ROOT / relative
        if source.is_symlink() or not source.is_file():
            raise ValueError(f"Missing or nonregular source: {source}")
        if output == source.resolve():
            raise ValueError("Output cannot overwrite a bundle source")
        contents.append((relative, source.read_bytes()))
    output.parent.mkdir(parents=True, exist_ok=True)
    with ZipFile(output, "w", compression=ZIP_DEFLATED, compresslevel=9) as archive:
        for relative, data in contents:
            entry = ZipInfo("code-dev-standalone/" + relative, (2026, 11, 6, 0, 0, 0))
            entry.create_system = 3
            entry.external_attr = 0o100644 << 16
            entry.compress_type = ZIP_DEFLATED
            archive.writestr(entry, data, compresslevel=9)
    return output


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", help="Destination ZIP path")
    args = parser.parse_args()
    print(build(args.output))
