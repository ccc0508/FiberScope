"""Cited image history survives index removal and exposes only verified content-addressed PNGs."""
from dataclasses import asdict
from pathlib import Path
import shutil

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from app.qa_images import cache_answer_images,cached_image_path,backup_answer_images
from app import literature
from literature_rag.domain.errors import InfrastructureError
from tests.test_visual_evidence import fixture,PNG


def test_cached_cited_image_survives_source_index_removal(tmp_path):
    source=tmp_path/'library';source.mkdir();_,_,assets=fixture(source)
    result=dict(citations=[dict(visual_assets=[asdict(assets[0])])])
    history=tmp_path/'history';cache_answer_images(result,source,history)
    shutil.rmtree(source)
    assert cached_image_path(history,assets[0].sha256).read_bytes()==PNG
    with pytest.raises(FileNotFoundError):cached_image_path(history,'../private')
    cache_answer_images(dict(citations=[]),source,history)


def test_public_image_endpoint_rejects_missing_hashes_and_tampering(tmp_path):
    source=tmp_path/'library';source.mkdir();_,_,assets=fixture(source)
    history=tmp_path/'history';cache_answer_images(dict(citations=[dict(visual_assets=[asdict(assets[0])])]),source,history)
    config=literature.LiteratureSettings(enabled=True,data_dir=history,library_dir=source)
    app=FastAPI();app.include_router(literature.router(config))
    path='/api/v1/literature/images/'+assets[0].sha256
    with TestClient(app) as client:
        response=client.get(path)
        assert response.status_code==200 and response.content==PNG
        assert response.headers['content-type']=='image/png'
        assert client.get('/api/v1/literature/images/not-a-hash').status_code==404
        cached_image_path(history,assets[0].sha256).write_bytes(PNG+b'changed')
        assert client.get(path).status_code==404


def test_uncited_model_input_images_are_kept_and_included_in_database_snapshot_backup(tmp_path):
    import json,sqlite3
    source=tmp_path/'library';source.mkdir();_,_,assets=fixture(source)
    result=dict(citations=[],retrieved_evidence=[dict(visual_assets=[asdict(assets[0])])])
    history=tmp_path/'history';cache_answer_images(result,source,history)
    database=tmp_path/'backup.sqlite3'
    with sqlite3.connect(database) as conn:
        conn.execute('CREATE TABLE questions(result_json TEXT)')
        conn.execute('INSERT INTO questions VALUES (?)',(json.dumps(result),))
    destination=tmp_path/'backup.assets'
    assert backup_answer_images(database,history,destination)==1
    assert (destination/'qa-images'/(assets[0].sha256+'.png')).read_bytes()==PNG
    assert json.loads((destination/'images.json').read_text(encoding='utf-8'))['sha256']==[assets[0].sha256]
