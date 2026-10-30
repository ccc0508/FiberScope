"""Check region targeting, immutable corrections, numeric guards and actual image requests."""
from copy import deepcopy
import json
from pathlib import Path
import sys
from types import SimpleNamespace as NS

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts'))
from index_mineru_experiment import native_units
from mineru_quality import inspect, assess, apply_reviews, validate_review, table_values
from review_mineru_quality import request_for, review_one


def unit(text='The measured value is 70.42%.', kind='paragraph'):
    return dict(source_id='mineru_block_0000', native_block_index=0, page=1, bbox=[100, 100, 900, 300],
                native_type='text', native_text_level=2 if kind == 'heading' else None, kind=kind, text=text)


def decision(text, **changes):
    return dict(decision='incorrect', confidence='high', reason='源图中的文字清晰可辨。',
        visible_text=text, corrected_text=text, heading_action='keep', heading_level=None, **changes)


def test_checks_only_flagged_units_and_ignore_empty_picture_content():
    blocks = [dict(type='text', text='1. Methods', text_level=2, page_idx=0, bbox=[100, 100, 900, 130]),
              dict(type='text', text='Ordinary scientific prose, with a value of 70.42%.', page_idx=0, bbox=[100, 140, 900, 300]),
              dict(type='text', text='4.1 nm', text_level=2, page_idx=0, bbox=[300, 400, 400, 420]),
              dict(type='chart', content='', chart_caption=[], page_idx=0, bbox=[100, 500, 500, 800])]
    units, excluded = native_units(blocks, 1)
    flags = inspect(units, blocks, 'test_document')
    assert {f['source_id'] for f in flags} == {'mineru_block_0002'}
    assert flags[0]['code'] == 'measurement_annotation'
    assert excluded[0]['reason'] == 'no_textual_content'


def test_duplicate_detection_does_not_delete_the_source():
    text = 'This experiment examines a specific sample under carefully controlled laboratory conditions today. '
    original = unit(text * 2)
    before = deepcopy(original)
    flags = inspect([original], [dict(type='text')], 'test_document')
    assert 'repeated_long_phrase' in {f['code'] for f in flags}
    assert original == before


def test_numeric_change_without_pdf_support_stays_pending():
    u = unit()
    status, reasons = assess(u, decision('The measured value is 72.54%.'), 'The measured value is 70.42%.')
    assert status == 'pending' and 'numbers_not_grounded_in_pdf_rectangle' in reasons


def test_duplicate_removal_is_reversible_with_original_offsets():
    before = 'The measured value is 70.42%. The measured value is 70.42%.'
    after = 'The measured value is 70.42%.'
    u = unit(before)
    job = dict(source_id=u['source_id'], pdf_text=after, findings=[], image_sha256='test-image')
    record = dict(status='completed', review=decision(after), request_sha256='test-request')
    corrected, ledger = apply_reviews([u], [job], {u['source_id']: record})
    assert u['text'] == before and corrected[0]['text'] == after
    assert ledger[0]['status'] == 'accepted_correction'
    reconstructed = before
    for edit in reversed(ledger[0]['edits']):
        reconstructed = reconstructed[:edit['original_start']] + edit['after'] + reconstructed[edit['original_end']:]
    assert reconstructed == after


def test_uncertain_and_unflagged_do_not_change_or_claim_verification():
    u, ordinary = unit(), dict(unit('An unflagged paragraph.'), source_id='normal')
    review = dict(decision='uncertain', confidence='low', reason='截图不足以确认。', visible_text='',
                  corrected_text=None, heading_action='keep', heading_level=None)
    job = dict(source_id=u['source_id'], pdf_text=u['text'], findings=[], image_sha256='test-image')
    corrected, ledger = apply_reviews([u, ordinary], [job], {u['source_id']: dict(status='completed', review=review)})
    assert corrected[0]['text'] == u['text'] and ledger[0]['status'] == 'pending'
    assert corrected[1]['quality_status'] == 'not_flagged_not_reviewed'


