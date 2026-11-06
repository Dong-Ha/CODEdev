"""Install only this bundle's agents and notices; never overwrite local changes."""
import argparse
from pathlib import Path

ROOT = Path(__file__).resolve().parent
NAMES = ("ax-code-dev", "ax-wiki-explorer", "ax-code-explorer",
         "ax-code-architect", "ax-code-reviewer")


def install(project, *, check=False):
    project = Path(project).expanduser().resolve(strict=True)
    if not project.is_dir():
        raise ValueError("Project must be an existing directory")
    target = project / ".claude" / "agents"
    for directory in (target.parent, target):
        if directory.is_symlink() or (directory.exists() and not directory.is_dir()):
            raise ValueError(f"Not a regular configuration directory: {directory}")
    sources = [(ROOT / ".claude" / "agents" / f"{name}.md", f"{name}.md")
               for name in NAMES]
    sources += [(ROOT / "LICENSE", "ax-code-dev-LICENSE.txt"),
                (ROOT / "NOTICE.md", "ax-code-dev-NOTICE.md")]
    pending = []
    # Validate the complete source/destination set before writing any file.
    for source, name in sources:
        if source.is_symlink() or not source.is_file():
            raise ValueError(f"Missing or nonregular bundle file: {source}")
        data = source.read_bytes()
        dest = target / name
        if dest.is_symlink() or (dest.exists() and not dest.is_file()):
            raise ValueError(f"Not a regular target file: {dest}")
        if dest.exists():
            if dest.read_bytes() != data:
                raise ValueError(f"Existing file differs; back it up and remove it before retrying: {dest}")
        else:
            pending.append((dest, data))
    if check:
        return [str(dest) for dest, _ in pending]
    created = []
    try:
        if pending:
            target.mkdir(parents=True, exist_ok=True)
        for dest, data in pending:
            # Exclusive creation also protects against a new conflicting file.
            with dest.open("xb") as stream:
                created.append(dest)
                stream.write(data)
    except OSError:
        for dest in reversed(created):
            dest.unlink(missing_ok=True)
        raise
    return [str(dest) for dest in created]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", required=True, help="Existing target project root")
    parser.add_argument("--check", action="store_true", help="Check without writing")
    args = parser.parse_args()
    try:
        paths = install(args.project, check=args.check)
    except (OSError, ValueError) as exc:
        parser.exit(1, f"{exc}\n")
    print(("Would install" if args.check else "Installed") + f" {len(paths)} file(s).")
    for path in paths:
        print(path)
    print("From the project root, start: claude --agent ax-code-dev")


if __name__ == "__main__":
    main()
