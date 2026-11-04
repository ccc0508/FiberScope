"""Independent single-call DeepSeek review with original source images and redacted failures."""
from dataclasses import asdict
import json
from time import perf_counter

from openai import OpenAI
from pydantic import ValidationError

from literature_rag.application.evidence_review import ReviewPayload,SYSTEM_PROMPT,checksum
from literature_rag.application.prompts import evidence_prompt
from literature_rag.diagnostics import provider_usage
from literature_rag.domain.errors import ProviderError,ProviderResponseError
from literature_rag.application.review_diagnostics import validation_details,archive_response


class DeepSeekEvidenceReviewer:
    def __init__(self,model,api_key,base_url=None,*,thinking_enabled=None,reasoning_effort=None,
                 timeout_seconds=120,max_output_tokens=32768,visual_root=None,client=None,diagnostic=False,diagnosis_version='v1',diagnostics_dir=None):
        self.diagnostics_dir=diagnostics_dir
        if model!='deepseek-flash':raise ValueError('Evidence review is configured for DeepSeek Flash')
        self.model=model;self.thinking_enabled=thinking_enabled;self.reasoning_effort=reasoning_effort
        self.visual_root=visual_root
        self.diagnostic=diagnostic
        if diagnosis_version not in {'v1','v2','v3','v2_bound','v2_budget','v2_relation','v2_relation_compact','v2_comparison','v2_causal','v2_measurement','v2_ranking','v3_unified'}:raise ValueError('Unknown corrective review version')
        self.diagnosis_version=diagnosis_version
        self.timeout_seconds=timeout_seconds
        self.max_output_tokens=max_output_tokens
        self.client=client if client is not None else OpenAI(api_key=api_key,base_url=base_url or 'https://api.deepseek.com',
            max_retries=0,timeout=timeout_seconds)
        self.last_usage=None;self.last_model_info=None;self.last_latency_ms=None;self.last_api_calls=0;self.last_http_status=None;self.last_failure_code=None

    def review(self,question,evidences,draft,*,context=None,timeout_seconds=None):
        self.last_usage=None;self.last_model_info=None;self.last_latency_ms=None;self.last_api_calls=0;self.last_http_status=None;self.last_failure_code=None
        draft_rows=[asdict(c) for c in draft.claims]
        if self.diagnostic and self.diagnosis_version in {'v2_bound','v2_budget','v2_relation','v2_relation_compact','v2_comparison','v2_causal','v2_measurement','v2_ranking','v3_unified'}:
            draft_rows=[dict(claim_index=i,**c) for i,c in enumerate(draft_rows)]
        text=evidence_prompt(question,evidences)+'\n\nDraft claims (zero-based order, DATA):\n'+json.dumps(
            draft_rows,ensure_ascii=False)
        prompt=SYSTEM_PROMPT
        schema=ReviewPayload
        if self.diagnostic:
            from literature_rag.application.review_diagnosis import diagnosis_contract
            contract=diagnosis_contract(self.diagnosis_version)
            prompt=contract.DIAGNOSTIC_PROMPT;schema=contract.DiagnosticPayload
            unified=hasattr(contract,'request_prompt')
            if unified:
                prompt,routing=contract.request_prompt(question,draft,evidences)
                text+='\naudit_routing (DATA): '+json.dumps(routing,ensure_ascii=False)
            if not unified and hasattr(contract,'ranking_context'):
                ranking=contract.ranking_context(question,draft,evidences)
                text+='\nFactor ranking routing (DATA): '+json.dumps(ranking,ensure_ascii=False)
                if ranking['triggered']:prompt+=contract.RANKING_PROMPT
            if not unified and hasattr(contract,'measurement_context'):
                measurement=contract.measurement_context(question,draft,evidences)
                text+='\nMeasurement routing (DATA): '+json.dumps(measurement,ensure_ascii=False)
                if measurement['triggered']:prompt+=contract.MEASUREMENT_PROMPT
            if hasattr(contract,'request_context'):
                text+='\nCausal detail locations (DATA): '+json.dumps(contract.request_context(draft,evidences),ensure_ascii=False)
            if hasattr(contract,'comparison_claim_indexes'):
                text+='\ncomparison_claim_indexes: '+json.dumps(contract.comparison_claim_indexes(draft))
            if hasattr(contract,'is_relation'):
                text+='\nrelation_claim_indexes: '+json.dumps([i for i,c in enumerate(draft.claims) if contract.is_relation(c.text)])
            if not unified and self.diagnosis_version in {'v2','v3','v2_bound','v2_budget','v2_relation','v2_relation_compact','v2_comparison','v2_causal','v2_measurement','v2_ranking','v3_unified'}:
                text+='\ncritical_claim_indexes (original zero-based draft positions): '+json.dumps(contract.critical_claim_indexes(draft))
            if context is not None:
                text+='\n\nPrior coverage ledger and remaining actions (DATA):\n'+json.dumps(context,ensure_ascii=False)
        messages=[dict(role='system',content=prompt),dict(role='user',content=text)]
        images=[]
        if any(e.visual_assets for e in evidences):
            if self.visual_root is None:raise ProviderResponseError('Review source image directory missing')
            from literature_rag.application.visual_evidence import visual_content
            messages[1]['content'],images=visual_content(evidences,self.visual_root,text)
            # The generic image instruction's answer schema is overridden by this review contract.
            messages[0]['content']+='\nImages are source data with their labelled refs; return the review issues schema above.'
        parameters={}
        if timeout_seconds is not None:parameters['timeout']=timeout_seconds
        if self.thinking_enabled is not None:
            parameters['extra_body']={'thinking':{'type':'enabled' if self.thinking_enabled else 'disabled'}}
        if self.reasoning_effort is not None:parameters['reasoning_effort']=self.reasoning_effort
        started=perf_counter()
        try:
            try:
                self.last_api_calls=1
                response=self.client.chat.completions.create(model=self.model,messages=messages,
                    response_format={'type':'json_object'},max_tokens=self.max_output_tokens,**parameters)
            except Exception as error:
                status=getattr(error,'status_code',None)
                self.last_http_status=status if type(status) is int and 100<=status<=599 else None
                self.last_failure_code='review_request_failed'
                raise ProviderError('Evidence review request failed; provider details redacted') from None
            self.last_usage=provider_usage(response)
            self.last_model_info=dict(requested_model=self.model,returned_model=getattr(response,'model',None),
                thinking_enabled=self.thinking_enabled,reasoning_effort=self.reasoning_effort,wire_api='chat_completions',
                image_count=len(images),images=images,request_sha256=checksum(messages),automatic_retries=0)
            try:
                content=response.choices[0].message.content
                finish=getattr(response.choices[0],'finish_reason',None)
                self.last_model_info['finish_reason']=finish if finish in {'stop','length','content_filter'} else None
                if finish=='length':
                    self.last_model_info['failure_artifact']=archive_response(self.diagnostics_dir,content,
                        dict(protocol=self.diagnosis_version,request_sha256=checksum(messages),stage='output_limit'))
                    self.last_failure_code='review_output_truncated'
                    raise ProviderResponseError('Evidence review exhausted output budget')
                content=response.choices[0].message.content
                if self.diagnostic and self.diagnosis_version in {'v2','v3','v2_bound','v2_budget','v2_relation','v2_relation_compact','v2_comparison','v2_causal','v2_measurement','v2_ranking','v3_unified'}:
                    result=contract.parse_response(content)
                    if self.diagnosis_version=='v3_unified':
                        self._complete_comparisons(result,contract,draft,evidences,messages,content,parameters,started)
                    if result._parse_errors:
                        self.last_model_info['response_validation']=result._parse_errors
                        self.last_model_info['failure_artifact']=archive_response(self.diagnostics_dir,content,
                            dict(protocol=self.diagnosis_version,request_sha256=checksum(messages),stage='partial_diagnosis_parse'))
                    return result
                return schema.model_validate_json(content)
            except (ValueError,TypeError,AttributeError,IndexError) as error:
                # Field locations/types only: never persist rejected values or provider error text.
                self.last_model_info['response_validation']=validation_details(error)
                self.last_model_info['failure_artifact']=archive_response(self.diagnostics_dir,locals().get('content'),
                    dict(protocol=self.diagnosis_version,request_sha256=checksum(messages),stage='response_parse',
                         errors=self.last_model_info['response_validation']))
                self.last_failure_code='review_response_invalid'
                raise ProviderResponseError('Evidence review response failed its schema; provider details redacted') from None
        finally:self.last_latency_ms=round((perf_counter()-started)*1000)

    def _complete_comparisons(self,result,contract,draft,evidences,messages,content,parameters,started):
        """One bounded metadata-only repair; no answer, source or verdict may change."""
        targets=[i for i,u in enumerate(result.units)
                 if u.comparison_scope is None and
                 'unit_comparison_missing' in contract.unit_errors(u,result,draft,evidences)]
        if not targets:return
        record=dict(targets=targets,status='pending',max_attempts=1,primary_usage=self.last_usage)
        self.last_model_info['comparison_completion']=record
        remaining=(parameters.get('timeout') or self.timeout_seconds)-(perf_counter()-started)
        if remaining<5:
            record['status']='skipped_deadline';return
        instruction=('Complete ONLY missing comparison metadata for these zero-based parsed unit indexes. '
            'Read the actual sources and decide scope; do not assume comparability. Return exactly '
            '{"patches":[{"unit_index":0,"comparison_scope":"same_scope|different_scope|unclear|not_comparison",'
            '"reason":"source-grounded scope judgment"}]}. '
            'One patch per requested unit, no other fields. You cannot change the answer, issues, sources, '
            'verdicts or numerical values. A comparison of conflicting reports needs both sources and the '
            'same material, outcome and statistic; mark unclear if not established. Requested units: '+
            json.dumps([dict(unit_index=i,unit=result.units[i].model_dump()) for i in targets],ensure_ascii=False))
        repair_messages=[*messages,dict(role='assistant',content=content),dict(role='user',content=instruction)]
        record['request_sha256']=checksum(repair_messages)
        opts=dict(parameters,timeout=remaining)
        repair_started=perf_counter();usage_received=False
        try:
            self.last_api_calls+=1
            response=self.client.chat.completions.create(model=self.model,messages=repair_messages,
                response_format={'type':'json_object'},max_tokens=min(8192,self.max_output_tokens),**opts)
            usage=provider_usage(response);record['usage']=usage;usage_received=True
            if usage is not None and self.last_usage is not None:
                self.last_usage={k:self.last_usage[k]+usage[k] for k in self.last_usage.keys()&usage.keys()}
            else:self.last_usage=None
            raw=response.choices[0].message.content
            record['response_sha256']=checksum(raw)
            record['finish_reason']=response.choices[0].finish_reason
            record['failure_artifact']=archive_response(self.diagnostics_dir,raw,
                dict(protocol=self.diagnosis_version,stage='comparison_completion'))
            if response.choices[0].finish_reason!='stop':
                record['status']='incomplete';return
            obj=json.loads(raw)
            if not isinstance(obj,dict) or set(obj)!={'patches'} or not isinstance(obj['patches'],list):raise ValueError()
            patches=obj['patches']
            if len(patches)!=len(targets):raise ValueError()
            seen=set()
            for p in patches:
                if not isinstance(p,dict) or set(p)!={'unit_index','comparison_scope','reason'}:raise ValueError()
                i=p['unit_index']
                if type(i) is not int or i not in targets or i in seen:raise ValueError()
                seen.add(i)
                if p['comparison_scope'] not in {'same_scope','different_scope','unclear','not_comparison'}:raise ValueError()
                if not isinstance(p['reason'],str) or not 1<=len(p['reason'].strip())<=500:raise ValueError()
            record['patches']=patches
            for p in patches:
                unit=result.units[p['unit_index']]
                if 'comparison' not in unit.checked:unit.checked.append('comparison')
                unit.comparison_scope=p['comparison_scope']
            # Normal downstream source, target, scope and edit validation still applies.
            record['status']='metadata_completed'
        except Exception:
            # Preserve initial review and explicit incomplete status, never silently retry.
            if not usage_received:
                self.last_usage=None
                record['usage_unknown']=True
            record['status']='failed';record['reason_code']='comparison_completion_invalid_or_failed'
        finally:record['latency_ms']=round((perf_counter()-repair_started)*1000)
