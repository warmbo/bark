"""Behavior tests for the dashboard's typed form serializer."""

from __future__ import annotations

import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
FORMS_JS = ROOT / "dashboard" / "static" / "js" / "forms.js"


def test_typed_form_serializer_preserves_false_arrays_numbers_and_nesting():
    script = f"""
const assert = require('node:assert/strict');
const {{ serializeFields }} = require({str(FORMS_JS)!r});
const result = serializeFields([
  {{ name: 'general__enabled', type: 'checkbox', checked: false, value: 'on', dataset: {{ schemaType: 'boolean' }} }},
  {{ name: 'general__roles', type: 'textarea', value: '[\"123\", \"456\"]', dataset: {{ schemaType: 'array' }} }},
  {{ name: 'threshold', type: 'number', value: '7', dataset: {{ schemaType: 'integer' }} }},
]);
assert.deepEqual(result, {{
  general: {{ enabled: false, roles: ['123', '456'] }},
  threshold: 7,
}});
"""
    subprocess.run(["node", "-e", script], check=True, cwd=ROOT)


def test_typed_form_serializer_rejects_invalid_array_json():
    script = f"""
const assert = require('node:assert/strict');
const {{ serializeFields }} = require({str(FORMS_JS)!r});
assert.throws(
  () => serializeFields([
    {{ name: 'roles', type: 'textarea', value: 'not-json', dataset: {{ schemaType: 'array' }} }},
  ]),
  /roles must be a valid JSON array/
);
"""
    subprocess.run(["node", "-e", script], check=True, cwd=ROOT)
