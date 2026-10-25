"""Validate canonical v2 files, hashes and optionally frozen PDF evidence."""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from validate_qa_eval import main

if __name__ == '__main__':
    sys.argv[1:1] = ['--pack', str(Path(__file__).resolve().parent)]
    main()
