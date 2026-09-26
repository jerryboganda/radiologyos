"""A deliberately tiny, strict templater for prompt ``user_template`` fields (ADR 0032).

Placeholders are ``{{name}}`` (lower-case identifiers). Rendering is one pass
over the template: a value is inserted verbatim and is never itself expanded,
so user or source text containing ``{{...}}`` cannot inject another variable.
Every placeholder must be supplied, no extra value may be passed, and values
must be strings — mistakes fail loudly instead of sending a malformed prompt.
There are no expressions, filters, loops, attribute lookups, or escapes.
"""

from __future__ import annotations

import re
from collections.abc import Mapping

PLACEHOLDER = re.compile(r"\{\{([a-z][a-z0-9_]*)\}\}")
_BRACES = re.compile(r"\{\{|\}\}")


class TemplateError(ValueError):
    """A template or its values do not match; the message names variables only."""


def placeholders(template: str) -> frozenset[str]:
    """Variable names used by ``template``; malformed ``{{`` / ``}}`` raise."""
    stripped = PLACEHOLDER.sub("", template)
    if _BRACES.search(stripped):
        raise TemplateError("template has a malformed placeholder")
    return frozenset(PLACEHOLDER.findall(template))


def render(template: str, values: Mapping[str, str]) -> str:
    needed = placeholders(template)
    missing = needed - values.keys()
    extra = values.keys() - needed
    if missing or extra:
        raise TemplateError(f"template variables mismatch: missing={sorted(missing)} "
                            f"unexpected={sorted(extra)}")
    for name, value in values.items():
        if not isinstance(value, str):
            raise TemplateError(f"template value {name} is not a string")
    return PLACEHOLDER.sub(lambda match: values[match.group(1)], template)
