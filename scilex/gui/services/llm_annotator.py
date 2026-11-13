"""LLM annotators of a campaign, through the SciLEx Annotator service.

SciLEx Annotator (``scilex-annotator api``, a separate project) reads each
paper's full text and answers one question per grid dimension with values,
verbatim evidence and a confidence. SciLEx uses it as an extra, *subordinate*
annotator:

1. :func:`run_campaign` registers the campaign on the service (grid +
   guideline + paper type), posts the campaign's papers as BibTeX, waits for
   the job and imports the answers.
2. :func:`import_results` keeps every answer in
   ``annotations/llm/<campaign>.jsonl`` (collection folder) and, **only on
   dimensions no human has coded**, writes ``DIMENSION-AUTO:value`` proposals
   into the results (the Zotero sync shares them). A human code always wins.
3. A person resolves each proposal (:func:`decide`: accept, correct, reject),
   in SciLEx or directly in Zotero (:func:`reconcile`). Resolving removes the
   ``-AUTO`` tags; the decision is logged in ``annotations/llm/decisions.jsonl``.
4. :func:`llm_agreement` compares each model with the human codes; the
   agreement study can also count models as annotators (:func:`coder_tags`).

The service token is a key (``LmmAnnotator: {token: …}`` in ``keys.yml``, or
``$SCILEX_ANNOTATOR_TOKEN``); it is never written in the review.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import time
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

import pandas as pd

from scilex import annotation_agreement, review_tags
from scilex.gui.services.campaigns import LLM_PREFIX, Campaign
from scilex.gui.services.workspace import Review
from scilex.tagging import auto_tags

logger = logging.getLogger(__name__)

KEY_BLOCK = "LmmAnnotator"
TOKEN_ENV = "SCILEX_ANNOTATOR_TOKEN"
STORE_DIR = Path("annotations") / "llm"
DECISIONS = "decisions.jsonl"
POLL_SECONDS = 3.0
ACCEPTED, CORRECTED, REJECTED = "accepted", "corrected", "rejected"
OUTCOMES = (ACCEPTED, CORRECTED, REJECTED)


class AnnotatorError(RuntimeError):
    """The SciLEx Annotator service refused a request or cannot be reached."""


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def token_for(review: Review) -> str:
    from scilex.gui.services.keys_editor import effective_keys

    block = effective_keys(review.folder).get(KEY_BLOCK) or {}
    return str(block.get("token") or os.environ.get(TOKEN_ENV) or "")


# -- the service --------------------------------------------------------------


class Client:
    """Minimal client of the SciLEx Annotator HTTP API."""

    def __init__(self, url: str, token: str = "", *, http=None, timeout: float = 60):
        import httpx

        self.url = url.rstrip("/")
        headers = {"Authorization": f"Bearer {token}"} if token else {}
        self.http = http or httpx.Client(
            base_url=self.url, headers=headers, timeout=timeout
        )

    def _call(self, method: str, path: str, **kwargs):
        try:
            response = self.http.request(method, path, **kwargs)
        except Exception as exc:  # httpx.HTTPError, OSError
            raise AnnotatorError(
                f"SciLEx Annotator cannot be reached at {self.url} ({exc}). "
                "Start it with: scilex-annotator api"
            ) from exc
        if response.status_code == 401:
            raise AnnotatorError(
                "SciLEx Annotator refused the token: set it in API keys > SciLEx Annotator."
            )
        if response.status_code >= 400:
            try:
                detail = response.json().get("detail")
            except ValueError:
                detail = response.text[:500]
            raise AnnotatorError(f"SciLEx Annotator: {response.status_code} {detail}")
        return response.json()

    def health(self) -> bool:
        return self._call("GET", "/health").get("status") == "ok"

    def register(
        self,
        name: str,
        grid: bytes,
        guideline: bytes | None,
        paper_type: str,
        model: str,
    ) -> dict:
        files = {"grid": ("annotation_grid.csv", grid, "text/csv")}
        if guideline:
            files["guideline"] = ("guideline.md", guideline, "text/markdown")
        return self._call(
            "POST",
            "/reviews",
            data={
                "name": name,
                "paper_type": paper_type,
                "model": model,
                "overwrite": "true",
            },
            files=files,
        )

    def submit(
        self,
        review: str,
        bibtex: str,
        keys: list[str],
        tags: list[str],
        model: str,
        force: bool = False,
    ) -> dict:
        return self._call(
            "POST",
            f"/reviews/{review}/jobs",
            json={
                "bibtex": bibtex,
                "keys": keys,
                "tags": tags,
                "model": model,
                "force": force,
            },
        )

    def job(self, review: str, job_id: str) -> dict:
        return self._call("GET", f"/reviews/{review}/jobs/{job_id}")

    def results(self, review: str, job_id: str) -> dict:
        return self._call("GET", f"/reviews/{review}/jobs/{job_id}/results")


def remote_name(review: Review, campaign: Campaign) -> str:
    """The campaign's review id on the service (letters, digits, - and _)."""
    raw = f"{review.name}-{campaign.id}"
    name = re.sub(r"[^A-Za-z0-9_-]+", "-", raw).strip("-")
    if len(name) > 64:
        name = name[:51] + "-" + hashlib.sha1(raw.encode()).hexdigest()[:12]
    return name or "scilex"


