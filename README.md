# Verity

**Evidence-first AI research for complex and contested questions.**

Verity is an open-source AI/ML engineering project exploring how artificial intelligence can investigate controversial historical, political, and social claims through transparent evidence retrieval, source attribution, and systematic verification.

Rather than treating an LLM-generated answer as authoritative, Verity aims to make the underlying evidence inspectable, traceable, and reproducible.

> **Status:** Early development — research prototype. Not intended as an authoritative fact-checking service.

## The Problem

Political and historical questions are often difficult to investigate. Sources may disagree, important evidence may be missing, and factual reporting can become mixed with interpretation, speculation, or misinformation.

LLMs can generate persuasive explanations, but a convincing answer does not necessarily mean its claims are supported.

Verity explores a different approach: **verify the evidence behind an answer, not just the plausibility of the answer itself.**

## How Verity Works

The planned research pipeline is:

1. **Document ingestion** — Collect and preserve source documents with provenance metadata.
2. **Evidence retrieval** — Identify relevant passages using lexical and semantic retrieval.
3. **Claim assessment** — Examine whether retrieved passages support, contradict, or fail to address a specific claim.
4. **Citation verification** — Validate that quotations and citations correspond to actual stored passages.
5. **Research reporting** — Present evidence, disagreements, limitations, and unresolved questions.

A central design principle is distinguishing two different tasks:

- **Attribution verification:** Does a source actually make a particular claim?
- **Factual assessment:** What does the broader body of evidence establish?

An accurately quoted source is not necessarily an accurate source.

## Planned AI/ML Components

| Component | Approach |
|---|---|
| Lexical retrieval | BM25 |
| Semantic retrieval | Text embeddings |
| Hybrid search | Reciprocal Rank Fusion |
| Evidence classification | Natural Language Inference |
| Claim analysis | Large Language Models |
| Citation validation | Deterministic passage verification |
| Evaluation | Retrieval Recall@k, MRR, classification metrics, citation accuracy |

The project will evaluate these approaches experimentally rather than assuming that additional AI components automatically improve reliability.

## Technology

- Python 3.12
- Pydantic
- pytest
- Ruff
- uv

Planned additions include sentence-transformers, an LLM integration, FastAPI, and Next.js.

## Development Roadmap

- [x] Milestone 0 — Project setup and development environment
- [ ] Milestone 1 — Document models, ingestion, and chunking
- [ ] Milestone 2 — BM25 evidence retrieval
- [ ] Milestone 3 — Citation verification
- [ ] Milestone 4 — LLM-based evidence assessment
- [ ] Milestone 5 — End-to-end research demonstration
- [ ] Milestone 6 — Dense and hybrid retrieval
- [ ] Milestone 7 — Natural language inference
- [ ] Milestone 8 — Claim decomposition and research reports
- [ ] Milestone 9 — API and reproducible research logs

Future work includes live web research, source-independence analysis, contradiction detection, and an interactive research interface.

See `docs/ROADMAP.md` for additional implementation details.

## Getting Started

Install [uv](https://docs.astral.sh/uv/), then run:

```bash
git clone https://github.com/mohammadshaban05/verity.git
cd verity
uv sync
uv run pytest
```

To check linting and formatting:

```bash
uv run ruff check .
uv run ruff format --check .
```

The research pipeline is not yet implemented.

## Research Principles

Verity is being designed around several principles:

- **Evidence over authority:** Evaluate claims using traceable evidence rather than relying solely on a source's reputation.
- **Transparency:** Preserve document provenance and verifiable citations.
- **Uncertainty:** Distinguish unsupported claims from disproven claims.
- **Source diversity:** Consider official records, independent journalism, academic research, and credible critiques.
- **No false balance:** Represent competing explanations in proportion to their evidentiary support.
- **Reproducibility:** Record relevant documents, configurations, and evaluation results.
- **Accountability:** Measure errors and document limitations.

## Limitations

Verity is an experimental research system under development.

Accurate citations do not guarantee that a source's claims are true. Neither LLM agreement nor model-generated confidence scores constitute independent verification.

The system's reliability must be established through empirical evaluation before it is used for consequential research decisions.

## Project Goals

Verity is being developed as a hands-on software engineering and machine learning project, focusing on information retrieval, NLP, evaluation methodology, and reliable AI system design.

The longer-term goal is to investigate whether structured evidence verification can make AI-assisted research more transparent and dependable.

---

**Verity — Question the claim. Examine the evidence.**
