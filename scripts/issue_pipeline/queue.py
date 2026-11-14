"""Parse a batch queue. Model slugs mirror the batch-solve prompt."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field

from .batch_config import (
    DEFAULT_ALTERNATE_SLUG,
    PREFIX_TO_SLUG,
    resolve_batch_config,
    validate_worker_slug,
)
from .models import GraphError

DEFAULT_ALTERNATE = DEFAULT_ALTERNATE_SLUG
MAX_CONCURRENCY = 32

_HEADER = re.compile(
    r"^(Concurrency|Worker mix|Alternate slug|Review model|Max fix rounds|"
    r"Implementation model|Escalation|Escalation premium|Escalation model|"
    r"Escalation max batch|Max premium escalations per batch|"
    r"Max premium attempts per issue|Composer attempts before escalation)\s*:\s*(.+)$",
    re.I,
)


@dataclass
class QueueItem:
    number: int
    hard_dependencies: list[int] = field(default_factory=list)
    prefix: str | None = None
    no_expand: bool = False
    model_slug: str | None = None
    issue_model: str | None = None
    escalation_disabled: bool | None = None
    source: str = ""


@dataclass
class ParsedQueue:
    items: list[QueueItem]
    concurrency: int | None
    fallback: str | None
    worker_mix: str
    alternate_slug: str
    review_model: str
    review_model_slug: str | None
    max_fix_rounds: int | None
    implementation_model: str | None = None
    escalation_enabled: bool | None = None
    escalation_premium: str | None = None
    escalation_max_batch: int | None = None
    escalation_max_per_issue: int | None = None
    composer_attempts_before_escalation: int | None = None


def parse_queue(text: str, env: dict[str, str] | None = None) -> ParsedQueue:
    environment = os.environ if env is None else env
    concurrency_header: int | None = None
    worker_mix = "cursor-only"
    alternate = environment.get("PIPELINE_ALTERNATE_SLUG") or DEFAULT_ALTERNATE
    review_model = "same"
    review_model_slug: str | None = None
    max_fix: int | None = None
    implementation_model: str | None = None
    escalation_enabled: bool | None = None
    escalation_premium: str | None = None
    escalation_max_batch: int | None = None
    escalation_max_per_issue: int | None = None
    composer_attempts: int | None = None
    items: list[QueueItem] = []

    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        header = _HEADER.match(line)
        if header:
            name = header.group(1).lower()
            value = header.group(2).strip()
            if name == "concurrency":
                concurrency_header = _positive_int(value, "Concurrency")
            elif name == "worker mix":
                worker_mix = value.lower()
                if worker_mix not in {"cursor-only", "balanced", "other-heavy"}:
                    raise GraphError(f"unsupported worker mix: {value}")
            elif name == "alternate slug":
                alternate_slug, _ = validate_worker_slug(value, label="Alternate slug")
                alternate = alternate_slug
            elif name == "review model":
                lowered = value.lower()
                if lowered in {"same", "inherit", "default"}:
                    review_model = "same"
                elif lowered == "alternate":
                    review_model = "alternate"
                else:
                    review_model = "explicit"
                    review_model_slug, _ = validate_worker_slug(value, label="Review model")
            elif name == "implementation model":
                implementation_model, _ = validate_worker_slug(value, label="Implementation model")
            elif name == "max fix rounds":
                max_fix = _positive_int(value, "Max fix rounds")
            elif name in {"escalation", "escalation premium", "escalation model"}:
                if name == "escalation":
                    escalation_enabled = _parse_bool_header(value, "Escalation")
                elif name == "escalation premium":
                    escalation_premium = value.strip()
                else:
                    escalation_premium, _ = validate_worker_slug(value, label="Escalation model")
            elif name in {"escalation max batch", "max premium escalations per batch"}:
                escalation_max_batch = _non_negative_int(
                    value, "Max premium escalations per batch"
                )
            elif name == "max premium attempts per issue":
                escalation_max_per_issue = _non_negative_int(
                    value, "Max premium attempts per issue"
                )
            elif name == "composer attempts before escalation":
                composer_attempts = _non_negative_int(
                    value, "Composer attempts before escalation"
                )
            continue
        items.append(parse_issue_line(line))

    if not items:
        raise GraphError("queue has no issues")
    concurrency, fallback = resolve_concurrency(concurrency_header, environment)
    if max_fix is not None and max_fix < 1:
        raise GraphError("max fix rounds must be at least 1")

    review_slug = review_model_slug
    if review_model == "alternate":
        review_slug, _ = validate_worker_slug(alternate, label="Review model")

    return ParsedQueue(
        items=items,
        concurrency=concurrency,
        fallback=fallback,
        worker_mix=worker_mix,
        alternate_slug=alternate,
        review_model=review_model,
        review_model_slug=review_slug,
        max_fix_rounds=max_fix,
        implementation_model=implementation_model,
        escalation_enabled=escalation_enabled,
        escalation_premium=escalation_premium,
        escalation_max_batch=escalation_max_batch,
        escalation_max_per_issue=escalation_max_per_issue,
        composer_attempts_before_escalation=composer_attempts,
    )


def parse_issue_line(line: str) -> QueueItem:
    rest = line.strip()
    prefix = None
    no_expand = False

    matched = re.match(r"(?i)^(grok|opus|sonnet|gpt|other):(\d+)\b(.*)$", rest)
    if matched:
        prefix = matched.group(1).lower()
        number = int(matched.group(2))
        rest = matched.group(3).strip()
    else:
        matched = re.match(r"(?i)^no-expand:(\d+)\b(.*)$", rest)
        if matched:
            no_expand = True
            number = int(matched.group(1))
            rest = matched.group(2).strip()
        else:
            matched = re.match(r"^(\d+)\b(.*)$", rest)
            if not matched:
                raise GraphError(f"cannot parse queue line: {line}")
            number = int(matched.group(1))
            rest = matched.group(2).strip()
            prefixed = re.match(r"(?i)^(grok|opus|sonnet|gpt|other)\b(.*)$", rest)
            if prefixed:
                prefix = prefixed.group(1).lower()
                rest = prefixed.group(2).strip()
            elif re.match(r"(?i)^no-expand\b", rest):
                no_expand = True
                rest = re.sub(r"(?i)^no-expand\b", "", rest).strip()

    dependencies, issue_model, escalation_disabled = _parse_issue_annotations(rest, line)
    return QueueItem(
        number=number,
        hard_dependencies=dependencies,
        prefix=prefix,
        no_expand=no_expand,
        issue_model=issue_model,
        escalation_disabled=escalation_disabled,
        source=line.strip(),
    )


def _parse_issue_annotations(rest: str, line: str) -> tuple[list[int], str | None, bool | None]:
    if not rest:
        return [], None, None
    if "(" not in rest:
        annotation = re.match(r"(?i)^\(?after\s+([0-9,\s]+)\)?$", rest)
        if annotation is None:
            annotation = re.match(r"(?i)^depends(?:\s+on)?:\s*([0-9,\s]+)$", rest)
        if annotation is None:
            raise GraphError(f"cannot parse queue annotation: {line}")
        deps = [int(value) for value in re.findall(r"\d+", annotation.group(1))]
        return deps, None, None

    dependencies: list[int] = []
    issue_model: str | None = None
    escalation_disabled: bool | None = None
    for block in re.findall(r"\(([^)]+)\)", rest):
        if re.match(r"(?i)^after\b", block) or re.match(r"(?i)^depends", block):
            dependencies.extend(int(value) for value in re.findall(r"\d+", block))
            continue
        model_match = re.match(r"(?i)^model:\s*(.+)$", block)
        if model_match:
            if issue_model is not None:
                raise GraphError(f"duplicate model override on line: {line}")
            issue_model = model_match.group(1).strip()
            continue
        esc_match = re.match(r"(?i)^escalation:\s*(.+)$", block)
        if esc_match:
            flag = esc_match.group(1).strip().lower()
            if flag == "disabled":
                escalation_disabled = True
            elif flag in {"enabled", "on", "true"}:
                escalation_disabled = False
            else:
                raise GraphError(f"unsupported escalation annotation: ({block})")
            continue
        raise GraphError(f"unknown queue annotation: ({block})")
    return dependencies, issue_model, escalation_disabled


def assign_models(items: list[QueueItem], parsed: ParsedQueue) -> None:
    """Set model_slug after epic expansion so worker-mix positions match the final queue."""

    for index, item in enumerate(items, start=1):
        if item.issue_model:
            slug, _ = validate_worker_slug(item.issue_model, label=f"Issue #{item.number} model")
            item.model_slug = slug
            continue
        if item.prefix == "other":
            slug, _ = validate_worker_slug(parsed.alternate_slug, label="Alternate slug")
            item.model_slug = slug
            continue
        if item.prefix:
            slug = PREFIX_TO_SLUG.get(item.prefix)
            if slug is None:
                raise GraphError(f"unsupported model prefix: {item.prefix}")
            item.model_slug = slug
            continue
        if parsed.worker_mix == "other-heavy":
            slug, _ = validate_worker_slug(parsed.alternate_slug, label="Worker mix")
            item.model_slug = slug
        elif parsed.worker_mix == "balanced" and index % 2 == 0:
            slug, _ = validate_worker_slug(parsed.alternate_slug, label="Worker mix")
            item.model_slug = slug
        else:
            item.model_slug = None


def resolve_concurrency(
    header: int | None,
    env: dict[str, str],
) -> tuple[int, str | None]:
    if env.get("PIPELINE_FORCE_SEQUENTIAL") == "1":
        return 1, "sequential"
    if header is not None:
        value = header
    elif env.get("PIPELINE_MAX_ACTIVE"):
        value = _positive_int(env["PIPELINE_MAX_ACTIVE"], "PIPELINE_MAX_ACTIVE")
    else:
        value = 3
    if value < 1 or value > MAX_CONCURRENCY:
        raise GraphError(f"concurrency must be between 1 and {MAX_CONCURRENCY}")
    return value, None


def _parse_bool_header(value: str, label: str) -> bool:
    lowered = value.lower()
    if lowered in {"on", "true", "yes", "1", "enabled", "automatic", "auto"}:
        return True
    if lowered in {"off", "false", "no", "0", "disabled"}:
        return False
    raise GraphError(f"unsupported {label} value: {value}")


def _positive_int(value: str, label: str) -> int:
    try:
        parsed = int(value)
    except ValueError as exc:
        raise GraphError(f"{label} must be an integer") from exc
    if parsed < 1:
        raise GraphError(f"{label} must be >= 1")
    return parsed


def _non_negative_int(value: str, label: str) -> int:
    try:
        parsed = int(value)
    except ValueError as exc:
        raise GraphError(f"{label} must be an integer") from exc
    if parsed < 0:
        raise GraphError(f"{label} must be >= 0")
    return parsed
