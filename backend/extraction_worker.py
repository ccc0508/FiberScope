"""Isolated, bounded PDF parsing and model process; safe JSON output only."""
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))


def main():
    from literature_extraction import snapshot, extract, configuration, ExtractionError
    from literature_rag.config import Settings
    body = json.loads(sys.stdin.read())
    artifact = Path(body['artifact_dir']).resolve()

    def save(name, value):
        temp = artifact / (name + '.tmp')
        temp.write_text(json.dumps(value, ensure_ascii=False), encoding='utf-8')
        temp.replace(artifact / name)

    try:
        settings = Settings(_env_file=Path(__file__).resolve().parent / '.env.literature')
        save('configuration.json', configuration(settings))
        evidence = snapshot(Path(body['pdf_path']), body['page'], body.get('crop'))
        save('evidence.json', evidence)
        if not settings.llm_api_key or not settings.llm_model or settings.llm_provider not in ('deepseek', 'openai'):
            raise ExtractionError('missing_configuration')
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
