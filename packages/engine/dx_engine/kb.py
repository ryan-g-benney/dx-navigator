"""Knowledge-base schema and loader.

Pure parsing and validation. No framework imports, no network, no I/O beyond
reading the YAML files handed to it.

Design notes live in docs/. The two that shape this file:
  - Weights are all 1 today. The field exists so likelihoods become a data
    change, not an engine change (docs/phase-0-simplified-engine.md §5).
  - Every clinical assertion carries a source id, and the loader refuses to
    build a KB where one is missing or unresolvable.
"""

from __future__ import annotations

import hashlib
from enum import Enum
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

UNKNOWN = "unknown"

# CKS is third-party content under a separate EULA and is not covered by the
# NICE UK open content licence. Links are fine; copied content is not.
# docs/phase-0-source-investigation.md §2.3
FORBIDDEN_SOURCE_HOSTS = ("cks.nice.org.uk",)


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class SourceType(str, Enum):
    PUBLISHED = "published"
    GUIDELINE = "guideline"
    ESTIMATE = "estimate"


class Modality(str, Enum):
    HISTORY = "history"
    EXAMINATION = "examination"
    POINT_OF_CARE = "point_of_care"
    # `investigation` is deliberately absent. An investigation is an output,
    # not a question -- there is no d-dimer in a 10-minute consultation.
    # docs/phase-0-source-investigation.md, acquisition plan §4.2


class Urgency(str, Enum):
    ROUTINE = "routine"
    URGENT = "urgent"
    SAME_DAY = "same_day"
    EMERGENCY = "emergency"


class Role(str, Enum):
    DISCRIMINATING = "discriminating"
    # Carries no information about the diagnosis but determines urgency or
    # safety-netting. Never selected by the question optimiser.
    DISPOSITION = "disposition"


class Origin(str, Enum):
    HUMAN = "human"
    # Machine-produced candidates live in .workbench/ and are refused here.
    MACHINE_CANDIDATE = "machine_candidate"


class Source(Strict):
    type: SourceType
    title: str
    url: str | None = None
    licence: str | None = None
    attribution: str | None = None
    note: str | None = None

    @model_validator(mode="after")
    def _check(self) -> "Source":
        if self.type is not SourceType.ESTIMATE:
            if not self.url:
                raise ValueError(f"source {self.title!r}: non-estimate needs a url")
            if not self.licence:
                raise ValueError(f"source {self.title!r}: non-estimate needs a licence")
        if self.url:
            for host in FORBIDDEN_SOURCE_HOSTS:
                if host in self.url:
                    raise ValueError(
                        f"source {self.title!r}: {host} content is not licensed for "
                        "reuse. Deep-link only -- do not copy content into data/."
                    )
        return self


class Variable(Strict):
    name: str
    prompt: str
    # Enumerations belong here or in `values`, never in the stem -- the
    # one-concept lint on `prompt` exists to force exactly that.
    hint: str | None = None
    modality: Modality
    role: Role = Role.DISCRIMINATING
    cost: int = Field(default=0, ge=0, le=10)
    values: list[str]

    @field_validator("values")
    @classmethod
    def _mece(cls, v: list[str]) -> list[str]:
        if len(v) < 2:
            raise ValueError("needs at least 2 values")
        if len(set(v)) != len(v):
            raise ValueError("duplicate values")
        if UNKNOWN not in v:
            raise ValueError(f"must include {UNKNOWN!r}")
        return v

    @field_validator("prompt")
    @classmethod
    def _precise(cls, p: str) -> str:
        if not p.endswith("?"):
            raise ValueError("prompt must be a question")
        if len(p.split()) > 15:
            raise ValueError("prompt over 15 words -- split it")
        low = f" {p.lower()} "
        for banned in (" and ", " or ", " perhaps ", " any sort of ", " at all "):
            if banned in low:
                raise ValueError(f"prompt contains {banned.strip()!r} -- one concept per question")
        return p


class Feature(Strict):
    """One condition's expectation for one variable."""

    expect: list[str]
    weight: float = 1.0  # always 1 today; see module docstring
    source: str

    @field_validator("expect")
    @classmethod
    def _nonempty(cls, v: list[str]) -> list[str]:
        if not v:
            raise ValueError("expect cannot be empty")
        if UNKNOWN in v:
            raise ValueError(f"{UNKNOWN!r} is a no-op, never an expectation")
        return v


