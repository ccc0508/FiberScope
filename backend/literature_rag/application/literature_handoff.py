"""Reuse successful directory pages within one question; locators never carry citations."""
import re


def directory_key(request):
    if request.get('tool') == 'list_sections' and set(request) <= {'tool','reason','document_id','offset'}:
        doc, offset = request.get('document_id'), request.get('offset', 0)
        if isinstance(doc,str) and type(offset) is int and offset >= 0:
            return doc, offset


def section_handoff(children, assigned, task):
    ids = {item['requirement_id'] for item in assigned}
    pages, candidates, visited = {}, {}, set()
    terms = set(re.findall(r'[a-z0-9]+', task.lower()))
    for child in children:
        if child['role'] != 'literature':
            continue
        for event in child.get('trace', {}).get('tool_calls', []):
            request, result = event['request'], event['result']
            if result.get('status') != 'completed' or event.get('model_delivery', {}).get('status') != 'delivered':
                continue
            doc = request.get('document_id')
            if request['tool'] == 'read_section':
                visited.add((doc,request.get('section_id')))
            key = directory_key(request)
            if not key:
                continue
            pages[key] = result
            if not ids.intersection(event.get('coverage_schedule', {}).get('target_requirements', [])):
                continue
            sections = candidates.setdefault(doc,{})
            for row in result.get('result', {}).get('sections', []):
                sections[row['section_id']] = row['title']
    hints = []
    for doc, sections in candidates.items():
        def rank(item):
            sid, title = item
            words = set(re.findall(r'[a-z0-9]+',title.lower()))
            return (-len(words & terms), (doc,sid) in visited)
        for sid,title in sorted(sections.items(),key=rank)[:8]:
            hints.append(dict(document_id=doc, section_id=sid, title=title[:160], already_read=(doc,sid) in visited))
    return pages,hints
