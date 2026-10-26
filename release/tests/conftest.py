import sys
from pathlib import Path

# The release scripts are plain files in release/, not a package.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
