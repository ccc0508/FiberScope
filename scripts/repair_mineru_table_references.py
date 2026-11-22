"""Backfill Chinese heading roles and verified table references in a local MinerU library."""
from argparse import ArgumentParser
from collections import Counter
from hashlib import sha256
import json
from pathlib import Path
from tempfile import TemporaryDirectory

import fitz

from index_table_evidence import build_table_links
from index_mineru_experiment import native_units
from mineru_roles import classify,collection_blocks
from mineru_table_reference_recovery import recover_table_references
from literature_rag.adapters.sqlite.metadata_store import SqliteMetadataStore
from literature_rag.application.body_context import BodySectionCatalog
from literature_rag.application.table_evidence import TableRelations
from literature_rag.application.visual_evidence import VisualCatalog


def encoded(data):
    return (json.dumps(data,ensure_ascii=False,indent=2,allow_nan=False)+'\n').encode('utf-8')


def checksum(data):
    return sha256(data).hexdigest()


def update_roles(chunks,mapping,native_roles):
    """Update only previously unclassified source spans; keep original chunk identities."""
    changed=Counter()
    for c in chunks:
        record=mapping[c.id]
        if record['role_status']!='uncertain' or record['role_signals']!=['insufficient_role_evidence']:
            continue
        roles=[native_roles.get(span['source_id']) for span in record['source_spans']]
        if not roles or any(r is None or r['status']!='identified' for r in roles):continue
        first=roles[0]
        if not all((r['role'],r['group'])==(first['role'],first['group']) for r in roles):continue
        if first['role']=='body' and c.kind=='paragraph':
            record.update(content_role='body',role_status='identified',role_group=first['group'],
                role_signals=sorted({signal for r in roles for signal in r['signals']}))
            changed[c.filename]+=1
    return changed


def repair(root,*,apply=False,document_id=None):
    root=Path(root).resolve()
    files=('structure.json','table-retrieval.json','visual-retrieval.json')
    original={f:(root/f).read_bytes() for f in files}
    structure,table,visual=(json.loads(original[f]) for f in files)
    if structure.get('status')!='ready' or table['source_structure_sha256']!=checksum(original[files[0]]):
        raise ValueError('Expected a complete and consistent structure catalog')
    store=SqliteMetadataStore(root/'metadata.sqlite3');old_catalog=BodySectionCatalog.load(root,store)
    identity=table['embedding'];old_relations=TableRelations.load(root,store,**identity)
    old_relations.validate_body_catalog(old_catalog)
    VisualCatalog.load(root,store,**identity)
    processed=set();changed=Counter();recovered={};ledger=[]
    for d in store.list_documents():
        if document_id is not None and d.id!=document_id:continue
        source=root/'imports'/(d.id+'.json')
        if not source.is_file():continue
        imported=json.loads(source.read_bytes())
        pdf_path=(root/d.file_path).resolve()
        if not pdf_path.is_relative_to(root) or checksum(pdf_path.read_bytes())!=imported['pdf_sha256']:
            raise ValueError('Cached MinerU input does not match the library PDF')
        native,_=collection_blocks(imported['native_blocks']);chunks=old_catalog.documents[d.id]
        units,_=native_units(native,d.page_count,max_chars=1_000_000)
        changed.update(update_roles(chunks,structure['mapping'],classify(units)))
        with fitz.open(pdf_path) as pdf:
            found,reviews=recover_table_references(pdf,chunks,structure['mapping'])
        recovered.update(found);ledger.extend(reviews);processed.add(d.id)
    if not processed:raise ValueError('No matching papers with cached MinerU input')
    catalog=BodySectionCatalog(list(old_catalog.chunks.values()),structure)
    chunks=[c for c in catalog.chunks.values() if c.document_id in processed]
    generated=build_table_links(chunks,structure['mapping'],recovered)
    old=table['links'];added=[link for link in generated if link not in old]
    table['links']=generated+[link for link in old if link not in generated]
    previous=table.get('table_reference_repairs',[])
    repairs=[r for r in previous if r['document_id'] not in processed]+ledger
    table['table_reference_repairs']=repairs
    TableRelations(table,store,old_relations.vectors).validate_body_catalog(catalog)
    result=dict(documents_scanned=len(processed),body_roles_added=dict(changed),links_added=len(added),
        total_links=len(table['links']),confirmed=dict(Counter(r['method'] for r in ledger if r['status']=='confirmed')),
        recovered_table_numbers=dict(Counter(r['table_number'] for r in ledger if r['status']=='confirmed')),
        review_required=sum(r['status']=='review_required' for r in ledger),applied=False)
    if not apply or not (changed or added or repairs!=previous):return result

    payload={files[0]:encoded(structure)}
    table['source_structure_sha256']=visual['structure_sha256']=checksum(payload[files[0]])
    payload[files[1]]=encoded(table);payload[files[2]]=encoded(visual)
    backup=root/'table-reference-repair-backups'/checksum(b''.join(original.values()))[:16]
    backup.mkdir(parents=True,exist_ok=True)
    for f,content in original.items():
        path=backup/f
        if not path.exists():path.write_bytes(content)
        if path.read_bytes()!=content:raise ValueError('Repair backup does not match the original catalog')
    with TemporaryDirectory(prefix='repair-table-references-',dir=root) as tmp:
        stage=Path(tmp)
        for f in files:(stage/f).write_bytes(payload[f])
        if any((root/f).read_bytes()!=original[f] for f in files):
            raise ValueError('The library changed during repair; retry against its latest snapshot')
        published=[]
        try:
            for f in files:
                (stage/f).replace(root/f);published.append(f)
            active=BodySectionCatalog.load(root,store)
            TableRelations.load(root,store,**identity).validate_body_catalog(active)
            VisualCatalog.load(root,store,**identity)
        except BaseException:
            for f in reversed(published):
                restored=stage/f;restored.write_bytes(original[f]);restored.replace(root/f)
            raise
    result.update(applied=True,backup=str(backup))
    return result


if __name__=='__main__':
    parser=ArgumentParser(description=__doc__)
    parser.add_argument('library',type=Path)
    parser.add_argument('--document-id',help='Limit repair to one imported paper')
    parser.add_argument('--apply',action='store_true',help='Apply after validation; defaults to dry run')
    args=parser.parse_args()
    print(json.dumps(repair(args.library,apply=args.apply,document_id=args.document_id),ensure_ascii=False))
