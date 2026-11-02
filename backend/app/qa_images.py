"""Persist cited images independently of the selected retrieval library."""
from hashlib import sha256
import json
from pathlib import Path
import re
import shutil
import sqlite3

from literature_rag.application.visual_evidence import verified_image_path
from literature_rag.domain.models import VisualAsset
from literature_rag.domain.errors import InfrastructureError


def cache_answer_images(result,library,history_root):
    assets={a['sha256']:a for citation in [*result.get('citations',[]),*result.get('retrieved_evidence',[])]
            for a in citation.get('visual_assets',[])}
    if not assets:return
    cache=Path(history_root).resolve()/'qa-images'
    if cache.is_symlink():raise InfrastructureError('history image directory must not be a symlink')
    cache.mkdir(parents=True,exist_ok=True)
    for checksum,row in assets.items():
        asset=VisualAsset(**row)
        source=verified_image_path(library,asset)
        target=cache/(checksum+'.png')
        if target.is_symlink():raise InfrastructureError('history image path must not be a symlink')
        if target.exists():
            if sha256(target.read_bytes()).hexdigest()!=checksum:raise InfrastructureError('history source image changed')
        else:
            # One bounded question worker writes this content-addressed cache.
            temporary=cache/(checksum+'.tmp')
            temporary.write_bytes(source.read_bytes());temporary.replace(target)


def cached_image_path(history_root,checksum):
    if not re.fullmatch(r'[0-9a-f]{64}',checksum):raise FileNotFoundError
    allowed=Path(history_root).resolve()/'qa-images'
    path=(allowed/(checksum+'.png')).resolve(strict=True)
    if not path.is_relative_to(allowed) or sha256(path.read_bytes()).hexdigest()!=checksum:
        raise FileNotFoundError
    return path


def backup_answer_images(database,history_root,output):
    """Read the frozen DB snapshot, then copy exactly its referenced input images."""
    output=Path(output)
    if output.exists():raise FileExistsError('Image backup destination already exists')
    checksums=set()
    with sqlite3.connect(Path(database).resolve().as_uri()+'?mode=ro',uri=True) as connection:
        for (payload,) in connection.execute('SELECT result_json FROM questions WHERE result_json IS NOT NULL'):
            result=json.loads(payload)
            checksums.update(a['sha256'] for e in [*result.get('citations',[]),*result.get('retrieved_evidence',[])]
                for a in e.get('visual_assets',[]))
    if not checksums:return 0
    target=output/'qa-images';target.mkdir(parents=True)
    for checksum in sorted(checksums):
        source=cached_image_path(history_root,checksum)
        shutil.copy2(source,target/(checksum+'.png'))
    (output/'images.json').write_text(json.dumps(dict(version=1,sha256=sorted(checksums)),indent=2)+'\n',encoding='utf-8',newline='\n')
    return len(checksums)
