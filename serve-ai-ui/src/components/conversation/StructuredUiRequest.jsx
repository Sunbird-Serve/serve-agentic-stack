/**
 * Renders a generic UiRequest structured turn:
 * - mode=collect: FIELD_WIDGETS + FIELD_VALIDATORS + submit
 * - mode=present: CONTENT_BLOCKS + optional actions (no field submit)
 *
 * Growth model: register a new `input` → widget + validator. Field catalog only
 * picks the input key; it does not re-implement checks per form.
 */
import { useState } from 'react';

function BooleanField({ field, value, onChange, disabled }) {
  return (
    <div className="flex gap-2">
      {[
        { label: 'Yes', v: true },
        { label: 'No', v: false },
      ].map((opt) => {
        const selected = value === opt.v;
        return (
          <button
            key={opt.label}
            type="button"
            disabled={disabled}
            onClick={() => onChange(opt.v)}
            className={`px-3 py-1.5 text-sm rounded-lg border transition-colors ${
              selected
                ? 'bg-slate-900 text-white border-slate-900'
                : 'bg-white text-slate-700 border-slate-200 hover:border-slate-400'
            }`}
          >
            {opt.label}
          </button>
        );
      })}
    </div>
  );
}

function TextField({ field, value, onChange, disabled, invalid = false }) {
  const type =
    field.input === 'email' ? 'email' : field.input === 'tel' ? 'tel' : 'text';
  return (
    <input
      type={type}
      value={value ?? ''}
      disabled={disabled}
      onChange={(e) => onChange(e.target.value)}
      aria-invalid={invalid || undefined}
      className={`w-full rounded-lg border px-3 py-2 text-sm text-slate-900 focus:outline-none focus:ring-2 ${
        invalid
          ? 'border-red-400 focus:ring-red-200'
          : 'border-slate-200 focus:ring-slate-300'
      }`}
      autoComplete={field.input === 'email' ? 'email' : field.input === 'tel' ? 'tel' : 'name'}
      placeholder={field.validation?.hint || undefined}
    />
  );
}

function TextareaField({ field, value, onChange, disabled, invalid = false }) {
  return (
    <textarea
      value={value ?? ''}
      disabled={disabled}
      onChange={(e) => onChange(e.target.value)}
      rows={3}
      aria-invalid={invalid || undefined}
      className={`w-full rounded-lg border px-3 py-2 text-sm text-slate-900 focus:outline-none focus:ring-2 ${
        invalid
          ? 'border-red-400 focus:ring-red-200'
          : 'border-slate-200 focus:ring-slate-300'
      }`}
      placeholder={field.validation?.hint || undefined}
    />
  );
}

function UnsupportedField({ field }) {
  return (
    <p className="text-xs text-amber-700">
      Unsupported field type “{field.input}” — please reply in chat instead.
    </p>
  );
}

/** Registry: add new inputs here without changing the orchestrator protocol. */
export const FIELD_WIDGETS = {
  boolean: BooleanField,
  text: TextField,
  email: TextField,
  tel: TextField,
  textarea: TextareaField,
};

// ── Input-type validators (return error string or null) ─────────────────────
// Keep in sync with onboarding_logic ProfileExtractor email/phone rules.

function isBlank(value) {
  return value === undefined || value === null || String(value).trim() === '';
}

function validateRequired(field, value) {
  if (!field.required) return null;
  if (field.input === 'boolean') {
    return value === true || value === false ? null : `Please answer: ${field.label}`;
  }
  return isBlank(value) ? `Please fill in: ${field.label}` : null;
}

function validateEmail(_field, value) {
  const email = String(value || '').trim();
  if (!email) return null; // required handled separately
  if (email.length > 254 || (email.match(/@/g) || []).length !== 1) {
    return 'Enter a valid email address';
  }
  const [local, domain] = email.split('@');
  if (!local || local.length > 64 || local.startsWith('.') || local.endsWith('.') || local.includes('..')) {
    return 'Enter a valid email address';
  }
  if (!/^[a-zA-Z0-9._%+-]+$/.test(local)) {
    return 'Enter a valid email address';
  }
  if (!domain || domain.length > 253 || domain.startsWith('.') || domain.endsWith('.') || domain.includes('..')) {
    return 'Enter a valid email address';
  }
  const labels = domain.split('.');
  if (labels.length < 2) {
    return 'Enter a valid email address (include domain, e.g. name@gmail.com)';
  }
  for (const label of labels) {
    if (!label || label.length > 63 || label.startsWith('-') || label.endsWith('-')) {
      return 'Enter a valid email address';
    }
    if (!/^[a-zA-Z0-9-]+$/.test(label)) {
      return 'Enter a valid email address';
    }
  }
  const tld = labels[labels.length - 1];
  if (!/^[a-zA-Z]{2,24}$/.test(tld)) {
    return 'Enter a valid email address';
  }
  return null;
}