class Codes(Strict):
    snomed: str | None = None  # backfilled once TRUD access lands
    icd10: str | None = None
    icd11: str | None = None
    icpc2: str | None = None


class Condition(Strict):
    slug: str
    name: str
    parents: list[str] = Field(default_factory=list)  # first == primary, for breadcrumbs
    codes: Codes = Codes()
    urgency: Urgency
    prior: float | None = None  # flat today
    origin: Origin = Origin.HUMAN
    features: dict[str, Feature] = Field(default_factory=dict)
    red_flag_features: list[str] = Field(default_factory=list)

    @property
    def primary_parent(self) -> str | None:
        return self.parents[0] if self.parents else None


class Category(Strict):
    slug: str
    name: str
    parents: list[str] = Field(default_factory=list)


class Emit(Strict):
    kind: Literal["referral", "escalation", "investigation", "safety_net", "must_ask"]
    urgency: Urgency
    text_verbatim: str
    source: str


class Clause(Strict):
    var: str
    op: Literal["==", "!=", ">=", "<=", ">", "<", "in"]
    value: str | int | float | list[str]


class Rule(Strict):
    """Single-shot predicate over the answer set. Never chains, never writes belief.

    docs/phase-0-architecture-position.md §1.
    """

    id: str
    complaints: list[str]
    all_of: list[Clause] = Field(default_factory=list)
    any_of: list[Clause] = Field(default_factory=list)
    # NICE criteria are often "2 or more of the following". any_of alone would
    # fire on one, which over-refers -- safe in direction but not the guideline.
    min_matches: int = Field(default=1, ge=1)
    emit: Emit

    @model_validator(mode="after")
    def _has_condition(self) -> "Rule":
        if not self.all_of and not self.any_of:
            raise ValueError(f"rule {self.id}: no predicate -- would fire always")
        if self.min_matches > max(len(self.any_of), 1):
            raise ValueError(
                f"rule {self.id}: min_matches={self.min_matches} exceeds "
                f"{len(self.any_of)} any_of clauses -- can never fire"
            )
        return self


class KnowledgeBase(Strict):
    sources: dict[str, Source]
    variables: dict[str, Variable]
    categories: dict[str, Category]
    conditions: dict[str, Condition]
    rules: dict[str, Rule]
    version_hash: str

    def node_parents(self, slug: str) -> list[str]:
        if slug in self.conditions:
            return self.conditions[slug].parents
        if slug in self.categories:
            return self.categories[slug].parents
        return []


def _read(path: Path) -> dict:
    with path.open() as fh:
        return yaml.safe_load(fh) or {}


def _merge(target: dict, incoming: dict, key: str, path: Path) -> None:
    for k, v in incoming.items():
        if k in target:
            raise ValueError(f"{path}: duplicate {key} id {k!r}")
        target[k] = v


def load(data_dir: Path) -> KnowledgeBase:
    """Load and validate every YAML file under data_dir. Raises on any problem."""
    files = sorted(p for p in data_dir.rglob("*.yaml"))
    if not files:
        raise ValueError(f"no YAML found under {data_dir}")

    buckets: dict[str, dict] = {
        "sources": {}, "variables": {}, "categories": {}, "conditions": {}, "rules": {},
    }
    hasher = hashlib.sha256()
    for path in files:
        hasher.update(path.relative_to(data_dir).as_posix().encode())
        hasher.update(path.read_bytes())
        doc = _read(path)
        for key in buckets:
            section = doc.get(key)
            if section is None:
                continue
            if isinstance(section, list):
                section = {item["slug" if key in ("conditions", "categories") else "name" if key == "variables" else "id"]: item for item in section}
            _merge(buckets[key], section, key, path)

    return KnowledgeBase(
        sources={k: Source(**v) for k, v in buckets["sources"].items()},
        variables={k: Variable(**({"name": k} | v)) for k, v in buckets["variables"].items()},
        categories={k: Category(**({"slug": k} | v)) for k, v in buckets["categories"].items()},
        conditions={k: Condition(**({"slug": k} | v)) for k, v in buckets["conditions"].items()},
        rules={k: Rule(**({"id": k} | v)) for k, v in buckets["rules"].items()},
        version_hash=hasher.hexdigest()[:16],
    )
