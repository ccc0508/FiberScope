"""Citation identities come from typed successful tool outputs, never prose."""
import re

CITABLE_KINDS = {'source_text', 'source_image', 'experiment_query', 'calculation'}


def citation_records(tool, response):
    if response.get('status') != 'completed':
        return []
    result = response.get('result', {})
    kind = {'search_literature': 'source_text', 'read_section': 'source_text',
        'read_table': 'source_text', 'view_image': 'source_image',
        'query_experiment_data': 'experiment_query', 'calculate_change': 'calculation'}.get(tool)
    if not kind:
        return []
    if tool == 'search_literature':
        entries = result.get('evidence', [])
    elif tool == 'read_section':
        entries = result.get('sources', [])
    elif tool == 'read_table':
        entries = [result.get('table', {})]
    else:
        entries = [result]
    return [dict(ref=e['ref'], kind=kind, citable=True) for e in entries
        if re.fullmatch(r'\[[1-9][0-9]*\]', str(e.get('ref', '')))]


def invalid_references(answer, allowed):
    # Also catch grouped/range citations and accidental internal IDs. The public
    # format is one numeric reference per bracket: [1][2], never [1,2] or [T15].
    tokens = re.findall(r'\[(?:\d[\d\s,，、;；\-–—]*|T\d+|txt_[a-fA-F0-9]+)\]', answer)
    return sorted({token for token in tokens if token not in allowed})