# -- papers sent ------------------------------------------------------------------


def bib_key(row) -> str:
    """BibTeX key of a results row: its Zotero key, else a stable hash."""
    from scilex.gui.services.screening import paper_key

    zkey = str(row.get("zotero_key") or "").strip()
    if re.fullmatch(r"[A-Za-z0-9]{4,32}", zkey):
        return zkey
    return "p" + hashlib.sha1(paper_key(row).encode()).hexdigest()[:12]


def bibtex_for(data: pd.DataFrame, indexes: list) -> tuple[str, dict[str, int]]:
    """BibTeX of the rows (without their tags: the LLM stays blind) and key -> index."""
    from scilex.export_to_bibtex import format_bibtex_entry

    subset = data.loc[indexes].drop(columns=["tags"], errors="ignore")
    entries, keys = [], {}
    for index, record, row in zip(
        subset.index,
        subset.to_dict("records"),
        subset.itertuples(index=False),
        strict=True,
    ):
        key = bib_key(record)
        if key in keys:
            continue
        keys[key] = index
        entries.append(format_bibtex_entry(row, key))
    return "\n\n".join(entries) + "\n", keys


@dataclass
class RunPlan:
    """Papers and dimensions to send: one job per distinct set of dimensions."""

    groups: dict[tuple[str, ...], list] = field(default_factory=dict)  # dims -> indexes

    @property
    def papers(self) -> int:
        return sum(len(v) for v in self.groups.values())

    @property
    def questions(self) -> int:
        return sum(len(k) * len(v) for k, v in self.groups.items())

    def only(self, accepted: set[str]) -> RunPlan:
        """The plan without the dimensions the service does not annotate
        (for example its excluded screening TAGs)."""
        kept = RunPlan()
        for dims, indexes in self.groups.items():
            if wanted := tuple(d for d in dims if d in accepted):
                kept.groups.setdefault(wanted, []).extend(indexes)
        return kept


def plan_run(
    data: pd.DataFrame,
    campaign: Campaign,
    dims: list[str],
    *,
    also_coded: bool = False,
    rejected: set[tuple[str, str]] | frozenset = frozenset(),
) -> RunPlan:
    """Which (paper, dimension) pairs to ask the LLM.

    By default only the dimensions a human has not coded, with no pending
    proposal and whose proposal a person has not ``rejected`` ((paper key,
    dimension) pairs: asking again would bring the same answer back).
    ``also_coded``: every dimension (answers on human-coded ones are kept
    locally, to measure the LLM against the humans; they cost more).
    """
    from scilex.gui.services.campaigns import paper_rows
    from scilex.gui.services.screening import paper_key

    plan = RunPlan()
    tags = data.get("tags", pd.Series("", index=data.index))
    for index in paper_rows(data, campaign):
        states = auto_tags.dimension_states(tags[index], dims)
        pkey = paper_key(data.loc[index].to_dict()) if rejected else ""
        wanted = tuple(
            d
            for d in dims
            if also_coded
            or (states[d].status == auto_tags.TODO and (pkey, d) not in rejected)
        )
        if wanted:
            plan.groups.setdefault(wanted, []).append(index)
    return plan


