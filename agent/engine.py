"""Runs the MeTTa rules in /rules over facts supplied by the service layer.

Each query gets a fresh MeTTa runner: the rule files are loaded, the facts
for that one request are added, and the query is evaluated. Nothing carries
over between requests, so the facts a decision was made on are exactly the
facts that were passed in (and can be shown to the user).
"""
from __future__ import annotations

import threading
from pathlib import Path
from typing import Any, Iterable

from hyperon import AtomKind, MeTTa

RULES_DIR = Path(__file__).resolve().parent.parent / "rules"
RULE_FILES = (
    "lib.metta",
    "deal_schema.metta",
    "validation.metta",
    "payout.metta",
    "classification.metta",
)

# hyperon runners are not documented as thread-safe; FastAPI runs sync
# handlers on a thread pool, so queries are serialised.
_LOCK = threading.Lock()


class EngineError(RuntimeError):
    """The rules produced an Error atom or an unexpected result shape."""


class Symbol(str):
    """A MeTTa symbol (as opposed to a MeTTa string) returned to Python."""


def quote(text: str) -> str:
    """A MeTTa string literal for arbitrary text."""
    cleaned = str(text).replace("\r", " ").replace("\n", " ")
    return '"' + cleaned.replace("\\", "\\\\").replace('"', '\\"') + '"'


def number(value: int | float) -> str:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"not a number: {value!r}")
    return repr(value)


def fact(*parts: str) -> str:
    return "(" + " ".join(parts) + ")"


def to_python(atom) -> Any:
    kind = atom.get_metatype()
    if kind == AtomKind.EXPR:
        return [to_python(child) for child in atom.get_children()]
    if kind == AtomKind.SYMBOL:
        name = atom.get_name()
        return None if name == "none" else Symbol(name)
    if kind == AtomKind.GROUNDED:
        return atom.get_object().value
    raise EngineError(f"unbound variable in result: {atom}")


def _find_error(value: Any) -> bool:
    if isinstance(value, list):
        if value and value[0] == "Error" and isinstance(value[0], Symbol):
            return True
        return any(_find_error(v) for v in value)
    return False


def pairs(value: list) -> dict[str, Any]:
    """((key value) ...) -> {"key": value}."""
    out: dict[str, Any] = {}
    for item in value:
        if not (isinstance(item, list) and len(item) == 2):
            raise EngineError(f"expected (key value), got {item!r}")
        out[str(item[0])] = item[1]
    return out


class Engine:
    def __init__(self, rules_dir: Path = RULES_DIR) -> None:
        self.rules_text = "\n".join(
            (rules_dir / name).read_text(encoding="utf-8") for name in RULE_FILES
        )

    def query(self, facts: Iterable[str], expression: str) -> list[Any]:
        """Evaluate `expression` over the rules plus `facts`; one item per result."""
        facts_text = "\n".join(facts)
        with _LOCK:
            runner = MeTTa()
            runner.run(self.rules_text)
            runner.run(facts_text)
            results = runner.run("!" + expression)
        if len(results) != 1:
            raise EngineError(f"expected one result set for {expression}, got {len(results)}")
        values = [to_python(atom) for atom in results[0]]
        for value in values:
            if _find_error(value):
                raise EngineError(f"rule error while evaluating {expression}: {value!r}")
        return values

    def query_one(self, facts: Iterable[str], expression: str) -> Any:
        values = self.query(facts, expression)
        if len(values) != 1:
            raise EngineError(f"expected exactly one result for {expression}, got {values!r}")
        return values[0]

    def rule_docs(self) -> dict[str, dict[str, str]]:
        rows = self.query_one([], "(collapse (match &self (rule-doc $id $stage $text) ($id $stage $text)))")
        return {str(r[0]): {"stage": str(r[1]), "statement": r[2]} for r in rows}
