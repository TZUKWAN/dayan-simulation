"""Recover narrowly identified bracket defects without editing any values."""
import hashlib
import json

from ..llm_client import json_object


def _unique_pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('格式恢复不能覆盖重复键的值')
        result[key] = value
    return result


def stage_object(raw):
    try:
        return json_object(raw, whole=True), None
    except ValueError as original:
        text = raw.strip().removeprefix('\ufeff')
        if text.startswith(('```json\n', '```\n')) and text.endswith('```'):
            text = text.split('\n', 1)[1][:-3].strip()
        stack, result, edits = [], [], []
        quoted = escaped = root_closed = False
        for position, char in enumerate(text):
            if root_closed and not char.isspace():
                tail = text[position:]
                if edits and all(item in '}] \t\r\n' for item in tail):
                    edits.extend({'position': position + offset, 'delete': item}
                                 for offset, item in enumerate(tail) if not item.isspace())
                    break
                raise original
            if quoted:
                if escaped:
                    escaped = False
                elif char == '\\':
                    escaped = True
                elif char == '"':
                    quoted = False
            elif char == '"':
                quoted = True
            elif char in '{[':
                stack.append(char)
            elif char in '}]':
                expected = '{' if char == '}' else '['
                if char == ']' and len(stack) >= 2 and stack[-2:] == ['[', '{']:
                    result.append('}')
                    stack.pop()
                    edits.append({'position': position, 'insert': '}'})
                if not stack or stack.pop() != expected:
                    raise original
                root_closed = not stack
            result.append(char)
        # Incomplete strings, truncated output and arbitrary prose remain errors.
        if not edits or stack or quoted:
            raise original
        normalized = ''.join(result)
        try:
            value = json.loads(normalized, object_pairs_hook=_unique_pairs)
            if not isinstance(value, dict):
                raise ValueError('Expected one object')
        except ValueError:
            raise original
        kind = ('missing_object_close_before_array_and_redundant_tail'
                if any('delete' in edit for edit in edits) else 'missing_object_close_before_array')
        evidence = {'kind': kind, 'edits': edits,
                    'position_basis': 'wrapper-free text; no value characters changed',
                    'original_sha256': hashlib.sha256(raw.encode()).hexdigest(),
                    'normalized_sha256': hashlib.sha256(normalized.encode()).hexdigest(),
                    'original_error': str(original)}
        return value, evidence