# -- store --------------------------------------------------------------------


def store_dir(review: Review) -> Path:
    return review.collection_dir / STORE_DIR


def store_path(review: Review, campaign_id: str) -> Path:
    return store_dir(review) / f"{campaign_id}.jsonl"


def _append(path: Path, records: list[dict]) -> None:
    if not records:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")


def _read(path: Path) -> list[dict]:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except FileNotFoundError:
        return []
    records = []
    for line in lines:
        try:
            records.append(json.loads(line))
        except json.JSONDecodeError:
            logger.warning("Skipping a damaged line of %s", path)
    return records


def answers(review: Review, campaign_id: str | None = None) -> list[dict]:
    """Stored LLM answers (of one campaign, or of all)."""
    if campaign_id:
        return _read(store_path(review, campaign_id))
    folder = store_dir(review)
    if not folder.is_dir():
        return []
    return [
        record
        for path in sorted(folder.glob("*.jsonl"))
        if path.name != DECISIONS
        for record in _read(path)
    ]


def latest_answers(records: list[dict]) -> dict[tuple[str, str, str], dict]:
    """Last answer per (paper_key, dimension, model)."""
    latest = {}
    for record in records:
        latest[(record["paper_key"], record["dimension"], record["model"])] = record
    return latest


def decisions(review: Review) -> list[dict]:
    return _read(store_dir(review) / DECISIONS)


def rejected_pairs(review: Review) -> set[tuple[str, str]]:
    """(paper key, dimension) whose latest decision is a rejection."""
    last: dict[tuple[str, str], str] = {}
    for decision in decisions(review):
        last[(decision["paper_key"], decision["dimension"])] = decision["outcome"]
    return {pair for pair, outcome in last.items() if outcome == REJECTED}


# -- import -------------------------------------------------------------------


def tag_value(value) -> str:
    """A value as SciLEx Annotator writes it in a tag (its ``scilex_value``).

    A value without spaces is kept as it is (``RC``, ``SciBERT``: the grid's
    UpperCamelCase vocabulary); one with spaces is joined in UpperCamelCase
    (``deep learning`` -> ``DeepLearning``). ``;`` cannot appear in a tag.
    """
    text = str(value).strip().replace(";", ",")
    if " " not in text:
        return text
    return "".join(w[:1].upper() + w[1:] for w in re.split(r"\s+", text))


def _values(raw) -> list[str]:
    return [v for v in dict.fromkeys(tag_value(v) for v in raw or []) if v]


@dataclass
class ImportReport:
    answers: int = 0
    proposals: int = 0  # DIM-AUTO tags written
    papers: int = 0  # papers whose tags changed
    validated: int = 0  # answers a person accepted/corrected in SciLEx Annotator
    rejected: int = 0  # answers a person rejected in SciLEx Annotator
    kept_local: int = 0  # answers on human-coded dimensions (human first)
    not_addressed: int = 0
    errors: int = 0

    def add(self, other: ImportReport) -> None:
        for name in ImportReport.__dataclass_fields__:
            setattr(self, name, getattr(self, name) + getattr(other, name))

    def message(self) -> str:
        text = (
            f"{self.answers} answers: {self.proposals} proposals written on "
            f"{self.papers} papers"
        )
        extra = []
        if self.validated:
            extra.append(
                f"{self.validated} already validated by a person in SciLEx Annotator "
                "(written as codes)"
            )
        if self.rejected:
            extra.append(f"{self.rejected} rejected there")
        if self.kept_local:
            extra.append(
                f"{self.kept_local} on dimensions a human coded (kept locally)"
            )
        if self.not_addressed:
            extra.append(f"{self.not_addressed} not addressed by the paper")
        if self.errors:
            extra.append(f"{self.errors} errors")
        return text + (f"; {', '.join(extra)}" if extra else "") + "."


