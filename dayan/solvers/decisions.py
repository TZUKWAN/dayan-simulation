"""Credential-free decision boundaries shared by host and isolated worker."""
import math

try:
    from .codec import digest, encode
except ImportError:  # Fixed isolated image, not a generated-model import.
    from codec import digest, encode


def validate_requests(requests):
    if not isinstance(requests, list):
        raise ValueError('decision_requests必须返回决策批次列表')
    seen = set()
    for row in requests:
        if (not isinstance(row, dict) or set(row) != {'id', 'actor_ids', 'prompt'}
                or not isinstance(row['id'], str) or not row['id'] or row['id'] in seen
                or not isinstance(row['prompt'], str) or not row['prompt'].strip()
                or not isinstance(row['actor_ids'], list) or not row['actor_ids']
                or any(not isinstance(ident, str) or not ident for ident in row['actor_ids'])
                or len(set(row['actor_ids'])) != len(row['actor_ids'])):
            raise ValueError('决策批次须有唯一id、非空actor_ids和实际prompt')
        seen.add(row['id'])
    encode(requests)  # Reject unsupported/non-finite value trees.
    return requests


def describe(fn, state, parameters, inputs, rng, step, dt, policy):
    """The request function is pure and cannot advance state or randomness."""
    before = encode({'state': state, 'parameters': parameters, 'inputs': inputs, 'rng': rng.bit_generator.state})
    requests = validate_requests(fn(state, parameters, inputs, step * dt))
    after = encode({'state': state, 'parameters': parameters, 'inputs': inputs, 'rng': rng.bit_generator.state})
    if digest(before) != digest(after):
        raise ValueError('decision_requests修改了状态、随机流或只读输入')
    body = {'step': step, 'time': step * dt, 'requests': requests,
            'state_sha256': digest(before), 'policy_sha256': digest(policy)}
    return {**body, 'key': digest(body)}


def verify_bundle(bundle, descriptor):
    if (not isinstance(bundle, dict) or set(bundle) != {'key', 'results'}
            or bundle['key'] != descriptor['key'] or not isinstance(bundle['results'], dict)
            or set(bundle['results']) != {row['id'] for row in descriptor['requests']}):
        raise ValueError('缺少同一状态边界的真实决策结果，或结果身份不一致')
    encode(bundle['results'])
    return bundle['results']