def test_table_guard_locks_numeric_rows_caption_and_footnotes():
    original = 'Table 1\n<table><tr><td>110</td><td>(110)</td></tr><tr><td>4000</td><td>70.42</td></tr></table>\nFootnote a'
    corrected = original.replace('<td>110</td>', '<td>(1\\bar{1}0)</td>')
    assert table_values(original) == [['4000', '70.42']]
    assert assess(unit(original, 'table'), decision(corrected), '')[0] == 'accepted_correction'
    assert 'table_data_rows_changed' in assess(unit(original, 'table'), decision(corrected.replace('70.42', '72.54')), '')[1]
    assert 'table_caption_or_footnotes_changed' in assess(unit(original, 'table'), decision(corrected.replace('Footnote a', '')), '')[1]


def test_correct_decision_cannot_hide_different_transcription():
    r = dict(decision='correct', confidence='high', reason='无误。', visible_text='Something unrelated.',
             corrected_text=None, heading_action='keep', heading_level=None)
    assert assess(unit(), r, '')[0] == 'pending'


def test_scientific_inequality_is_not_an_html_tag_and_ligatures_are_normalized():
    from mineru_quality import plain, normalized
    text = 'p < 0.05 and later <sup>2</sup> remain in the source.'
    assert '0.05 and later' in plain(text)
    assert normalized('ﬁbers') == normalized('fibers')


def test_false_heading_demotion_can_keep_image_only_text_without_inventing_values():
    u = unit('4.1 nm', 'heading')
    r = decision('4.1 nm')
    r['heading_action'] = 'demote'
    assert assess(u, r, '') == ('accepted_correction', [])
    r['corrected_text'] = r['visible_text'] = '4.2 nm'
    assert assess(u, r, '')[0] == 'pending'


def test_keep_heading_level_is_harmless_metadata_not_an_implicit_promotion():
    r = decision('1. Introduction')
    r['heading_level'] = 2
    validate_review(r)


def test_miller_overbar_does_not_create_fake_measured_numbers():
    from mineru_quality import numbers
    assert numbers(r'The (1\overline{1}0) plane and 70.42%.') == numbers('The (110) plane and 70.42%.')
    assert numbers('70.42%') != numbers('72.54%')


def test_scoped_header_patch_cannot_change_data_and_preserves_caption():
    from mineru_quality import header_review
    original = 'Caption<table><tr><td>110</td><td>(110)</td></tr><tr><td>4000</td><td>70.42</td></tr></table>Footnote'
    u = unit(original, 'table')
    value = dict(decision='incorrect', confidence='high', reason='图中上划线仅覆盖中间一位。',
                 patches=[dict(before='110', after=r'(1\overline{1}0)', occurrences=1)])
    r = header_review(value, u)
    assert r['corrected_text'].startswith('Caption') and r['corrected_text'].endswith('Footnote')
    assert table_values(r['corrected_text']) == table_values(original)
    value['patches'][0].update(before='70.42', after='70.42')
    with pytest.raises(ValueError, match='header cell'):
        header_review(value, u)


def test_scoped_header_patch_rejects_changed_digits_and_wrong_occurrence_count():
    from mineru_quality import header_review
    u = unit('<table><tr><td>110</td><td>(110)</td></tr></table>', 'table')
    value = dict(decision='incorrect', confidence='high', reason='有原图依据。',
                 patches=[dict(before='110', after='120', occurrences=1)])
    with pytest.raises(ValueError, match='digits'):
        header_review(value, u)
    value['patches'][0].update(after=r'(1\bar{1}0)', occurrences=2)
    with pytest.raises(ValueError, match='header cell'):
        header_review(value, u)


def test_pdf_vector_geometry_detects_the_covered_digit_and_blocks_wrong_model_scope(tmp_path):
    from pypdf import PdfWriter
    from pypdf.generic import DictionaryObject, NameObject, DecodedStreamObject
    import fitz
    from review_mineru_quality import header_targets
    from mineru_quality import header_geometry_agrees
    writer = PdfWriter()
    page = writer.add_blank_page(width=600, height=800)
    font = DictionaryObject({NameObject('/Type'):NameObject('/Font'), NameObject('/Subtype'):NameObject('/Type1'), NameObject('/BaseFont'):NameObject('/Helvetica')})
    page[NameObject('/Resources')] = DictionaryObject({NameObject('/Font'):DictionaryObject({NameObject('/F1'):writer._add_object(font)})})
    content = DecodedStreamObject()
    content.set_data(b'BT /F1 12 Tf 100 600 Td (110) Tj ET 106.672 614 m 113.344 614 l S')
    page[NameObject('/Contents')] = writer._add_object(content)
    path = tmp_path / 'bar.pdf'
    with path.open('wb') as stream: writer.write(stream)
    u = unit('<table><tr><td>110</td><td>(110)</td></tr></table>', 'table')
    u['bbox'] = [100,100,900,600]
    with fitz.open(path) as pdf:
        _, _, geometry = header_targets(u, pdf[0])
    assert geometry[0]['bar_digit_indices'] == [1]
    wrong = dict(patches=[dict(before='110',after=r'\bar{1}10')])
    right = dict(patches=[dict(before='110',after=r'1\bar{1}0')])
    assert header_geometry_agrees(wrong, geometry) is False
    assert header_geometry_agrees(right, geometry) is True