def import_results(
    review: Review,
    campaign: Campaign,
    payload: dict,
    keys: dict[str, int],
    *,
    job_id: str = "",
    journal: bool = True,
) -> ImportReport:
    """Store the answers of a job and write them as SciLEx tags (human first).

    - a dimension a human already coded in the review keeps its codes (the
      answer is only stored);
    - an answer a person accepted or corrected in SciLEx Annotator is a human
      decision: its final values become ``DIM:value`` codes, logged with that
      reviewer; one they rejected writes nothing;
    - any other answer becomes ``DIM-AUTO:value`` proposals.

    ``payload``: the service's job results; ``keys``: BibTeX key -> results index.
    """
    from scilex.gui.services.extend import read_results
    from scilex.gui.services.members import apply_tags_by_key
    from scilex.gui.services.screening import paper_key

    data = read_results(review.results_path)
    report = ImportReport()
    records, changes, logged = [], {}, []
    model = str((payload.get("job") or {}).get("model") or "")
    for paper in payload.get("papers") or []:
        index = keys.get(str(paper.get("key")))
        if index is None or index not in data.index:
            continue
        row = data.loc[index].to_dict()
        pkey = paper_key(row)
        current = row.get("tags")
        states = auto_tags.dimension_states(current)
        add: list[str] = []
        remove: list[str] = []
        for answer in paper.get("annotations") or []:
            dim = str(answer.get("tag") or "").strip().upper()
            if not dim:
                continue
            values = _values(answer.get("values"))  # the model's own answer
            error = str(answer.get("error") or "")
            addressed = bool(answer.get("addressed")) and not error
            status = str(answer.get("status") or "llm")
            answer_model = str(answer.get("model") or model)
            coded = dim in states and states[dim].status == auto_tags.HUMAN
            report.answers += 1
            report.errors += bool(error)
            report.not_addressed += not error and not addressed
            proposed = False
            if error:
                pass
            elif coded:
                report.kept_local += addressed
            elif status in OUTCOMES:
                human = (
                    _values(answer.get("final_values")) if status != REJECTED else []
                )
                if status == REJECTED or human:
                    add_now, remove_now = auto_tags.resolve(current, dim, human)
                    current = review_tags.with_tags(current, add_now, remove_now)
                    add += add_now
                    remove += remove_now
                    report.validated += status != REJECTED
                    report.rejected += status == REJECTED
                    logged.append(
                        {
                            "at": _now(),
                            "campaign": campaign.id,
                            "paper_key": pkey,
                            "dimension": dim,
                            "proposed": values,
                            "models": [answer_model],
                            "human_values": human,
                            "outcome": status,
                            "reviewer": str(answer.get("reviewer") or ""),
                            "via": "scilex-annotator",
                        }
                    )
            elif addressed and values:
                proposals = [auto_tags.auto_tag(dim, v) for v in values]
                current = review_tags.with_tags(current, proposals)
                add += proposals
                proposed = True
            records.append(
                {
                    "at": _now(),
                    "campaign": campaign.id,
                    "job": job_id,
                    "paper_key": pkey,
                    "bib_key": paper.get("key"),
                    "zotero_key": str(row.get("zotero_key") or ""),
                    "dimension": dim,
                    "model": answer_model,
                    "addressed": addressed,
                    "values": values,
                    "confidence": answer.get("confidence") or "",
                    "rationale": answer.get("rationale") or "",
                    "evidence": [
                        {
                            "quote": e.get("quote", ""),
                            "section": e.get("section", ""),
                            "found": bool(e.get("found")),
                        }
                        for e in answer.get("evidence") or []
                    ],
                    "text_source": answer.get("text_source") or "",
                    "prompt_hash": answer.get("prompt_hash") or "",
                    "error": error,
                    "status_in_annotator": status,
                    "proposed": proposed,
                    "human_at_import": states[dim].human if coded else [],
                }
            )
        if add or remove:
            changes[pkey] = (add, remove)
    _append(store_path(review, campaign.id), records)
    if changes:
        apply_tags_by_key(review, changes)
        report.papers = len(changes)
        report.proposals = sum(
            1 for a, _ in changes.values() for t in a if auto_tags.is_auto_tag(t)
        )
    _append(store_dir(review) / DECISIONS, logged)
    if journal:
        _journal(review, "llm-annotations-imported", campaign, report, job_id, model)
    return report


