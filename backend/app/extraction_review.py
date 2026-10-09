"""Versioned human review; extraction snapshots remain immutable."""
from __future__ import annotations

import csv
from io import StringIO
import json
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, Request, Response
from pydantic import BaseModel, ConfigDict, Field, model_validator

from .qa_history import now
from literature_extraction import number, ExtractionError

EDIT_FIELDS = ('raw_material', 'metric', 'measurement_state', 'raw_value', 'raw_unit', 'experiment_condition', 'condition_source')


class ReviewInput(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    expected_revision: int = Field(ge=0)
    raw_material: str = Field(min_length=1, max_length=200)
    metric: str = Field(pattern=r'^[a-z][a-z0-9_]{1,60}$')
    measurement_state: Literal['raw_material', 'unrefined', 'refined', 'unspecified']
    raw_value: str = Field(min_length=1, max_length=60)
    raw_unit: str = Field(max_length=60)
    experiment_condition: str = Field(default='', max_length=600)
    condition_source: str = Field(default='', max_length=300)
    status: Literal['pending', 'confirmed', 'rejected']
    suitability: Literal['unassessed', 'suitable', 'unsuitable'] = 'unassessed'
    note: str = Field(default='', max_length=1200)

    @model_validator(mode='after')
    def validate_review(self):
        try:
            number(self.raw_value)
        except ExtractionError:
            raise ValueError('请输入有限数值，不包含单位或误差范围。') from None
        if self.status != 'confirmed' and self.suitability != 'unassessed':
            raise ValueError('确认原文抄录后才能标记建模适用性。')
        if (self.status == 'rejected' or self.suitability != 'unassessed') and not self.note:
            raise ValueError('驳回或评估建模适用性时请填写说明。')
        if self.experiment_condition and not self.condition_source:
            raise ValueError('补充实验条件时请注明原文来源。')
        return self


def initialize_reviews(conn):
    conn.executescript('''
        CREATE TABLE IF NOT EXISTS extraction_reviews (
            task_id TEXT NOT NULL REFERENCES extraction_tasks(id), record_id TEXT NOT NULL,
            revision INTEGER NOT NULL, review_json TEXT NOT NULL,
            PRIMARY KEY(task_id,record_id)
        );
        CREATE TABLE IF NOT EXISTS extraction_review_events (
            task_id TEXT NOT NULL REFERENCES extraction_tasks(id), record_id TEXT NOT NULL,
            revision INTEGER NOT NULL, previous_json TEXT NOT NULL,
            current_json TEXT NOT NULL, created_at TEXT NOT NULL,
            PRIMARY KEY(task_id,record_id,revision)
        );
        PRAGMA user_version=2;
    ''')


def initial_review(original):
    return {'revision': 0, 'status': 'pending', 'suitability': 'unassessed', 'note': '',
            'current': {k: original.get(k, '') for k in EDIT_FIELDS},
            'updated_at': None, 'approved_for_training': False}


def find_original(task, record_id):
    if task['status'] != 'completed' and not task.get('has_reviewable_result'):
        raise HTTPException(409, '提取完成后才能审核。')
    for r in (task.get('snapshot') or {}).get('result', {}).get('measurements', []):
        if r['record_id'] == record_id:
            return r
    raise HTTPException(404, '没有找到这条候选数据。')


class ReviewStoreMixin:
    def reviews(self, task_id):
        with self.connection() as conn:
            return {r['record_id']: json.loads(r['review_json']) for r in conn.execute(
                'SELECT record_id,review_json FROM extraction_reviews WHERE task_id=?', (task_id,))}

    def review(self, owner, task_id, record_id, body):
        with self.connection() as conn:
            conn.execute('BEGIN IMMEDIATE')
            row = conn.execute('SELECT * FROM extraction_tasks WHERE id=?', (task_id,)).fetchone()
            if row is None:
                raise HTTPException(404, '没有找到这条提取记录。')
            if row['owner_id'] != owner:
                raise HTTPException(403, '该记录公开可查看，审核仅限原提交浏览器修改。')
            task = self.public(row)
            original = find_original(task, record_id)
            stored = conn.execute('SELECT review_json FROM extraction_reviews WHERE task_id=? AND record_id=?', (task_id,record_id)).fetchone()
            previous = json.loads(stored['review_json']) if stored else initial_review(original)
            if previous['revision'] != body.expected_revision:
                raise HTTPException(409, '这条记录已被更新，请重新读取后再保存。')
            current = {k: getattr(body,k) for k in EDIT_FIELDS}
            if any(current[k] != previous['current'][k] for k in EDIT_FIELDS) and not body.note:
                raise HTTPException(422, '修改数据时请填写修改说明。')
            current['value'] = number(body.raw_value)
            # Compare editable fields, not the derived numeric display value.
            if (all(current[k] == previous['current'][k] for k in EDIT_FIELDS) and
                    previous['status'] == body.status and previous['suitability'] == body.suitability and previous['note'] == body.note):
                return previous
            stamp = now()
            reviewed = {'revision': previous['revision']+1, 'current': current, 'status': body.status,
                        'suitability': body.suitability, 'note': body.note, 'updated_at': stamp,
                        'approved_for_training': body.status == 'confirmed' and body.suitability == 'suitable'}
            encoded = json.dumps(reviewed,ensure_ascii=False)
            conn.execute('INSERT INTO extraction_review_events VALUES(?,?,?,?,?,?)',
                         (task_id,record_id,reviewed['revision'],json.dumps(previous,ensure_ascii=False),encoded,stamp))
            conn.execute('INSERT INTO extraction_reviews VALUES(?,?,?,?) ON CONFLICT(task_id,record_id) DO UPDATE SET revision=excluded.revision,review_json=excluded.review_json',
                         (task_id,record_id,reviewed['revision'],encoded))
            return reviewed

    def review_events(self, task_id, record_id):
        with self.connection() as conn:
            return [{'revision': r['revision'], 'previous': json.loads(r['previous_json']),
                     'current': json.loads(r['current_json']), 'created_at': r['created_at']}
                    for r in conn.execute('SELECT * FROM extraction_review_events WHERE task_id=? AND record_id=? ORDER BY revision DESC', (task_id,record_id))]


def review_summary(task, reviews):
    total = (task.get('snapshot') or {}).get('result', {}).get('measurement_count', 0)
    return {'total': total, 'confirmed': sum(r['status']=='confirmed' for r in reviews.values()),
            'rejected': sum(r['status']=='rejected' for r in reviews.values()),
            'pending': total-sum(r['status']!='pending' for r in reviews.values()),
            'suitable': sum(r['approved_for_training'] for r in reviews.values())}


def csv_safe(value):
    text = str(value)
    # Quoting alone does not prevent spreadsheet formula execution.
    return "'"+text if text.lstrip().startswith(('=', '+', '-', '@')) or text.startswith(('\t','\r','\n')) else text


def router(runner, detail, check_origin):
    routes = APIRouter()

    @routes.post('/{task_id}/reviews/{record_id}')
    def review(task_id: UUID, record_id: str, body: ReviewInput, request: Request, response: Response):
        check_origin(request)
        owner = runner.session(request,response)
        # Check save state here; enforce write ownership inside the atomic transaction.
        detail(owner,str(task_id))
        return runner.database(runner.store.review,owner,str(task_id),record_id,body)

    @routes.get('/{task_id}/reviews/{record_id}/events')
    def events(task_id: UUID,record_id: str, request: Request,response: Response):
        owner = runner.session(request,response)
        task = detail(owner,str(task_id))
        find_original(task,record_id)
        return {'data':runner.database(runner.store.review_events,str(task_id),record_id)}

    @routes.get('/{task_id}/confirmed')
    def confirmed(task_id: UUID,request: Request,format: Literal['jsonl','csv'] = Query('jsonl')):
        holder = Response()
        owner = runner.session(request,holder)
        task = detail(owner,str(task_id))
        records = (task.get('snapshot') or {}).get('result',{}).get('measurements',[])
        reviews = runner.database(runner.store.reviews,str(task_id))
        rows = [{'schema_version':1,'task_id':str(task_id),'source':task['source'],
                 'original':r,'review':reviews[r['record_id']]}
                for r in records if reviews.get(r['record_id'],{}).get('status')=='confirmed']
        headers = {k:v for k,v in holder.headers.items() if k!='content-length'}
        if format=='jsonl':
            text = ''.join(json.dumps(r,ensure_ascii=False)+'\n' for r in rows)
            headers['Content-Disposition']='attachment; filename="confirmed-literature-data.jsonl"'
            return Response(text,media_type='application/x-ndjson',headers=headers)
        buffer=StringIO(newline='')
        fields=['task_id','record_id',*EDIT_FIELDS,'original_raw_value','original_raw_unit','original_raw_material','original_metric','original_measurement_state','source_filename','source_pdf_sha256',
                'source_pdf_page','source_table','source_kind','source_quote','source_value_text','value_qualifier','source_bbox_pt','revision','reviewed_at','suitability','approved_for_training','note']
        writer=csv.DictWriter(buffer,fieldnames=fields)
        writer.writeheader()
        for row in rows:
            r,review,source=row['original'],row['review'],row['source']
            data={'task_id':str(task_id),'record_id':r['record_id'],**review['current'],
                  'original_raw_value':r['raw_value'],'original_raw_unit':r['raw_unit'],
                  'original_raw_material':r['raw_material'],'original_metric':r['metric'],
                  'original_measurement_state':r['measurement_state'],'source_filename':source['filename'],
                  'source_pdf_sha256':source['pdf_sha256'],'source_pdf_page':r['source_pdf_page'],
                  'source_table':r['source_table'],'source_kind':r.get('source_kind','table'),
                  'source_quote':r.get('source_quote',''),'source_bbox_pt':json.dumps(r['source_bbox_pt']),
                  'source_value_text':r.get('source_value_text',r['raw_value']),
                  'value_qualifier':r.get('value_qualifier','unspecified'),
                  'revision':review['revision'],'reviewed_at':review['updated_at'],'suitability':review['suitability'],
                  'approved_for_training':review['approved_for_training'],'note':review['note']}
            # Numeric literals (including negative values) retain their exact
            # spelling; escape only text fields that Excel could execute.
            writer.writerow({k:data[k] if k in ('raw_value','original_raw_value') else csv_safe(data[k]) for k in fields})
        headers['Content-Disposition']='attachment; filename="confirmed-literature-data.csv"'
        return Response('\ufeff'+buffer.getvalue(),media_type='text/csv; charset=utf-8',headers=headers)
    return routes
