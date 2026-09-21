"""Resolve the same complete local model for discovery and ASR loading."""
import os
from pathlib import Path


def _hub_cache():
    configured = os.environ.get('HF_HUB_CACHE') or os.environ.get('HUGGINGFACE_HUB_CACHE')
    if configured:
        return Path(configured)
    hf_home = os.environ.get('HF_HOME')
    if hf_home:
        return Path(hf_home) / 'hub'
    cache_home = Path(os.environ.get('XDG_CACHE_HOME') or (Path.home() / '.cache'))
    return cache_home / 'huggingface' / 'hub'


def _complete_model(candidate):
    required = ('model.bin', 'config.json', 'tokenizer.json')
    if not all((candidate / name).is_file() and (candidate / name).stat().st_size > 0 for name in required):
        return False
    # Older converted models use vocabulary.txt; large-v3 uses vocabulary.json.
    return any((candidate / name).is_file() and (candidate / name).stat().st_size > 0
               for name in ('vocabulary.txt', 'vocabulary.json'))


def resolve_local_model(root, model):
    candidates = [Path(root) / 'engines' / 'faster-whisper' / model]
    for hub in (Path(root) / 'engines' / 'faster-whisper' / 'cache', _hub_cache()):
        repo = hub / f'models--Systran--faster-whisper-{model}'
        ref = repo / 'refs' / 'main'
        if ref.is_file():
            candidates.append(repo / 'snapshots' / ref.read_text(encoding='utf-8').strip())
        candidates.extend(sorted((repo / 'snapshots').glob('*'), reverse=True))
    for candidate in candidates:
        if _complete_model(candidate):
            return candidate.resolve()
    return None