def new_answers(
    payload: dict, seen: set[tuple[str, str]], *, since: str = ""
) -> dict | None:
    """The job results restricted to the (paper, TAG) answers not in ``seen``
    (which is updated), or None if there is none.

    ``since``: an ISO time; keep only the answers created at or after it.
    """
    papers = []
    for paper in payload.get("papers") or []:
        key = str(paper.get("key"))
        fresh = []
        for answer in paper.get("annotations") or []:
            pair = (key, str(answer.get("tag") or "").strip().upper())
            if pair in seen or (since and str(answer.get("created_at") or "") < since):
                continue
            seen.add(pair)
            fresh.append(answer)
        if fresh:
            papers.append({**paper, "annotations": fresh})
    return {**payload, "papers": papers} if papers else None


def store_signature(review: Review) -> tuple:
    """Changes when LLM answers are imported or decided (cheap: file stats)."""
    try:
        return tuple(
            sorted(
                (p.name, p.stat().st_mtime_ns, p.stat().st_size)
                for p in store_dir(review).glob("*.jsonl")
            )
        )
    except OSError:
        return ()


def _journal(review, event, campaign, report, job_id, model) -> None:
    try:
        from scilex.gui.services import journal

        journal.append(
            review.folder,
            event,
            used={"campaign": campaign.id, "job": job_id},
            generated={
                "proposals": report.proposals,
                "papers": report.papers,
                "answers": report.answers,
            },
            params={"model": model, "collection": campaign.collection},
        )
    except Exception:  # the journal must never break an import
        logger.warning("Cannot journal the LLM import", exc_info=True)


def run_campaign(
    review: Review,
    campaign: Campaign,
    model: str,
    url: str,
    *,
    also_coded: bool = False,
    job=None,
    client: Client | None = None,
    poll: float = POLL_SECONDS,
) -> ImportReport:
    """Annotate the campaign's papers with ``model`` and import the answers.

    ``job``: a :class:`scilex.gui.services.jobs.Job` (progress, message,
    cancellation), or None.
    """
    from scilex.gui.services import annotations
    from scilex.gui.services.campaigns import dimensions
    from scilex.gui.services.extend import read_results

    grid = annotations.load_review_grid(review)
    dims = dimensions(grid, campaign)
    if not dims:
        raise ValueError(
            f"No dimension of the grid applies to '{campaign.paper_type}' papers."
        )
    data = read_results(review.results_path)
    if data is None:
        raise ValueError("The review has no papers yet.")
    plan = plan_run(
        data, campaign, dims, also_coded=also_coded, rejected=rejected_pairs(review)
    )
    if not plan.groups:
        return ImportReport()
    client = client or Client(url, token_for(review))
    remote = remote_name(review, campaign)
    guideline = annotations.load_guideline_text(review)

    def say(text: str, progress: float | None = None) -> None:
        if job is not None:
            job.message = text
            if progress is not None:
                job.progress = progress

    say(f"Registering the campaign on SciLEx Annotator ({url})…", 1)
    info = client.register(
        remote,
        annotations.grid_path(review).read_bytes(),
        guideline.encode("utf-8") if guideline.strip() else None,
        campaign.paper_type,
        model,
    )
    if info.get("tags") is not None:  # the TAGs the service annotates
        plan = plan.only({str(t).upper() for t in info["tags"]})
        if not plan.groups:
            return ImportReport()
    total = ImportReport()
    expected = plan.questions
    done_before = 0
    for dims_asked, indexes in plan.groups.items():
        bibtex, keys = bibtex_for(data, indexes)
        posted = client.submit(remote, bibtex, list(keys), list(dims_asked), model)
        job_id = posted["id"]
        since = str(posted.get("created_at") or "")
        seen: set[tuple[str, str]] = set()
        report = ImportReport()

        def pull(final: bool) -> None:
            """Import the answers of the job not imported yet, as they arrive.

            While the job runs, only answers written since it started (the
            service may also hold older answers of the same pairs); the last
            pull takes everything, as a whole-job import did."""
            fresh = new_answers(
                client.results(remote, job_id), seen, since="" if final else since
            )
            if fresh is not None:
                part = import_results(
                    review, campaign, fresh, keys, job_id=job_id, journal=False
                )
                report.add(part)
                total.add(part)

        pulled = 0
        while True:
            status = client.job(remote, job_id)
            completed = int(status.get("completed") or 0)
            finished = status.get("status") in ("done", "failed", "interrupted")
            if completed > pulled and not finished:
                pull(final=False)
                pulled = completed
            say(
                f"{model}: {done_before + completed} of {expected} questions answered, "
                f"{total.proposals} proposals imported…",
                min(99, 100 * (done_before + completed) / max(expected, 1)),
            )
            if finished:
                break
            if job is not None and job.cancel_event.is_set():
                say("Cancelled: answers received so far are imported.")
                break
            time.sleep(poll)
        if status.get("status") in ("failed", "interrupted") and not completed:
            raise AnnotatorError(
                f"The annotation job {status.get('status')}: {status.get('error', '')}"
            )
        pull(final=True)
        _journal(review, "llm-annotations-imported", campaign, report, job_id, model)
        done_before += len(dims_asked) * len(indexes)
        if job is not None and job.cancel_event.is_set():
            break
    say(total.message(), 100)
    return total


