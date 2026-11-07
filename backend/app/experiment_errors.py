"""Safe field diagnostics: identifiers from the submitted AST, metadata from allowed views."""
import re
from difflib import get_close_matches
import sqlglot
from sqlglot import exp
from sqlglot.optimizer.scope import traverse_scope, Scope


def field_diagnostic(error, query, schema):
    code={'42703':'undefined_column','42702':'ambiguous_column'}.get(error.sqlstate)
    if not code:return None
    tree=sqlglot.parse_one(query,read='postgres')
    columns=list(tree.find_all(exp.Column))
    # PostgreSQL normally names the offending column in message_primary.
    # Never return that raw message: accept only identifiers also present in AST.
    quoted=re.findall(r'"([^"\n]+)"',getattr(error.diag,'message_primary','') or '')
    token=next((s for s in quoted if any(s in (c.name, f'{c.table}.{c.name}') for c in columns)),None)
    if not token:
        return dict(error_code=code,message='字段无法解析；请对照所选视图目录检查字段及别名。',diagnostic={'column_identified':False})
    matches=[c for c in columns if token in (c.name,f'{c.table}.{c.name}')]
    name=matches[0].name
    scopes=[]
    for scope in traverse_scope(tree):
        if not any(c in matches for c in scope.columns):continue
        sources=[]
        for alias,source in scope.sources.items():
            if isinstance(source, exp.Table):
                sources.append(dict(alias=alias,view='fiber.'+source.name,
                    has_column=name in schema.get(source.name,[]),
                    similar_columns=get_close_matches(name,schema.get(source.name,[]),n=5,cutoff=.55)))
            elif isinstance(source,Scope):
                # Derived output may have aliases/wildcards; don't pretend to infer its schema.
                sources.append(dict(alias=alias,kind='derived_query',hint='检查子查询实际输出列及别名'))
        scopes.append(dict(sources=sources))
    return dict(error_code=code,
        message=('字段在当前查询中有歧义，请用正确的表别名限定。' if code=='ambiguous_column'
                 else '字段在当前查询作用域中不存在；检查字段拼写、所属视图或子查询输出。'),
        diagnostic=dict(requested_column=name,requested_qualifier=matches[0].table or None,
            candidate_scopes=scopes,available_in=['fiber.'+v for v,cs in sorted(schema.items()) if name in cs],
            hint='候选只说明真实字段归属，不是自动改写指令。按原问题选字段和视图，确认数据粒度；不要擅自放宽筛选。'))


def diagnose(error, query, connect, allowed):
    if error.sqlstate not in ('42703','42702'):return None
    # The failed transaction has already rolled back; use a fresh read-only connection.
    with connect() as db:
        rows=db.execute("SELECT table_name,column_name FROM information_schema.columns WHERE table_schema='fiber' AND table_name=ANY(%s) ORDER BY table_name,ordinal_position",(sorted(allowed),)).fetchall()
    schema={v:[] for v in allowed}
    for v,c in rows:schema[v].append(c)
    return field_diagnostic(error,query,schema)
