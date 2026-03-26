# seiyomi/__main__.py — delegates to seiyomi.cli which owns the entry point
import sys
from seiyomi.cli import main

sys.exit(main())