# -- human validation ----------------------------------------------------------


@dataclass
class Proposal:
    """A pending ``DIM-AUTO`` proposal on one paper, with the models' answers."""

    paper_key: str
    title: str
    dimension: str
    values: list[str]
    campaign: str
    answers: list[dict] = field(default_factory=list)  # latest per model

    @property
    def confidence(self) -> str:
        levels = [a.get("confidence") for a in self.answers]
        for level in ("low", "medium", "high"):
            if level in levels:
                return level
        return ""

    @property
    def evidence_found(self) -> bool:
        quotes = [e for a in self.answers for e in a.get("evidence") or []]
        return bool(quotes) and all(e.get("found") for e in quotes)


def pending(
    review: Review, data: pd.DataFrame, campaigns: list[Campaign], grid
) -> list[Proposal]:
    """Every proposal waiting for a person, in the campaigns' papers."""
    from scilex.gui.services.campaigns import dimensions, paper_rows
    from scilex.gui.services.screening import paper_key

    latest = latest_answers(answers(review))
    by_paper_dim = defaultdict(list)
    for (pkey, dim, _model), record in latest.items():
        by_paper_dim[(pkey, dim)].append(record)
    found: list[Proposal] = []
    seen = set()
    tags = data.get("tags", pd.Series("", index=data.index))
    for campaign in campaigns:
        dims = dimensions(grid, campaign)
        for index in paper_rows(data, campaign):
            row = data.loc[index].to_dict()
            pkey = paper_key(row)
            for dim, state in auto_tags.dimension_states(tags[index], dims).items():
                if state.status != auto_tags.PROPOSED or (pkey, dim) in seen:
                    continue
                seen.add((pkey, dim))
                found.append(
                    Proposal(
                        paper_key=pkey,
                        title=str(row.get("title") or pkey),
                        dimension=dim,
                        values=state.proposed,
                        campaign=campaign.id,
                        answers=by_paper_dim.get((pkey, dim), []),
                    )
                )
    return found


