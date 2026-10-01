"""Database-specific query translation from a conceptual boolean structure.

The conceptual query is modelled as an AND of concept groups, each group an OR
of terms (the structure used by the existing Scopus/IEEE/WoS strategies and
by boolean ``search_overrides``). Each renderer emits the syntax the target
API actually parses:

- Semantic Scholar bulk search: ``+`` AND, ``|`` OR, ``"..."`` phrase, ``()`` grouping.
- OpenAlex ``search``: uppercase AND/OR and quoted phrases.
- CORE v3: AND/OR, quoted phrases (date clauses are appended by the connector).
- arXiv: fielded ``all:"term"`` groups joined by AND/OR.
- DBLP: ``|`` OR inside a group, space AND between groups, phrases dash-joined.
- Crossref ``query.bibliographic``: plain keywords (no boolean operators).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field


@dataclass(frozen=True)
class QueryTerm:
    text: str
    phrase: bool = False


@dataclass
class ConceptualQuery:
    groups: list[list[QueryTerm]] = field(default_factory=list)
    # Verbatim text when the source query could not be parsed into groups.
    raw: str | None = None

    @property
    def is_structured(self) -> bool:
        return bool(self.groups) and any(self.groups)

    def render(self) -> str:
        """Canonical, database-neutral string used for ``conceptual_query``."""
        if not self.is_structured:
            return self.raw or ""
        return render_boolean(self)


_TOKEN_RE = re.compile(r'"[^"]*"|\(|\)|[^\s()"]+')

# Field wrappers / clauses that carry no conceptual meaning (date and doc-type
# limits are re-applied natively by each connector).
_STRIP_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\bAND\s+NOT\s+DOCTYPE\s*\(\s*\w+\s*\)", re.IGNORECASE),
    re.compile(r"\bAND\s+NOT\s+DT\s*=\s*\w+", re.IGNORECASE),
    re.compile(r"\bAND\s+PUBYEAR\s*[<>]=?\s*\d{4}", re.IGNORECASE),
    re.compile(r"\bAND\s+PY\s*=\s*\(?\s*\d{4}\s*-\s*\d{4}\s*\)?", re.IGNORECASE),
    re.compile(r"\bAND\s+yearPublished\s*[<>]=?\s*\d{4}", re.IGNORECASE),
    re.compile(r"\bAND\s+submittedDate:\[[^\]]*\]", re.IGNORECASE),
    re.compile(r"\[[^\]]*\]"),  # PubMed field tags such as [Title/Abstract]
)
_FIELD_PREFIX_RE = re.compile(r"\b(?:TITLE-ABS-KEY|TITLE-ABS|TITLE|ABS|KEY)\s*\(", re.IGNORECASE)
_FIELD_EQ_RE = re.compile(r"\b(?:TS|TI|AB)\s*=\s*", re.IGNORECASE)
_COLON_FIELD_RE = re.compile(r"\b(?:all|ti|abs|title|abstract):", re.IGNORECASE)
_OPS = {"AND", "OR", "NOT"}


def _clean(query: str) -> str:
    q = " ".join(str(query or "").split())
    for pat in _STRIP_PATTERNS:
        q = pat.sub(" ", q)
    q = _FIELD_PREFIX_RE.sub("(", q)
    q = _FIELD_EQ_RE.sub("", q)
    q = _COLON_FIELD_RE.sub("", q)
    return " ".join(q.split())


class _ParseError(ValueError):
    pass


def _parse(tokens: list[str]) -> list[list[QueryTerm]]:
    """Parse tokens into AND-of-OR groups; raise _ParseError for other shapes."""
    pos = 0

    def peek() -> str | None:
        return tokens[pos] if pos < len(tokens) else None

    def parse_and() -> list[list[QueryTerm]]:
        nonlocal pos
        groups = [parse_or()]
        while peek() is not None and peek() != ")":
            tok = peek()
            if tok is not None and tok.upper() == "AND":
                pos += 1
                groups.append(parse_or())
                continue
            if tok is not None and tok.upper() == "NOT":
                raise _ParseError("NOT is not representable in the concept-group model")
            # Implicit AND between adjacent atoms (Scopus/WoS semantics).
            groups.append(parse_or())
        # Flatten: an AND inside an AND is just more groups.
        flat: list[list[QueryTerm]] = []
        for g in groups:
            flat.extend(g)
        return flat

    def parse_or() -> list[list[QueryTerm]]:
        nonlocal pos
        alternatives = [parse_atom()]
        while peek() is not None and peek().upper() == "OR":  # type: ignore[union-attr]
            pos += 1
            alternatives.append(parse_atom())
        if len(alternatives) == 1:
            return alternatives[0]
        terms: list[QueryTerm] = []
        for alt in alternatives:
            if len(alt) != 1:
                raise _ParseError("OR of AND-expressions is not representable")
            terms.extend(alt[0])
        return [terms]

    def parse_atom() -> list[list[QueryTerm]]:
        nonlocal pos
        tok = peek()
        if tok is None:
            raise _ParseError("unexpected end of query")
        if tok == "(":
            pos += 1
            inner = parse_and()
            if peek() != ")":
                raise _ParseError("unbalanced parentheses")
            pos += 1
            return inner
        if tok == ")" or tok.upper() in _OPS:
            raise _ParseError(f"unexpected token {tok!r}")
        # A run of adjacent bare words forms one multi-word term.
        if tok.startswith('"'):
            pos += 1
            text = tok.strip('"').strip()
            if not text:
                raise _ParseError("empty phrase")
            return [[QueryTerm(text=text, phrase=True)]]
        words: list[str] = []
        while True:
            t = peek()
            if t is None or t in {"(", ")"} or t.upper() in _OPS or t.startswith('"'):
                break
            words.append(t)
            pos += 1
        return [[QueryTerm(text=" ".join(words), phrase=len(words) > 1)]]

    result = parse_and()
    if pos != len(tokens):
        raise _ParseError("trailing tokens")
    return result


def has_boolean_operators(query: str) -> bool:
    return bool(re.search(r"\b(AND|OR|NOT)\b", query or "")) or "(" in (query or "")


def parse_conceptual_query(query: str) -> ConceptualQuery:
    """Parse a boolean query (generic or Scopus/WoS/PubMed flavoured) into groups.

    Plain keyword strings (no operators, no quotes) are returned unstructured
    with ``raw`` set so callers can pass them through verbatim.
    """
    raw = " ".join(str(query or "").split())
    if not raw:
        return ConceptualQuery(raw="")
    if not has_boolean_operators(raw) and '"' not in raw:
        return ConceptualQuery(raw=raw)
    cleaned = _clean(raw)
    tokens = _TOKEN_RE.findall(cleaned)
    try:
        groups = _parse(tokens)
    except _ParseError:
        return ConceptualQuery(raw=raw)
    groups = [_dedupe_terms(g) for g in groups if g]
    return ConceptualQuery(groups=[g for g in groups if g], raw=raw)


def conceptual_from_terms(groups: list[list[str]]) -> ConceptualQuery:
    out: list[list[QueryTerm]] = []
    for g in groups:
        terms = [QueryTerm(text=t.strip(), phrase=" " in t.strip()) for t in g if str(t or "").strip()]
        if terms:
            out.append(_dedupe_terms(terms))
    return ConceptualQuery(groups=out)


def _dedupe_terms(terms: list[QueryTerm]) -> list[QueryTerm]:
    seen: set[str] = set()
    out: list[QueryTerm] = []
    for t in terms:
        key = t.text.casefold()
        if key and key not in seen:
            seen.add(key)
            out.append(t)
    return out


def _quote(term: QueryTerm) -> str:
    text = term.text.replace('"', "")
    return f'"{text}"' if (term.phrase or " " in text) else text


def _group(parts: list[str], op: str, *, wrap: bool) -> str:
    joined = f" {op} ".join(parts)
    return f"({joined})" if wrap and len(parts) > 1 else joined


def render_boolean(cq: ConceptualQuery) -> str:
    """Generic uppercase AND/OR boolean (OpenAlex ``search``, CORE ``q``)."""
    wrap = len(cq.groups) > 1
    return " AND ".join(_group([_quote(t) for t in g], "OR", wrap=wrap) for g in cq.groups)


def render_semantic_scholar_bulk(cq: ConceptualQuery) -> str:
    """Semantic Scholar /paper/search/bulk syntax: ``+`` AND, ``|`` OR."""
    wrap = len(cq.groups) > 1
    return " + ".join(_group([_quote(t) for t in g], "|", wrap=wrap) for g in cq.groups)


def render_arxiv(cq: ConceptualQuery) -> str:
    def _field(t: QueryTerm) -> str:
        text = t.text.replace('"', "")
        return f'all:"{text}"' if (t.phrase or " " in text) else f"all:{text}"

    wrap = len(cq.groups) > 1
    return " AND ".join(_group([_field(t) for t in g], "OR", wrap=wrap) for g in cq.groups)


_DBLP_MAX_TERMS_PER_GROUP = 6
_DBLP_MAX_GROUPS = 3


def render_dblp(cq: ConceptualQuery) -> str:
    """DBLP: ``|`` OR within a group, space AND between groups, dash-joined phrases."""

    def _term(t: QueryTerm) -> str:
        words = re.findall(r"[A-Za-z0-9]+", t.text)
        return "-".join(words)

    parts: list[str] = []
    for g in cq.groups[:_DBLP_MAX_GROUPS]:
        terms = [x for x in (_term(t) for t in g[:_DBLP_MAX_TERMS_PER_GROUP]) if x]
        if terms:
            parts.append("|".join(terms))
    return " ".join(parts)


_CROSSREF_MAX_TERMS = 12


def render_crossref_keywords(cq: ConceptualQuery) -> str:
    """Crossref ``query.bibliographic`` is relevance-ranked free text: no operators."""
    terms: list[str] = []
    seen: set[str] = set()
    # Interleave groups so every concept is represented within the cap.
    longest = max((len(g) for g in cq.groups), default=0)
    for i in range(longest):
        for g in cq.groups:
            if i < len(g):
                text = re.sub(r"[\"()]", " ", g[i].text)
                text = " ".join(text.split())
                if text and text.casefold() not in seen:
                    seen.add(text.casefold())
                    terms.append(text)
    return " ".join(terms[:_CROSSREF_MAX_TERMS])


def strip_boolean_syntax(query: str) -> str:
    """Remove boolean operators/quotes/parentheses from a raw query string."""
    q = re.sub(r"\b(AND|OR|NOT)\b", " ", query or "")
    q = re.sub(r"[\"()|+]", " ", q)
    return " ".join(q.split())
