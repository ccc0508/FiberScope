"""Checks for scientific table comparison and untrusted parser output handling."""
from pathlib import Path
import sys
import zipfile

import pytest

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'scripts'))
import report_mineru_comparison_20261029 as reporting
import parse_mineru_pfi_20261029 as client


def test_numeric_check_handles_thousands_and_decimal_format_without_scoring_headers():
    table='<table><tr><th>Condition</th><th>Value</th></tr><tr><td>4000</td><td>1.50</td></tr><tr><td>12,000</td><td>2.0</td></tr></table>'
    result=reporting.compare_table(table,'4000 1.5\n12000 2.00')
    assert result['data_rows']==2 and result['numeric_cells']==result['matching_cells']==4


def test_missing_table_cell_is_not_silently_counted_as_a_match():
    table='<table><tr><td>4000</td><td>1.50</td></tr></table>'
    with pytest.raises(ValueError,match='shape'):
        reporting.compare_table(table,'4000 1.5 2.0')


def test_changed_number_is_recorded_as_a_mismatch():
    table='<table><tr><td>4000</td><td>15</td></tr></table>'
    result=reporting.compare_table(table,'4000 1.5')
    assert result['numeric_cells']==2 and result['matching_cells']==1
    assert result['checks'][1]['equal'] is False


def test_model_html_cannot_execute_scripts_or_load_remote_content():
    raw='<table onclick="bad()"><tr><td colspan="2">safe<script>alert(1)</script><img src="https://example.invalid/x" onerror="bad()"></td></tr></table>'
    clean=reporting.safe_table(raw)
    assert '<script' not in clean and '<img' not in clean and 'onclick' not in clean and 'onerror' not in clean
    assert '<td colspan="2">' in clean and 'safe' in clean


@pytest.mark.parametrize('bad_name',['../outside.txt','a/../../outside.txt'])
def test_archive_traversal_is_rejected_before_any_file_is_extracted(tmp_path,bad_name):
    archive=tmp_path/'result.zip'
    with zipfile.ZipFile(archive,'w') as stream:
        stream.writestr('good.md','source')
        stream.writestr(bad_name,'outside')
    destination=tmp_path/'output'
    with pytest.raises(ValueError,match='Unsafe'):
        client.extract_archive(archive,destination)
    assert list(destination.rglob('*'))==[]
    assert not (tmp_path/'outside.txt').exists()


def test_valid_archive_preserves_exact_provider_bytes(tmp_path):
    archive=tmp_path/'result.zip';payload=b'raw provider document'
    with zipfile.ZipFile(archive,'w') as stream:stream.writestr('sub/full.md',payload)
    client.extract_archive(archive,tmp_path/'output')
    assert (tmp_path/'output/sub/full.md').read_bytes()==payload