def decide(
    review: Review,
    proposal: Proposal,
    outcome: str,
    values: list[str] | None = None,
    reviewer: str = "",
) -> None:
    """A person resolves ``proposal``: accept it, correct it (``values``) or reject it.

    The human values become ``DIM:value`` codes; ``DIM:?`` and every
    ``DIM-AUTO`` tag of the dimension are removed (reject keeps ``DIM:?``).
    """
    decide_many(review, [(proposal, outcome, values)], reviewer)


def decide_many(
    review: Review,
    items: list[tuple[Proposal, str, list[str] | None]],
    reviewer: str = "",
) -> int:
    """:func:`decide` for several proposals in one write; return those applied."""
    from scilex.gui.services.extend import read_results
    from scilex.gui.services.journal import current_agent
    from scilex.gui.services.members import apply_tags_by_key
    from scilex.gui.services.screening import paper_key

    reviewer = reviewer or current_agent()["id"] or current_agent()["name"]
    data = read_results(review.results_path)
    tags_by_key = {paper_key(r): r.get("tags") for r in data.to_dict("records")}
    changes: dict[str, tuple[list[str], list[str]]] = {}
    logged = []
    for proposal, outcome, values in items:
        if outcome not in OUTCOMES:
            raise ValueError(f"Unknown outcome {outcome!r}")
        human = (
            proposal.values
            if outcome == ACCEPTED
            else []
            if outcome == REJECTED
            else list(values or [])
        )
        human = _values(human)
        if outcome == CORRECTED and not human:
            raise ValueError("A correction needs at least one value.")
        # Several dimensions of one paper: resolve against its tags so far.
        current = tags_by_key.get(proposal.paper_key)
        add_now, remove_now = auto_tags.resolve(current, proposal.dimension, human)
        tags_by_key[proposal.paper_key] = review_tags.with_tags(
            current, add_now, remove_now
        )
        add, remove = changes.get(proposal.paper_key, ([], []))
        gone = {t.casefold() for t in remove_now}
        changes[proposal.paper_key] = (
            [t for t in add if t.casefold() not in gone] + add_now,
            remove + remove_now,
        )
        logged.append(
            {
                "at": _now(),
                "campaign": proposal.campaign,
                "paper_key": proposal.paper_key,
                "dimension": proposal.dimension,
                "proposed": proposal.values,
                "models": sorted({a.get("model", "") for a in proposal.answers}),
                "human_values": human,
                "outcome": outcome,
                "reviewer": reviewer,
                "via": "scilex",
            }
        )
    if not changes:
        return 0
    apply_tags_by_key(review, changes)
    _append(store_dir(review) / DECISIONS, logged)
    return len(logged)


def reconcile(review: Review, data: pd.DataFrame | None = None) -> dict[str, int]:
    """Log the proposals people resolved directly in Zotero, and tidy stale ones.

    A proposal written by SciLEx, gone from the tags with no decision logged,
    was resolved in Zotero: accepted (human codes = proposal), corrected
    (other codes) or rejected (no code). Proposals still on a dimension a
    human has coded are removed (human first) and logged as such.
    """
    from scilex.gui.services.extend import read_results
    from scilex.gui.services.members import apply_tags_by_key
    from scilex.gui.services.screening import paper_key

    data = read_results(review.results_path) if data is None else data
    if data is None:
        return {}
    tags_by_key = {paper_key(r): r.get("tags") for r in data.to_dict("records")}
    decided_pairs_after: dict[tuple[str, str], str] = {}
    for d in decisions(review):
        key = (d["paper_key"], d["dimension"])
        decided_pairs_after[key] = max(decided_pairs_after.get(key, ""), d["at"])
    written: dict[tuple[str, str], dict] = {}
    for record in answers(review):
        if record.get("proposed"):
            key = (record["paper_key"], record["dimension"])
            if key not in written or record["at"] >= written[key]["at"]:
                written[key] = record
    counts: Counter = Counter()
    logged, tidy = [], {}
    for (pkey, dim), record in written.items():
        if decided_pairs_after.get((pkey, dim), "") >= record["at"]:
            continue  # already decided after this proposal
        if pkey not in tags_by_key:
            continue
        state = auto_tags.dimension_states(tags_by_key[pkey], [dim])[dim]
        if state.proposed and not state.human:
            continue  # still waiting
        if state.stale_proposals:
            tidy[pkey] = (
                [],
                tidy.get(pkey, ([], []))[1]
                + [auto_tags.auto_tag(dim, v) for v in state.proposed],
            )
        proposed = set(record.get("values") or [])
        if state.human:
            outcome = ACCEPTED if set(state.human) == proposed else CORRECTED
        else:
            outcome = REJECTED
        counts[outcome] += 1
        logged.append(
            {
                "at": _now(),
                "campaign": record.get("campaign", ""),
                "paper_key": pkey,
                "dimension": dim,
                "proposed": sorted(proposed),
                "models": [record.get("model", "")],
                "human_values": state.human,
                "outcome": outcome,
                "reviewer": "",
                "via": "human-first" if state.stale_proposals else "zotero",
            }
        )
    if tidy:
        apply_tags_by_key(review, tidy)
        counts["tidied"] = len(tidy)
    _append(store_dir(review) / DECISIONS, logged)
    return dict(counts)