function isPlausibleIndianMobile(core) {
  if (!/^\d{10}$/.test(core)) return false;
  if (!['6', '7', '8', '9'].includes(core[0])) return false;
  if (new Set(core).size === 1) return false;
  return true;
}

function validateTel(_field, value) {
  const raw = String(value || '').trim();
  if (!raw) return null;
  const hasPlus = raw.startsWith('+');
  const digits = raw.replace(/\D/g, '');

  let core = null;
  if (hasPlus) {
    if (!digits.startsWith('91') || digits.length !== 12) {
      return 'Enter a 10-digit Indian mobile number';
    }
    core = digits.slice(2);
  } else if (digits.length === 12 && digits.startsWith('91')) {
    core = digits.slice(2);
  } else if (digits.length === 10) {
    core = digits;
  } else {
    return 'Enter a 10-digit Indian mobile number';
  }

  if (!isPlausibleIndianMobile(core)) {
    return 'Enter a valid 10-digit Indian mobile (starts with 6–9)';
  }
  return null;
}

function validateText(field, value) {
  if (isBlank(value)) return null;
  const text = String(value).trim();
  const v = field.validation || {};
  if (typeof v.maxLength === 'number' && text.length > v.maxLength) {
    return `${field.label} is too long`;
  }
  if (typeof v.minLength === 'number' && text.length < v.minLength) {
    return `${field.label} must be at least ${v.minLength} characters`;
  }
  // Person-name style (full_name): first + last, letter words — matches MCP/agent
  if (typeof v.minWords === 'number') {
    const words = text.split(/\s+/).filter(Boolean);
    if (words.length < v.minWords) {
      return 'Please enter your first and last name';
    }
    const minW = typeof v.minWordLength === 'number' ? v.minWordLength : 2;
    const maxW = typeof v.maxWordLength === 'number' ? v.maxWordLength : 20;
    const wordRe = /^[A-Za-z]+(?:['-][A-Za-z]+)*$/;
    for (const word of words) {
      if (word.length < minW || word.length > maxW || !wordRe.test(word)) {
        return 'Use a real first and last name (letters only)';
      }
    }
  }
  return null;
}

function validateBoolean(_field, _value) {
  return null; // required handled separately
}

/**
 * input → validate(field, value) => error string | null
 * Optional field.validation can refine (minLength, hint, …).
 */
export const FIELD_VALIDATORS = {
  boolean: validateBoolean,
  text: validateText,
  email: validateEmail,
  tel: validateTel,
  textarea: validateText,
};

/** Run required + type validator for one field. */
export function validateField(field, value) {
  const requiredError = validateRequired(field, value);
  if (requiredError) return requiredError;
  if (field.input === 'boolean') return null;
  if (isBlank(value)) return null;
  const typeValidator = FIELD_VALIDATORS[field.input];
  if (!typeValidator) return null;
  return typeValidator(field, value);
}

/** Validate all fields; returns { name: error } (empty if valid). */
export function validateFields(fields, values) {
  const errors = {};
  for (const field of fields || []) {
    const err = validateField(field, values?.[field.name]);
    if (err) errors[field.name] = err;
  }
  return errors;
}

function TextBlock({ block }) {
  if (!block?.text) return null;
  return <p className="text-sm text-slate-800 whitespace-pre-wrap">{block.text}</p>;
}

function VideoBlock({ block }) {
  if (!block?.url) return null;
  return (
    <div className="rounded-lg overflow-hidden">
      <video
        src={block.url}
        controls
        className="w-full max-w-[300px] rounded-lg"
        preload="metadata"
      />
      {block.caption ? (
        <p className="text-xs text-slate-500 mt-1">{block.caption}</p>
      ) : null}
    </div>
  );
}

function UnsupportedBlock({ block }) {
  return (
    <p className="text-xs text-amber-700">
      Unsupported content block “{block?.type}”.
    </p>
  );
}

/** Registry: present-mode blocks (info / media). */
export const CONTENT_BLOCKS = {
  text: TextBlock,
  video: VideoBlock,
};

export function StructuredUiRequest({
  uiRequest,
  disabled = false,
  onSubmit,
  submittedValues = null,
}) {
  const mode = uiRequest?.mode || (uiRequest?.fields?.length ? 'collect' : 'present');
  const fields = uiRequest?.fields || [];
  const blocks = uiRequest?.blocks || [];
  const actions = uiRequest?.actions || [];

  const [values, setValues] = useState(() => {
    const initial = {};
    fields.forEach((f) => {
      if (submittedValues && submittedValues[f.name] !== undefined) {
        initial[f.name] = submittedValues[f.name];
      } else if (f.value !== undefined && f.value !== null) {
        initial[f.name] = f.value;
      } else {
        initial[f.name] = f.input === 'boolean' ? null : '';
      }
    });
    return initial;
  });
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState('');
  const [fieldErrors, setFieldErrors] = useState({});

  if (!uiRequest) return null;
  const isCollect = mode === 'collect' && fields.length > 0;
  const isPresent = mode === 'present' || (!isCollect && (blocks.length > 0 || actions.length > 0));
  if (!isCollect && !isPresent) return null;

  const setField = (name, value) => {
    setValues((prev) => ({ ...prev, [name]: value }));
    setError('');
    setFieldErrors((prev) => {
      if (!prev[name]) return prev;
      const next = { ...prev };
      delete next[name];
      return next;
    });
  };

  const runSubmit = async (payload) => {
    if (disabled || submitting) return;
    setSubmitting(true);
    setError('');
    try {
      await onSubmit?.(payload);
    } catch (err) {
      console.error(err);
      setError('Could not submit. Please try again.');
    } finally {
      setSubmitting(false);
    }
  };

  const handleSubmit = async (e) => {
    e.preventDefault();
    if (!isCollect) return;

    const errors = validateFields(fields, values);
    if (Object.keys(errors).length > 0) {
      setFieldErrors(errors);
      setError('Please fix the highlighted fields.');
      return;
    }
    setFieldErrors({});
    await runSubmit(values);
  };

  const handleAction = async (actionId) => {
    await runSubmit({ _action: actionId });
  };

  return (
    <div
      className={`mt-3 w-full max-w-md rounded-xl border border-slate-200 bg-white p-4 shadow-sm ${
        disabled ? 'opacity-60 pointer-events-none' : ''
      }`}
    >
      {uiRequest.title && (
        <p className="text-sm font-semibold text-slate-900 mb-3">{uiRequest.title}</p>
      )}
      {uiRequest.description && (
        <p className="text-xs text-slate-600 mb-3 whitespace-pre-wrap">{uiRequest.description}</p>
      )}

      {blocks.length > 0 && (
        <div className="space-y-3 mb-3">
          {blocks.map((block, i) => {
            const Widget = CONTENT_BLOCKS[block.type] || UnsupportedBlock;
            return <Widget key={`${block.type}-${i}`} block={block} />;
          })}
        </div>
      )}

      {isCollect && (
        <form onSubmit={handleSubmit} noValidate>
          <div className="space-y-3">
            {fields.map((field) => {
              const Widget = FIELD_WIDGETS[field.input] || UnsupportedField;
              const fieldError = fieldErrors[field.name];
              return (
                <div key={field.name}>
                  <label className="block text-xs font-medium text-slate-700 mb-1.5">
                    {field.label}
                    {field.required ? <span className="text-red-500"> *</span> : null}
                  </label>
                  <Widget
                    field={field}
                    value={values[field.name]}
                    onChange={(v) => setField(field.name, v)}
                    disabled={disabled || submitting}
                    invalid={Boolean(fieldError)}
                  />
                  {fieldError ? (
                    <p className="mt-1 text-xs text-red-600">{fieldError}</p>
                  ) : null}
                </div>
              );
            })}
          </div>

          {error && <p className="mt-2 text-xs text-red-600">{error}</p>}

          <button
            type="submit"
            disabled={disabled || submitting}
            className="mt-4 w-full rounded-lg bg-slate-900 text-white text-sm font-medium py-2 hover:bg-slate-800 disabled:opacity-50"
          >
            {disabled ? 'Submitted' : submitting ? 'Submitting…' : 'Submit'}
          </button>
        </form>
      )}

      {isPresent && actions.length > 0 && (
        <div className="flex flex-col gap-2 mt-2">
          {error && <p className="text-xs text-red-600">{error}</p>}
          {actions.map((action) => {
            const chosenId = submittedValues?._action;
            if (disabled && chosenId && action.id !== chosenId) {
              return null;
            }
            return (
              <button
                key={action.id}
                type="button"
                disabled={disabled || submitting}
                onClick={() => handleAction(action.id)}
                className="w-full rounded-lg bg-slate-900 text-white text-sm font-medium py-2 hover:bg-slate-800 disabled:opacity-50"
              >
                {submitting && !disabled ? 'Continuing…' : action.label}
              </button>
            );
          })}
        </div>
      )}
    </div>
  );
}

export default StructuredUiRequest;
