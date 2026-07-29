def cleanup_temp_dir(temp_dir: str) -> None:
    """Deletes only the per-call ephemeral working directory. Deliberately never called
    with the permanent audio storage path — see the audit finding in
    docs/project/REUSE.md about main.py's original delete-on-completion behavior."""
    from src.utils.utils import Cleaner

    Cleaner.cleanup(temp_dir)