# -- LLM against humans --------------------------------------------------------


@dataclass
class ModelAgreement:
    """How one model compares with the human codes."""

    model: str
    dimensions: list[annotation_agreement.DimensionAgreement]
    outcomes: Counter  # accepted / corrected / rejected decisions on its proposals

    @property
    def acceptance(self) -> float:
        total = sum(self.outcomes[o] for o in OUTCOMES)
        return self.outcomes[ACCEPTED] / total if total else float("nan")


def coder_tags(review: Review, zotero_keys: set[str] | None = None) -> dict:
    """``{zotero item key: {"llm:<model>": [DIM:value…]}}`` from the stored answers.

    The agreement study adds these coders next to the humans' copies.
    """
    found: dict[str, dict[str, list[str]]] = {}
    for record in latest_answers(answers(review)).values():
        zkey = record.get("zotero_key") or ""
        if not zkey or (zotero_keys is not None and zkey not in zotero_keys):
            continue
        if record.get("error"):
            continue
        coder = LLM_PREFIX + record["model"]
        tags = found.setdefault(zkey, {}).setdefault(coder, [])
        tags += [f"{record['dimension']}:{v}" for v in record.get("values") or []]
    return found


def llm_agreement(review: Review, data: pd.DataFrame) -> list[ModelAgreement]:
    """Each model against the human codes of the same papers (MASI alpha per dimension)."""
    from scilex.gui.services.screening import paper_key

    human_by_key = {}
    for record in data.to_dict("records"):
        states = auto_tags.dimension_states(record.get("tags"))
        human_by_key[paper_key(record)] = {
            dim: s.human for dim, s in states.items() if s.human
        }
    per_model: dict[str, dict[str, dict[str, list[str]]]] = defaultdict(dict)
    for record in latest_answers(answers(review)).values():
        if record.get("error"):
            continue
        human = human_by_key.get(record["paper_key"], {}).get(record["dimension"])
        if not human:
            continue
        study = per_model[record["model"]].setdefault(
            record["paper_key"], {"human": [], "llm": []}
        )
        study["human"] += [f"{record['dimension']}:{v}" for v in human]
        values = record.get("values") or [auto_tags.PLACEHOLDER]
        study["llm"] += [f"{record['dimension']}:{v}" for v in values]
    outcomes: dict[str, Counter] = defaultdict(Counter)
    for decision in decisions(review):
        for model in decision.get("models") or []:
            outcomes[model][decision["outcome"]] += 1
    return [
        ModelAgreement(
            model=model,
            # Only dimensions a human coded: "not addressed" counts as a value.
            dimensions=annotation_agreement.by_dimension(studied, skip_uncoded=False),
            outcomes=outcomes.get(model, Counter()),
        )
        for model, studied in sorted(per_model.items())
    ] + [
        ModelAgreement(model=m, dimensions=[], outcomes=c)
        for m, c in sorted(outcomes.items())
        if m and m not in per_model
    ]
