"""Allow launching with ``python -m rc_app``."""

from .bootstrap import main


if __name__ == "__main__":
    raise SystemExit(main())
