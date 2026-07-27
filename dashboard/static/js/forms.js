/* Bark typed form serialization shared by settings and module actions. */
(function (root, factory) {
    const api = factory();
    if (typeof module === 'object' && module.exports) module.exports = api;
    if (root) root.BarkForms = api;
})(typeof globalThis !== 'undefined' ? globalThis : this, function () {
    'use strict';

    function coerceField(field) {
        const schemaType = field.dataset?.schemaType || field.type || 'string';
        const value = field.value ?? '';

        if (schemaType === 'boolean' || field.type === 'checkbox') {
            return Boolean(field.checked);
        }
        if (schemaType === 'integer') {
            return value === '' ? '' : Number.parseInt(value, 10);
        }
        if (schemaType === 'number') {
            return value === '' ? '' : Number(value);
        }
        if (schemaType === 'array' || schemaType === 'object') {
            if (value.trim() === '') return schemaType === 'array' ? [] : {};
            let parsed;
            try {
                parsed = JSON.parse(value);
            } catch {
                throw new Error(`${field.name} must be a valid JSON ${schemaType}`);
            }
            if (schemaType === 'array' && !Array.isArray(parsed)) {
                throw new Error(`${field.name} must be a valid JSON array`);
            }
            if (schemaType === 'object' && (parsed === null || Array.isArray(parsed) || typeof parsed !== 'object')) {
                throw new Error(`${field.name} must be a valid JSON object`);
            }
            return parsed;
        }
        return value;
    }

    function serializeFields(fields) {
        const data = {};
        for (const field of fields) {
            if (!field.name || field.disabled) continue;
            const value = coerceField(field);
            const separator = field.name.indexOf('__');
            if (separator === -1) {
                data[field.name] = value;
                continue;
            }
            const parent = field.name.slice(0, separator);
            const child = field.name.slice(separator + 2);
            if (!data[parent]) data[parent] = {};
            data[parent][child] = value;
        }
        return data;
    }

    return { coerceField, serializeFields };
});
