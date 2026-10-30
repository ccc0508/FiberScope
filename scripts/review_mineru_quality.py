"""Prepare, review, export and index flagged MinerU regions; never sample normal regions."""
from argparse import ArgumentParser
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from hashlib import sha256
from html import escape
import base64
import json
import math
import re
from pathlib import Path
import shutil
import subprocess
import sys
from time import perf_counter

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'backend'))
sys.path.insert(0, str(ROOT / 'scripts'))
import index_mineru_experiment as native
from mineru_quality import (VERSION, PROMPT_VERSION, REVIEW_SYSTEM, HEADER_SYSTEM, inspect, review_prompt,
                            validate_review, fingerprint, apply_reviews, normalized, plain, header_review)
from mineru_sections import organize


def now():
    return datetime.now(timezone.utc).isoformat()


def save(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + '.tmp')
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n', encoding='utf-8', newline='\n')
    temp.replace(path)


def load(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def digest(path):
    return sha256(Path(path).read_bytes()).hexdigest()


def rules():
    return {name: digest(ROOT / 'scripts' / name) for name in
            ['mineru_quality.py', 'mineru_sections.py', 'review_mineru_quality.py']}


def crop_region(pdf, unit, destination, renderer, dpi=180, margin_points=18):
    """Render locally with Poppler; only the flagged rectangle plus a small margin leaves the machine."""
    from PIL import Image, ImageDraw
    page = pdf.pages[unit['page']-1]
    if page.rotation % 360:
        raise ValueError('Rotated pages need an explicit coordinate transform')
    x0, top, x1, bottom = unit['bbox']
    target = (x0 * page.width/1000, top * page.height/1000,
              x1 * page.width/1000, bottom * page.height/1000)
    if not (0 <= target[0] < target[2] <= page.width and 0 <= target[1] < target[3] <= page.height):
        raise ValueError('Empty or invalid target rectangle')
    clip = (max(0, target[0]-margin_points), max(0, target[1]-margin_points),
            min(page.width, target[2]+margin_points), min(page.height, target[3]+margin_points))
    scale = dpi/72
    left, upper = math.floor(clip[0]*scale), math.floor(clip[1]*scale)
    right, lower = math.ceil(clip[2]*scale), math.ceil(clip[3]*scale)
    subprocess.run([renderer, '-f', str(unit['page']), '-l', str(unit['page']), '-singlefile',
        '-r', str(dpi), '-x', str(left), '-y', str(upper), '-W', str(right-left), '-H', str(lower-upper),
        '-png', str(pdf.stream.name), str(destination.with_suffix(''))],
        check=True, capture_output=True)
    with Image.open(destination) as image:
        image = image.convert('RGB')
        # Outside the target, so the marking does not cover characters.
        border = (max(0, target[0]*scale-left-3), max(0, target[1]*scale-upper-3),
                  min(image.width-1, target[2]*scale-left+3), min(image.height-1, target[3]*scale-upper+3))
        ImageDraw.Draw(image).rectangle(border, outline='#2869bd', width=2)
        image.save(destination)
        size = list(image.size)
    return dict(page=unit['page'], target_bbox_pdf_points=list(target), crop_bbox_pdf_points=list(clip),
                dpi=dpi, size_pixels=size, image_sha256=digest(destination),
                pdf_text=page.crop(target).extract_text(x_tolerance=2, y_tolerance=3) or '')


def header_targets(unit, page):
    """Read vector line/character geometry only inside this flagged table, with no paper-specific labels."""
    import fitz
    from mineru_quality import table_values
    cells = Counter()
    for row in re.findall(r'<tr\b[^>]*>(.*?)</tr>', unit['text'], re.I | re.S):
        if table_values('<tr>'+row+'</tr>'):
            continue
        values = re.findall(r'<t[dh]\b[^>]*>(.*?)</t[dh]>', row, re.I | re.S)
        if any(re.fullmatch(r'\(\d{3}\)', plain(c)) for c in values):
            cells.update(c for c in values if re.fullmatch(r'\d{3}', c))
    bbox = unit['bbox']
    rectangle = fitz.Rect(bbox[0]*page.rect.width/1000, bbox[1]*page.rect.height/1000,
                          bbox[2]*page.rect.width/1000, bbox[3]*page.rect.height/1000)
    words = [w for w in page.get_text('words', clip=rectangle) if w[4] in cells]
    if len(words) != sum(cells.values()):
        raise ValueError('Cannot uniquely locate the ambiguous table header labels')
    geometry = []
    for block in page.get_text('rawdict', clip=rectangle)['blocks']:
        for line in block.get('lines', []):
            chars = [c for span in line['spans'] for c in span['chars']]
            text = ''.join(c['c'] for c in chars)
            if text not in cells:
                continue
            bars, positions = [], set()
            for drawing in page.get_drawings():
                rect = drawing['rect']
                if not (0 < rect.width < 30 and rect.height < .8 and .2 < line['bbox'][1]-rect.y0 < 8):
                    continue
                covered = [i for i,c in enumerate(chars) if
                    min(rect.x1,c['bbox'][2])-max(rect.x0,c['bbox'][0]) >= .6*(c['bbox'][2]-c['bbox'][0])]
                if covered:
                    positions.update(covered)
                    bars.append(list(rect))
            geometry.append(dict(text=text, bbox=list(line['bbox']), characters=[dict(character=c['c'], bbox=c['bbox']) for c in chars],
                bar_digit_indices=sorted(positions) if bars else None, horizontal_lines=bars,
                index_convention='zero-based character positions; null means no reliable vector-line determination'))
    return cells, words, geometry


def make_header_job(job, pdf, text_pdf, output, renderer):
    unit = job['unit']
    page = text_pdf[unit['page']-1]
    cells, words, geometry = header_targets(unit, page)
    extra_images, regions = [], []
    for index, word in enumerate(words):
        bbox = [unit['bbox'][0], max(0, (word[1]-25)/page.rect.height*1000),
                unit['bbox'][2], min(1000, (word[3]+4)/page.rect.height*1000)]
        image_path = Path('crops') / (unit['source_id'] + '-cell-header-'+str(index)+'.png')
        crop = crop_region(pdf, dict(unit, bbox=bbox), Path(output)/image_path, renderer, dpi=300, margin_points=6)
        if index == 0:
            job.update(**crop, image_path=image_path.as_posix())
        else:
            extra_images.append(dict(image_path=image_path.as_posix(), image_sha256=crop['image_sha256'],
                page=unit['page'], role='another_header_of_same_flagged_table'))
        regions.append(dict(page=unit['page'], bbox=bbox))
    job.update(review_mode='table_header_cells', extra_images=extra_images, verified_regions=regions, header_geometry=geometry)
    job['prompt'] = json.dumps(dict(task='Verify only the ambiguous numeric table header labels, including overbar scope.',
        original_cell_contents=dict(cells), source_page=unit['page'],
        auxiliary_pdf_vector_geometry=geometry,
        geometry_note='Coordinates come directly from PDF characters and drawn horizontal lines. Compare line x-ranges to individual digit bboxes. Zero-based indices; do not reinterpret them.',
        constraint='Do not change or transcribe data rows, caption or footnotes.'), ensure_ascii=False)
    job['prompt_sha256'] = sha256(job['prompt'].encode()).hexdigest()
    return job


def prepare(source_dir, parse_dir, output):
    import pdfplumber
    import fitz
    output = Path(output).resolve()
    if output.exists():
        raise ValueError('Use a new review directory; previous source/reviews are immutable')
    renderer = shutil.which('pdftoppm')
    if not renderer:
        raise ValueError('Poppler pdftoppm is required for review crops')
    document, pdf_path, blocks, units, excluded, _ = native.plan(source_dir, parse_dir, 1_000_000)
    findings = inspect(units, blocks, document.id)
    output.mkdir(parents=True)
    (output / 'crops').mkdir()
    shutil.copyfile(pdf_path, output / 'source.pdf')
    save(output / 'source.json', dict(document_id=document.id, filename=document.filename,
        source_pdf_sha256=document.file_hash, blocks=blocks, units=units, excluded=excluded))
    jobs = []
    with pdfplumber.open(output / 'source.pdf') as pdf, fitz.open(output / 'source.pdf') as text_pdf:
        for unit in units:
            flagged = [f for f in findings if f['source_id'] == unit['source_id']]
            if not flagged:
                continue
            image_path = Path('crops') / (unit['source_id'] + '.png')
            crop = crop_region(pdf, unit, output / image_path, renderer)
            crop['pdfplumber_text'] = crop['pdf_text']
            crop['pdf_text'] = text_pdf[unit['page']-1].get_text('text', clip=fitz.Rect(crop['target_bbox_pdf_points']), sort=True)
            prompt = review_prompt(unit, flagged, crop['pdf_text'])
            job = dict(source_id=unit['source_id'], unit=unit, findings=flagged,
                image_path=image_path.as_posix(), prompt=prompt, prompt_sha256=sha256(prompt.encode()).hexdigest(), **crop)
            if unit['kind'] == 'table' and any(f['code'] == 'ambiguous_numeric_table_header' for f in flagged):
                make_header_job(job, pdf, text_pdf, output, renderer)
            jobs.append(job)
    save(output / 'jobs.json', jobs)
    save(output / 'findings.json', findings)
    study = dict(version=VERSION, prompt_version=PROMPT_VERSION, status='prepared', prepared_at=now(),
        source_pdf_sha256=document.file_hash, source_sha256=digest(output / 'source.json'),
        native_content_sha256=digest(Path(parse_dir) / 'mineru-content-list.json'),
        source_dir=str(Path(source_dir).resolve()), parse_dir=str(Path(parse_dir).resolve()),
        jobs_sha256=digest(output / 'jobs.json'), findings_sha256=digest(output / 'findings.json'),
        rules_sha256=rules(), source_units=len(units), flagged_units=len(jobs), findings=len(findings),
        unflagged_sample_count=0, provider_calls=0, answer_model_config_sha256=digest(ROOT / 'backend/.env.literature'),
        policy='Only flagged native regions. No normal-region sampling, whole-PDF model input, QA tasks or answer grading.')
    save(output / 'study.json', study)
    snapshot_rules(output)
    return {key: study[key] for key in ['status', 'source_units', 'flagged_units', 'findings', 'unflagged_sample_count', 'provider_calls']}


def snapshot_rules(output):
    folder = Path(output) / 'rule-snapshots'
    folder.mkdir(exist_ok=True)
    for name in rules():
        shutil.copyfile(ROOT / 'scripts' / name, folder / name)


def verify(output, require_current=True):
    output = Path(output).resolve()
    study = load(output / 'study.json')
    if require_current and study['rules_sha256'] != rules():
        raise ValueError('Review rules changed; preserve this run and prepare a new version')
    for name, checksum in study['rules_sha256'].items():
        if digest(output / 'rule-snapshots' / name) != checksum:
            raise ValueError('Archived review rules changed')
    for name, key in [('source.json', 'source_sha256'), ('jobs.json', 'jobs_sha256'), ('findings.json', 'findings_sha256'), ('source.pdf', 'source_pdf_sha256')]:
        if digest(output / name) != study[key]:
            raise ValueError('Frozen review input changed: ' + name)
    jobs = load(output / 'jobs.json')
    for job in jobs:
        for item in [job, *job.get('extra_images', [])]:
            image = (output / item['image_path']).resolve()
            if not image.is_relative_to((output / 'crops').resolve()) or digest(image) != item['image_sha256']:
                raise ValueError('Review image changed or escaped the crop directory')
    return study, load(output / 'source.json'), jobs


def revise(output, destination):
    """Reapply improved local guards to the same model responses, without paying to rerun them."""
    import fitz
    output, destination = Path(output).resolve(), Path(destination).resolve()
    study, source, jobs = verify(output, require_current=False)
    if destination.exists() or destination.is_relative_to(output):
        raise ValueError('Use a new sibling revision directory')
    if study['prompt_version'] != PROMPT_VERSION:
        raise ValueError('Prompt changes require new model requests')
    destination.mkdir(parents=True)
    for filename in ['source.pdf', 'source.json', 'findings.json']:
        shutil.copyfile(output / filename, destination / filename)
    shutil.copytree(output / 'crops', destination / 'crops')
    if (output / 'reviews').exists():
        shutil.copytree(output / 'reviews', destination / 'reviews')
    if (output / 'prior-records.json').exists():
        shutil.copyfile(output / 'prior-records.json', destination / 'prior-records.json')
    with fitz.open(destination / 'source.pdf') as pdf:
        for job in jobs:
            regions = job.get('verified_regions')
            if regions:
                texts = []
                for region in regions:
                    page = pdf[region['page']-1]
                    b = region['bbox']
                    rect = fitz.Rect(b[0]*page.rect.width/1000,b[1]*page.rect.height/1000,b[2]*page.rect.width/1000,b[3]*page.rect.height/1000)
                    texts.append(page.get_text('text', clip=rect, sort=True))
                job['validation_pdf_text'] = '\n'.join(texts)
            else:
                job['validation_pdf_text'] = pdf[job['page']-1].get_text('text', clip=fitz.Rect(job['target_bbox_pdf_points']), sort=True)
            if job['unit']['kind'] == 'table':
                job['header_geometry'] = header_targets(job['unit'], pdf[job['page']-1])[2]
            path = destination / 'reviews' / job['source_id'] / 'record.json'
            if path.exists():
                record = load(path)
                if record.get('status') == 'failed' and record.get('error_type') == 'ValueError' and record.get('response_text'):
                    try:
                        parsed = validate_review(json.loads(record['response_text']))
                    except (ValueError, TypeError):
                        continue
                    record.update(status='completed', review=parsed,
                        revalidated_without_api_call=dict(original_record_sha256=digest(path),
                            reason='Accept harmless native heading_level on a keep action; metadata remains unchanged.'))
                    save(path, record)
    save(destination / 'jobs.json', jobs)
    study.update(revision_of=str(output), previous_study_sha256=digest(output / 'study.json'),
        previous_rules_sha256=study['rules_sha256'], rules_sha256=rules(),
        jobs_sha256=digest(destination / 'jobs.json'), revision_at=now(),
        revision_new_model_calls=0, local_validation_reference='PyMuPDF rectangle text; original model requests/crops remain unchanged.')
    save(destination / 'study.json', study)
    snapshot_rules(destination)
    return dict(status='revised', reused_regions=len(jobs), new_model_calls=0)


def escalate(output, destination):
    """Widen only already-flagged pending regions; preserve and charge-count previous calls."""
    import fitz
    import pdfplumber
    _, source, _, records, _, ledger, _, _ = materialize(output)
    pending = {e['source_id']: e for e in ledger if e['status'] == 'pending'}
    revise(output, destination)
    destination = Path(destination).resolve()
    study = load(destination / 'study.json')
    jobs = load(destination / 'jobs.json')
    prior = load(destination / 'prior-records.json') if (destination / 'prior-records.json').exists() else []
    changed = []
    renderer = shutil.which('pdftoppm')
    with pdfplumber.open(destination / 'source.pdf') as pdf, fitz.open(destination / 'source.pdf') as text_pdf:
        for job in jobs:
            if job['source_id'] not in pending:
                continue
            unit = job['unit']
            page = pdf.pages[unit['page']-1]
            regions, extra_images = [], []
            text = job['validation_pdf_text']
            if unit['kind'] == 'table':
                make_header_job(job, pdf, text_pdf, destination, renderer)
                regions, extra_images = job['verified_regions'], job['extra_images']
                instruction = None
            elif unit['bbox'][3] >= 800 and unit['page'] < len(pdf.pages):
                # A source-block tail must positively match the next-page paragraph before that crop is allowed.
                continuation = None
                next_page = text_pdf[unit['page']]
                for block in next_page.get_text('blocks', sort=True):
                    if block[6] != 0 or block[1] > next_page.rect.height*.35:
                        continue
                    words = re.findall(r'\w+', plain(block[4]).casefold())
                    # Match punctuation/spacing independently, including PDF ligatures.
                    start = normalized(''.join(words[:3]))
                    end = normalized(''.join(words[-12:]))
                    raw = normalized(re.sub(r'[^\w]', '', plain(unit['text'])))
                    if len(words) >= 18 and start in raw and end in raw:
                        continuation = block
                        break
                if continuation is None:
                    continue
                bbox = [continuation[0]/next_page.rect.width*1000, continuation[1]/next_page.rect.height*1000,
                        continuation[2]/next_page.rect.width*1000, continuation[3]/next_page.rect.height*1000]
                extra_unit = dict(unit, page=unit['page']+1, bbox=bbox)
                extra_path = Path('crops') / (unit['source_id'] + '-continuation.png')
                extra = crop_region(pdf, extra_unit, destination / extra_path, renderer)
                extra_images.append(dict(image_path=extra_path.as_posix(), image_sha256=extra['image_sha256'],
                    page=extra_unit['page'], role='matched_continuation_of_same_flagged_source'))
                text += '\n' + continuation[4]
                regions = [dict(page=unit['page'], bbox=unit['bbox']), dict(page=extra_unit['page'], bbox=bbox)]
                instruction = ('The original native block crosses a page boundary. Image 1 is the first part; '
                    'image 2 is its positively text-matched continuation on the next page. Transcribe both targets '
                    'as one paragraph, without repeating or dropping the boundary words. Do not include other paragraphs.')
            else:
                continue
            old = records.get(unit['source_id'])
            if old:
                prior.append(old)
                (destination / 'reviews' / unit['source_id'] / 'record.json').unlink()
            job.update(extra_images=extra_images, verified_regions=regions, validation_pdf_text=text, pdf_text=text)
            if instruction is not None:
                job['prompt'] = review_prompt(unit, job['findings'], text)+'\nFollow-up verification:\n'+instruction
            job['prompt_sha256'] = sha256(job['prompt'].encode()).hexdigest()
            changed.append(unit['source_id'])
    save(destination / 'prior-records.json', prior)
    save(destination / 'jobs.json', jobs)
    study.update(jobs_sha256=digest(destination / 'jobs.json'), escalated_regions=changed,
        escalation_new_model_calls=0, escalation_policy='Only pending flagged source regions; no normal sampling.')
    save(destination / 'study.json', study)
    return dict(status='escalation_prepared', regions=changed, new_model_calls=0)


def request_for(job, model, thinking, effort, output):
    data = base64.b64encode((Path(output) / job['image_path']).read_bytes()).decode('ascii')
    content = [dict(type='text', text=job['prompt']),
               dict(type='image_url', image_url=dict(url='data:image/png;base64,' + data, detail='original'))]
    for image in job.get('extra_images', []):
        extra_data = base64.b64encode((Path(output) / image['image_path']).read_bytes()).decode('ascii')
        content.append(dict(type='image_url', image_url=dict(url='data:image/png;base64,' + extra_data, detail='original')))
    scoped_header = job.get('review_mode') == 'table_header_cells'
    body = dict(model=model, messages=[dict(role='system', content=HEADER_SYSTEM if scoped_header else REVIEW_SYSTEM), dict(role='user', content=content)],
        response_format=dict(type='json_object'), max_tokens=6000 if scoped_header else 12000)
    if thinking is not None:
        body['extra_body'] = dict(thinking=dict(type='enabled' if thinking else 'disabled'))
    if effort is not None:
        body['reasoning_effort'] = effort
    return body


def review_one(output, job, settings):
    from openai import OpenAI
    from literature_rag.diagnostics import provider_usage
    folder = Path(output) / 'reviews' / job['source_id']
    body = request_for(job, settings.llm_model, settings.llm_thinking_enabled, settings.llm_reasoning_effort, output)
    request_sha = fingerprint(body)
    if (folder / 'record.json').exists():
        existing = load(folder / 'record.json')
        if existing['request_sha256'] != request_sha:
            raise ValueError('A review with different inputs already exists')
        return dict(source_id=job['source_id'], status=existing['status'], cached=True)
    folder.mkdir(parents=True, exist_ok=True)
    record = dict(status='started', started_at=now(), source_id=job['source_id'], request_sha256=request_sha,
        prompt_sha256=job['prompt_sha256'], image_sha256=job['image_sha256'],
        model_info=dict(requested_model=settings.llm_model, thinking_enabled=settings.llm_thinking_enabled,
                        reasoning_effort=settings.llm_reasoning_effort), usage=None,
        monetary_cost=None, monetary_cost_note='Provider did not return an invoice amount.', provider_calls=1)
    save(folder / 'record.json', record)
    start = perf_counter()
    client = OpenAI(api_key=settings.llm_api_key.get_secret_value(), base_url=settings.llm_base_url,
                    max_retries=0, timeout=180, organization='', project='')
    client.organization = None
    client.project = None
    client._custom_headers = {}
    try:
        response = client.chat.completions.create(**body)
        record['usage'] = provider_usage(response)
        record['model_info'].update(returned_model=response.model,
                                   system_fingerprint=getattr(response, 'system_fingerprint', None))
        content = response.choices[0].message.content
        record['finish_reason'] = getattr(response.choices[0], 'finish_reason', None)
        # Store the observable review only, never reasoning_content or credentials.
        record['response_text'] = content
        if job.get('review_mode') == 'table_header_cells':
            record['header_review'] = json.loads(content)
            record['review'] = header_review(record['header_review'], job['unit'])
            record['review_scope'] = 'flagged_header_cells_only; unchanged data/caption/footnotes copied from native source'
        else:
            record['review'] = validate_review(json.loads(content))
        record['status'] = 'completed'
    except Exception as error:
        record['status'] = 'failed'
        record['error_type'] = type(error).__name__
        status = getattr(error, 'status_code', None)
        if type(status) is int:
            record['http_status'] = status
    finally:
        client.close()
        record.update(finished_at=now(), latency_seconds=round(perf_counter()-start, 4))
        save(folder / 'record.json', record)
    return dict(source_id=job['source_id'], status=record['status'], cached=False,
                decision=record.get('review', {}).get('decision'), usage=record['usage'])


def review(output, env_file, workers):
    from literature_rag.config import Settings
    study, _, jobs = verify(output)
    if digest(env_file) != study['answer_model_config_sha256']:
        raise ValueError('Use the exact answer-model configuration frozen at preparation')
    settings = Settings(_env_file=env_file)
    if settings.llm_provider != 'deepseek' or not settings.llm_api_key:
        raise ValueError('The configured DeepSeek answering model/key is required')
    lock = Path(output) / '.review.lock'
    with lock.open('x', encoding='utf-8') as stream:
        stream.write(now())
    try:
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = [pool.submit(review_one, output, job, settings) for job in jobs]
            for future in as_completed(futures):
                print(json.dumps(future.result(), ensure_ascii=False), flush=True)
    finally:
        lock.unlink()
    return dict(status='review_finished', jobs=len(jobs))


def materialize(output):
    study, source, jobs = verify(output)
    records = {}
    for job in jobs:
        path = Path(output) / 'reviews' / job['source_id'] / 'record.json'
        if path.exists():
            record = load(path)
            if record['image_sha256'] != job['image_sha256'] or record['prompt_sha256'] != job['prompt_sha256']:
                raise ValueError('Review record does not match the frozen region')
            config = record['model_info']
            expected = request_for(job, config['requested_model'], config['thinking_enabled'], config['reasoning_effort'], output)
            if fingerprint(expected) != record['request_sha256']:
                raise ValueError('Review request no longer reproduces')
            records[job['source_id']] = record
    units, ledger = apply_reviews(source['units'], jobs, records)
    organized = organize(units, source['document_id'], source['blocks'])
    ledger_by_source = {item['source_id']: item for item in ledger}
    for chunk in organized['chunks']:
        chunk['quality_provenance'] = []
        for span in chunk['source_spans']:
            entry = ledger_by_source.get(span['source_id'])
            chunk['quality_provenance'].append(dict(source_id=span['source_id'], page=span['page'], bbox=span['bbox'],
                view_start=span['start'], view_end=span['end'],
                offset_space='corrected_unit' if entry and entry['status'] == 'accepted_correction' else 'native_unit',
                correction_id=entry['id'] if entry else None,
                status=entry['status'] if entry else 'not_flagged_not_reviewed',
                verified_regions=entry.get('verified_regions', []) if entry else []))
        verified_pages = [r['page'] for p in chunk['quality_provenance'] for r in p['verified_regions']]
        if verified_pages:
            chunk['page_start'] = min(chunk['page_start'], *verified_pages)
            chunk['page_end'] = max(chunk['page_end'], *verified_pages)
    prior = load(Path(output) / 'prior-records.json') if (Path(output) / 'prior-records.json').exists() else []
    all_calls = {}
    for record in [*prior, *records.values()]:
        all_calls[fingerprint([record['request_sha256'], record['started_at']])] = record
    usage = Counter()
    for record in all_calls.values():
        for key, value in (record.get('usage') or {}).items():
            if type(value) is int:
                usage[key] += value
    info = dict(version=VERSION, source_pdf_sha256=study['source_pdf_sha256'], source_units=len(units),
        flagged_units=len(jobs), findings=study['findings'], unflagged_sample_count=0,
        review_statuses=dict(Counter(r['status'] for r in records.values())),
        correction_statuses=dict(Counter(item['status'] for item in ledger)),
        provider_calls=sum(r['provider_calls'] for r in all_calls.values()), usage=dict(usage),
        monetary_cost=None, chunks=len(organized['chunks']), chunk_kinds=organized['chunk_kinds'],
        sections=len(organized['sections']), remaining_organization_anomalies=organized['anomalies'],
        source_preservation='Immutable native snapshot plus reversible full before/after ledger. New offsets explicitly identify the corrected view.',
        quality_scope='AI verification of flagged crops only; no normal sampling, expert certification or whole-paper accuracy claim.')
    return study, source, jobs, records, units, ledger, organized, info


def export(output, destination):
    destination = Path(destination).resolve()
    if destination.exists():
        raise ValueError('Use a new export directory')
    study, source, jobs, records, units, ledger, organized, info = materialize(output)
    destination.mkdir(parents=True)
    (destination / 'crops').mkdir()
    for image in (Path(output) / 'crops').glob('*.png'):
        shutil.copyfile(image, destination / 'crops' / image.name)
    save(destination / 'summary.json', info)
    save(destination / 'corrections.json', ledger)
    save(destination / 'findings.json', load(Path(output) / 'findings.json'))
    save(destination / 'corrected-units.json', units)
    save(destination / 'sections.json', dict(sections=organized['sections'], document_titles=organized['document_titles']))
    save(destination / 'review-records.json', records)
    if (Path(output) / 'prior-records.json').exists():
        shutil.copyfile(Path(output) / 'prior-records.json', destination / 'prior-records.json')
    (destination / 'chunks.jsonl').write_text(''.join(json.dumps(c, ensure_ascii=False)+'\n' for c in organized['chunks']), encoding='utf-8', newline='\n')
    e = lambda value: escape(str(value), quote=True)
    labels = {'accepted_correction': '已通过程序检查的AI修正', 'verified_unchanged': 'AI复核无需修改', 'pending': '待进一步核对'}
    parts = ['<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>MinerU解析复核</title>',
        '<style>body{margin:0;background:#f4f7fa;color:#203247;font:15px/1.75 system-ui,"Microsoft YaHei",sans-serif}main{max-width:1250px;margin:30px auto;padding:0 20px}article{background:white;border:1px solid #dce5ee;border-radius:10px;padding:20px;margin:18px 0}img{max-width:100%;height:auto;border:1px solid #dde4ee}pre{white-space:pre-wrap;overflow-wrap:anywhere;background:#f5f7fa;padding:12px;font:13px/1.7 monospace}.pair{display:grid;grid-template-columns:1fr 1fr;gap:14px}.pair>div{min-width:0}summary{cursor:pointer}a{color:#2869bd}@media(max-width:850px){.pair{display:block}}</style><main>',
        '<h1>MinerU解析质量检查与局部复核</h1>',
        '<p>检查 → DeepSeek图片复核 → 修正版与修改记录。仅发送标记区域及小范围边缘；正常区域抽查数为0。结果属于AI复核，不等同于专家审核。</p>',
        '<p>原始PDF和MinerU输出保留。修正版单独保存；无法通过数值、原文或结构检查的建议保留待核对。尚未切换网站默认索引。</p>',
        '<p>原生单位：'+str(info['source_units'])+'；标记区域：'+str(info['flagged_units'])+'；修正：'+str(info['correction_statuses'].get('accepted_correction',0))+'；确认无需修改：'+str(info['correction_statuses'].get('verified_unchanged',0))+'；待核对：'+str(info['correction_statuses'].get('pending',0))+'。</p>',
        '<details><summary>调用、Token用量及完整统计</summary><pre>'+e(json.dumps(info, ensure_ascii=False, indent=2))+'</pre></details>',
        '<p><a href="corrections.json">完整修正记录</a> · <a href="corrected-units.json">整理后的原生单位</a> · <a href="chunks.jsonl">重新组织的检索块</a></p>']
    for entry in ledger:
        job = next(j for j in jobs if j['source_id'] == entry['source_id'])
        record = records.get(entry['source_id'], {})
        parts += ['<article id="'+e(entry['source_id'])+'"><h2>'+e(entry['source_id'])+' · 第'+str(entry['page'])+'页</h2>',
            '<p><strong>'+e(labels[entry['status']])+'</strong> · '+e(', '.join(f['code'] for f in entry['findings']))+'</p>',
            '<p>'+e((entry['review'] or {}).get('reason', record.get('error_type', '尚无有效复核')))+'</p>',
            '<p>程序检查：'+e(entry['automatic_checks'] or '通过')+'</p>',
            '<details><summary>查看发给模型的局部截图（蓝框为目标区域）</summary><img loading="lazy" src="'+e(job['image_path'])+'" alt="第'+str(entry['page'])+'页异常区域"></details>',
            '<div class="pair"><div><h3>原始解析</h3><pre>'+e(entry['original_text'])+'</pre></div><div><h3>当前保留内容</h3><pre>'+e(entry['corrected_text'])+'</pre></div></div>',
            '<details><summary>修改差异、模型判断及来源</summary><pre>'+e(json.dumps(entry, ensure_ascii=False, indent=2))+'</pre></details></article>']
        for item in job.get('extra_images', []):
            parts.insert(-1, '<details><summary>'+e(item['role'])+' · 第'+str(item['page'])+'页</summary><img loading="lazy" src="'+e(item['image_path'])+'" alt="异常区域补充截图"></details>')
    parts.append('</main></html>')
    (destination / 'comparison.html').write_text(''.join(parts), encoding='utf-8', newline='\n')
    save(destination / 'publication.json', dict(version=VERSION, source_pdf_sha256=study['source_pdf_sha256'],
        rules_sha256=study['rules_sha256'], private_source_sha256=study['source_sha256'],
        private_jobs_sha256=study['jobs_sha256'],
        files={p.relative_to(destination).as_posix(): digest(p) for p in sorted(destination.rglob('*')) if p.is_file()}))
    return info


def build_index(output, destination, env_file):
    """Build a separate library only after all flagged regions pass review guards."""
    from dataclasses import replace
    from literature_rag.config import Settings
    from literature_rag.adapters.sqlite.metadata_store import SqliteMetadataStore
    from literature_rag.adapters.chroma.vector_store import ChromaVectorStore
    from literature_rag.adapters.providers.openai import OpenAIEmbedder
    from literature_rag.domain.models import Chunk, DocumentStatus, VectorRecord
    study, source, jobs, records, units, ledger, organized, info = materialize(output)
    if info['correction_statuses'].get('pending', 0):
        raise ValueError('Unresolved flagged regions block index creation; preserve pending records')
    destination = Path(destination).resolve()
    if destination.exists():
        raise ValueError('Use a new index directory')
    settings = Settings(_env_file=env_file)
    document, _, _, _, _, _ = native.plan(study['source_dir'], study['parse_dir'], 1_000_000)
    destination.mkdir(parents=True)
    (destination / 'papers').mkdir()
    relative = Path('papers') / (document.file_hash + '.pdf')
    shutil.copyfile(Path(output) / 'source.pdf', destination / relative)
    store = SqliteMetadataStore(destination / 'metadata.sqlite3')
    store.initialize()
    store.upsert_document(replace(document, file_path=relative, status=DocumentStatus.PENDING, chunk_count=0))
    chunks, mapping = [], {}
    for i, unit in enumerate(organized['chunks']):
        cid = 'chk_' + fingerprint([VERSION, document.id, i, unit['text']])[:20]
        chunks.append(Chunk(cid, document.id, document.filename, unit['page_start'], unit['page_end'], i,
            unit['text'], (len(unit['text'])+3)//4, settings.embedding_model, kind=unit['kind']))
        mapping[cid] = {k: v for k, v in unit.items() if k != 'text'}
    save(destination / 'quality-ledger.json', ledger)
    save(destination / 'native-source.json', source)
    manifest = dict(version=VERSION, status='building', source_pdf_sha256=document.file_hash,
        chunks=len(chunks), chunk_kinds=organized['chunk_kinds'], sections=organized['sections'],
        mapping=mapping, quality_summary=info, quality_ledger_sha256=digest(destination / 'quality-ledger.json'),
        native_source_sha256=digest(destination / 'native-source.json'),
        paragraph_target_chars=organized['paragraph_target_chars'], max_evidence_chars=organized['max_evidence_chars'],
        embedding_model=settings.embedding_model, embedding_dimensions=settings.embedding_dimensions, embedding_calls=[],
        visual_policy='Vision used only to verify flagged parse regions; QA still receives textual evidence.',
        activation='Isolated experimental library; no default configuration changes.')
    save(destination / 'structure.json', manifest)
    try:
        embedder = OpenAIEmbedder(settings.embedding_model, settings.embedding_dimensions,
                                 settings.embedding_api_key.get_secret_value(), settings.embedding_base_url)
        vectors = ChromaVectorStore(destination / 'chroma', settings.embedding_provider,
                                    settings.embedding_model, settings.embedding_dimensions)
        for start in range(0, len(chunks), settings.embedding_batch_size):
            batch = chunks[start:start+settings.embedding_batch_size]
            call = dict(status='started', chunk_count=len(batch), usage=None)
            manifest['embedding_calls'].append(call)
            save(destination / 'structure.json', manifest)
            try:
                embeddings = embedder.embed_documents([c.text for c in batch])
                call['status'] = 'completed'
                call['usage'] = embedder.last_usage
                vectors.upsert([VectorRecord(c.id, c.document_id, c.text, c.page_start, c.page_end, c.filename) for c in batch], embeddings)
            finally:
                save(destination / 'structure.json', manifest)
        store.complete_document(document.id, document.page_count, chunks)
        manifest.update(status='ready', metadata_sha256=digest(destination / 'metadata.sqlite3'))
    except Exception:
        manifest['status'] = 'failed'
        raise
    finally:
        save(destination / 'structure.json', manifest)
    return dict(status=manifest['status'], chunks=len(chunks), embedding_calls=manifest['embedding_calls'])


def main():
    parser = ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['prepare', 'review', 'export', 'build', 'revise', 'escalate'])
    parser.add_argument('--run-dir', type=Path, required=True)
    parser.add_argument('--source-dir', type=Path)
    parser.add_argument('--parse-dir', type=Path)
    parser.add_argument('--destination', type=Path)
    parser.add_argument('--env-file', type=Path, default=ROOT / 'backend/.env.literature')
    parser.add_argument('--workers', type=int, choices=range(1, 5), default=2)
    args = parser.parse_args()
    if args.action == 'prepare':
        if args.source_dir is None or args.parse_dir is None:
            parser.error('prepare requires --source-dir and --parse-dir')
        result = prepare(args.source_dir, args.parse_dir, args.run_dir)
    elif args.action == 'review':
        result = review(args.run_dir, args.env_file, args.workers)
    else:
        if args.destination is None:
            parser.error('export/build requires --destination')
        if args.action == 'revise':
            result = revise(args.run_dir, args.destination)
        elif args.action == 'escalate':
            result = escalate(args.run_dir, args.destination)
        else:
            result = export(args.run_dir, args.destination) if args.action == 'export' else build_index(args.run_dir, args.destination, args.env_file)
    print(json.dumps(result, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    try:
        main()
    except Exception as error:
        # Exceptions may contain provider URLs or request data; never expose raw error messages.
        print(json.dumps(dict(status='operation_failed', error_type=type(error).__name__)), flush=True)
        sys.exit(1)
