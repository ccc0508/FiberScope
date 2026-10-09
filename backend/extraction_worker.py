"""Isolated, bounded PDF parsing and model process; safe JSON output only."""
import json
from pathlib import Path
import sys
from time import sleep

sys.path.insert(0, str(Path(__file__).resolve().parent))


def save_artifact(artifact, name, value):
    temp = artifact / (name + '.tmp')
    temp.write_text(json.dumps(value, ensure_ascii=False), encoding='utf-8')
    for attempt in range(5):
        try:
            temp.replace(artifact / name)
            return
        except PermissionError:
            # A Windows reader can briefly hold the old checkpoint open.
            if attempt == 4:
                raise
            sleep(.02 * (attempt + 1))


def main():
    from literature_extraction import snapshot, extract, configuration, ExtractionError
    from literature_rag.config import Settings
    from literature_document import extract_document, document_configuration
    body = json.loads(sys.stdin.read())
    artifact = Path(body['artifact_dir']).resolve()

    def save(name, value):
        save_artifact(artifact, name, value)

    try:
        settings = Settings(_env_file=Path(__file__).resolve().parent / '.env.literature')
        save('configuration.json', {**configuration(settings), **(
            document_configuration() if body.get('mode') == 'document' else {})})
        if not settings.llm_api_key or not settings.llm_model or settings.llm_provider not in ('deepseek', 'openai'):
            raise ExtractionError('missing_configuration')
        if body.get('mode') == 'document':
            result = extract_document(Path(body['pdf_path']), settings, save,
                                      budget_seconds=body['budget_seconds'])
        else:
            evidence = snapshot(Path(body['pdf_path']), body['page'], body.get('crop'))
            save('evidence.json', evidence)
            result = extract(evidence, body['table'], settings,
                             checkpoint=lambda data: save('diagnostics.json', data))
        save('result.json', result)
        print(json.dumps({'ok': True}))
    except ExtractionError as e:
        print(json.dumps({'ok': False, 'reason': e.reason}))
    except Exception:
        print(json.dumps({'ok': False, 'reason': 'worker_error'}))


if __name__ == '__main__':
    main()
