"""The suite must not write into the project's real log directory.

Importing src.main calls configure_logging(settings.logs_dir) at module
level, so without isolation every test run appends fixture noise --
pytest tmp paths, deliberately-broken skills, simulated hook failures --
into the same data/logs/vault-server.jsonl used to debug the live server.
That made a real incident harder to read than it needed to be.
"""

from pathlib import Path


REAL_LOGS_DIR = Path.home() / "dev" / "mazkir" / "data" / "logs"


def test_settings_logs_dir_is_not_the_real_one():
    from src.config import settings

    assert settings.logs_dir != REAL_LOGS_DIR


def test_no_log_handler_writes_into_the_real_logs_dir():
    import logging

    import src.main  # noqa: F401  — triggers configure_logging

    targets = []
    for logger in (logging.getLogger(), logging.getLogger("mazkir.audit")):
        for h in logger.handlers:
            filename = getattr(h, "baseFilename", None)
            if filename:
                targets.append(Path(filename))

    offenders = [p for p in targets if REAL_LOGS_DIR in p.parents]
    assert offenders == [], f"handlers writing into the real logs dir: {offenders}"
