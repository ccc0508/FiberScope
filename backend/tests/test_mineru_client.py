"""Checks for safe MinerU provider archive extraction."""
from pathlib import Path
import sys
import zipfile

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts'))
import mineru_client as client


@pytest.mark.parametrize('bad_name', ['../outside.txt', 'a/../../outside.txt'])
def test_archive_traversal_is_rejected_before_any_file_is_extracted(tmp_path, bad_name):
    archive = tmp_path / 'result.zip'
    with zipfile.ZipFile(archive, 'w') as stream:
        stream.writestr('good.md', 'source')
        stream.writestr(bad_name, 'outside')
    destination = tmp_path / 'output'
    with pytest.raises(ValueError, match='Unsafe'):
        client.extract_archive(archive, destination)
    assert list(destination.rglob('*')) == []
    assert not (tmp_path / 'outside.txt').exists()


def test_valid_archive_preserves_exact_provider_bytes(tmp_path):
    archive = tmp_path / 'result.zip'
    payload = b'raw provider document'
    with zipfile.ZipFile(archive, 'w') as stream:
        stream.writestr('sub/full.md', payload)
    client.extract_archive(archive, tmp_path / 'output')
    assert (tmp_path / 'output/sub/full.md').read_bytes() == payload