@pytest.mark.parametrize('changes', [dict(corrected_text=''), dict(heading_action='promote'), dict(extra='invented')])
def test_malformed_edits_rejected(changes):
    r = decision('Original scientific text.')
    r.update(changes)
    with pytest.raises(ValueError):
        validate_review(r)


def test_image_on_wire_same_model_independent_context_and_no_secret_or_reasoning_persisted(tmp_path, monkeypatch):
    import openai
    (tmp_path / 'crop.png').write_bytes(b'fixture-image-only')
    job = dict(source_id='test-region', image_path='crop.png', image_sha256='image',
               prompt='flagged extraction and local text only', prompt_sha256='prompt')
    response_value = dict(decision='correct', confidence='high', reason='与原图一致。', visible_text='Original',
                          corrected_text=None, heading_action='keep', heading_level=None)
    calls = []
    class Client:
        def __init__(self, **kwargs):
            assert kwargs['api_key'] == 'TEST_PRIVATE_KEY' and kwargs['max_retries'] == 0
            self.chat = NS(completions=NS(create=self.create))
        def create(self, **kwargs):
            calls.append(kwargs)
            return NS(model='DeepSeek-V4.1-Flash-1017', system_fingerprint='fixture',
                      usage=NS(prompt_tokens=50, completion_tokens=25, total_tokens=75),
                      choices=[NS(message=NS(content=json.dumps(response_value), reasoning_content='PRIVATE_REASONING'))])
        def close(self): pass
    monkeypatch.setattr(openai, 'OpenAI', Client)
    settings = NS(llm_model='deepseek-flash', llm_base_url='https://api.deepseek.com',
                  llm_api_key=NS(get_secret_value=lambda:'TEST_PRIVATE_KEY'), llm_thinking_enabled=True, llm_reasoning_effort='high')
    first = review_one(tmp_path, job, settings)
    second = review_one(tmp_path, job, settings)
    assert first['cached'] is False and second['cached'] is True and len(calls) == 1
    body = calls[0]
    assert body['model'] == 'deepseek-flash' and body['reasoning_effort'] == 'high'
    assert len(body['messages']) == 2
    image = body['messages'][1]['content'][1]
    assert image['type'] == 'image_url' and image['image_url']['url'].startswith('data:image/png;base64,')
    saved = (tmp_path / 'reviews/test-region/record.json').read_text(encoding='utf-8')
    assert all(value not in saved for value in ['TEST_PRIVATE_KEY', 'PRIVATE_REASONING', 'data:image'])


def test_actual_crop_uses_target_page_and_dimensions(tmp_path):
    import shutil
    import pdfplumber
    from pypdf import PdfWriter
    from review_mineru_quality import crop_region
    from PIL import Image
    renderer = shutil.which('pdftoppm')
    if not renderer:
        pytest.skip('Poppler is required for integration rendering')
    writer = PdfWriter()
    writer.add_blank_page(width=600, height=800)
    writer.add_blank_page(width=600, height=800)
    path = tmp_path / 'source.pdf'
    with path.open('wb') as stream: writer.write(stream)
    u = dict(unit(), page=2, bbox=[250, 250, 750, 500])
    image_path = tmp_path / 'crop.png'
    with pdfplumber.open(path) as pdf:
        meta = crop_region(pdf, u, image_path, renderer, dpi=72, margin_points=10)
    assert meta['page'] == 2 and meta['target_bbox_pdf_points'] == [150, 200, 450, 400]
    assert Image.open(image_path).size == (320, 220)
