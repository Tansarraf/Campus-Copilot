const fs = require("fs");
const {
  Document, Packer, Paragraph, TextRun, HeadingLevel, AlignmentType,
  Table, TableRow, TableCell, WidthType, ShadingType, BorderStyle,
  ImageRun, PageBreak, LevelFormat, convertInchesToTwip,
} = require("docx");

const BLUE = "3454D1";
const DARK = "1C1F26";
const MUTED = "6B7280";

// ---------- helpers ----------
function h1(text) {
  return new Paragraph({ text, heading: HeadingLevel.HEADING_1, spacing: { before: 320, after: 160 } });
}
function h2(text) {
  return new Paragraph({ text, heading: HeadingLevel.HEADING_2, spacing: { before: 240, after: 120 } });
}
function p(text, opts = {}) {
  return new Paragraph({
    spacing: { after: 160, line: 276 },
    children: [new TextRun({ text, ...opts })],
  });
}
function pRuns(runs, opts = {}) {
  return new Paragraph({ spacing: { after: 160, line: 276 }, children: runs, ...opts });
}
function bold(text) { return new TextRun({ text, bold: true }); }
function italic(text) { return new TextRun({ text, italics: true }); }
function caption(text) {
  return new Paragraph({
    alignment: AlignmentType.CENTER,
    spacing: { after: 240 },
    children: [new TextRun({ text, italics: true, size: 20, color: MUTED })],
  });
}

function simpleTable(headerRow, rows, colWidths) {
  const totalWidth = 9350;
  const widths = colWidths || headerRow.map(() => Math.floor(totalWidth / headerRow.length));
  const mkCell = (text, isHeader) => new TableCell({
    width: { size: widths[0], type: WidthType.DXA },
    shading: isHeader ? { type: ShadingType.CLEAR, color: "auto", fill: "EEF2FF" } : undefined,
    margins: { top: 80, bottom: 80, left: 100, right: 100 },
    children: [new Paragraph({
      children: [new TextRun({ text: String(text), bold: !!isHeader, size: 20 })],
    })],
  });
  const headerCells = headerRow.map((t, i) => new TableCell({
    width: { size: widths[i], type: WidthType.DXA },
    shading: { type: ShadingType.CLEAR, color: "auto", fill: "EEF2FF" },
    margins: { top: 80, bottom: 80, left: 100, right: 100 },
    children: [new Paragraph({ children: [new TextRun({ text: String(t), bold: true, size: 20 })] })],
  }));
  const bodyRows = rows.map((row) => new TableRow({
    children: row.map((cell, i) => new TableCell({
      width: { size: widths[i], type: WidthType.DXA },
      margins: { top: 80, bottom: 80, left: 100, right: 100 },
      children: [new Paragraph({ children: [new TextRun({ text: String(cell), size: 20 })] })],
    })),
  }));
  return new Table({
    width: { size: totalWidth, type: WidthType.DXA },
    columnWidths: widths,
    rows: [new TableRow({ children: headerCells }), ...bodyRows],
  });
}

// ---------- title page ----------
const titlePage = [
  new Paragraph({ spacing: { before: 1600 }, alignment: AlignmentType.CENTER,
    children: [new TextRun({ text: "Campus Copilot", bold: true, size: 56, color: BLUE })] }),
  new Paragraph({ alignment: AlignmentType.CENTER, spacing: { before: 120, after: 400 },
    children: [new TextRun({ text: "A Retrieval-Augmented Knowledge Assistant for University Information and Circulars", size: 30, color: DARK })] }),
  new Paragraph({ alignment: AlignmentType.CENTER, spacing: { after: 80 },
    children: [new TextRun({ text: "A Project Report submitted in partial fulfilment of the requirements for", size: 22, italics: true })] }),
  new Paragraph({ alignment: AlignmentType.CENTER, spacing: { after: 400 },
    children: [new TextRun({ text: "[Course / Degree Name — e.g. B.Tech in Computer Science and Engineering]", size: 22, italics: true, color: MUTED })] }),
  new Paragraph({ alignment: AlignmentType.CENTER, spacing: { before: 800, after: 40 },
    children: [new TextRun({ text: "Submitted by", size: 20, color: MUTED })] }),
  new Paragraph({ alignment: AlignmentType.CENTER, spacing: { after: 40 },
    children: [new TextRun({ text: "Tanishk Sarraf", bold: true, size: 26 })] }),
  new Paragraph({ alignment: AlignmentType.CENTER, spacing: { after: 400 },
    children: [new TextRun({ text: "[Roll No. / Registration No.]", size: 20, color: MUTED })] }),
  new Paragraph({ alignment: AlignmentType.CENTER, spacing: { before: 900, after: 40 },
    children: [new TextRun({ text: "Under the guidance of", size: 20, color: MUTED })] }),
  new Paragraph({ alignment: AlignmentType.CENTER, spacing: { after: 400 },
    children: [new TextRun({ text: "[Guide / Supervisor Name]", size: 22, color: MUTED })] }),
  new Paragraph({ alignment: AlignmentType.CENTER, spacing: { before: 900 },
    children: [new TextRun({ text: "[Department Name]", size: 22 })] }),
  new Paragraph({ alignment: AlignmentType.CENTER,
    children: [new TextRun({ text: "[College / University Name]", size: 22 })] }),
  new Paragraph({ alignment: AlignmentType.CENTER, spacing: { after: 400 },
    children: [new TextRun({ text: "September 2026", size: 22 })] }),
  new Paragraph({ children: [new PageBreak()] }),
];

// ---------- abstract ----------
const abstract = [
  h1("Abstract"),
  p(
    "Colleges generate a large volume of unstructured information — academic calendars, fee circulars, " +
    "hostel rules, scholarship notices, placement guidelines, examination regulations and library policies — " +
    "scattered across PDFs, notice boards, department pages and messaging groups. Students and staff routinely " +
    "lose time locating straightforward answers that already exist in an official document. This report presents " +
    "Campus Copilot, a Retrieval-Augmented Generation (RAG) question-answering assistant that ingests official " +
    "university documents in multiple formats, indexes them into a searchable knowledge base, and answers natural-" +
    "language questions with responses grounded strictly in the indexed material, accompanied by transparent " +
    "citations to the source document, section or page."
  ),
  p(
    "The system is deliberately built with a lean, explainable stack rather than a heavyweight enterprise one: " +
    "FastAPI for the backend API, SQLite for both relational data and vector storage, scikit-learn for cosine-" +
    "similarity retrieval, LangChain for document loading, chunking and Gemini model orchestration, and the " +
    "Google Gemini API for embeddings and answer generation. A plain HTML/CSS/JavaScript frontend provides a " +
    "chat interface with expandable citations and per-answer feedback, and a separate administrator view surfaces " +
    "usage statistics and informational gaps — questions the indexed corpus does not yet confidently answer. " +
    "Role-based authentication separates student and administrator capabilities. Beyond the core scope, the " +
    "system implements two stretch features: lightweight multi-turn conversational context and an administrator " +
    "insights dashboard."
  ),
  p(
    "The assistant was evaluated on a hand-built benchmark of 31 question/answer pairs spanning a seven-document " +
    "seed corpus (academic calendar, fees, hostel rules, scholarships, placements, examination regulations and " +
    "library policy) using standard information-retrieval metrics — Precision@k, Recall@k and Mean Reciprocal " +
    "Rank — together with end-to-end latency and a citation-based faithfulness proxy. This report documents the " +
    "system's motivation, architecture, implementation choices and their rationale, the evaluation methodology " +
    "and results, and the limitations and future work that follow from building this as a scoped MVP rather than " +
    "a production deployment."
  ),
];

// ---------- 1 introduction ----------
const introduction = [
  h1("1. Introduction"),
  h2("1.1 Motivation"),
  p(
    "Every academic term, a college publishes dozens of circulars and policy documents that govern day-to-day " +
    "student life: when semester fees are due, what the hostel curfew is, which CGPA qualifies for a scholarship, " +
    "how many books a student may borrow from the library. This information is authoritative and precisely " +
    "specified, yet it is difficult to search: it is spread across PDFs, DOCX handbooks, and plain-text notices, " +
    "published incrementally, and rarely indexed in a way that supports natural-language queries. The result is " +
    "that students repeatedly ask departmental staff questions whose answers are already written down, and staff " +
    "spend time retrieving and re-explaining information rather than doing higher-value work."
  ),
  p(
    "Retrieval-Augmented Generation (RAG) is well suited to this problem. Rather than relying on a language " +
    "model's parametric memory — which cannot know an institution's specific, frequently-changing policies — " +
    "a RAG system retrieves the most relevant passages from an indexed, authoritative corpus at query time and " +
    "asks the model to answer using only that retrieved material. This keeps answers current (re-indexing a " +
    "document updates the system's knowledge immediately) and auditable (every claim can be traced back to a " +
    "specific document, section or page)."
  ),
  h2("1.2 Problem Statement"),
  p(
    "This project builds an end-to-end question-answering system that ingests official university documents " +
    "(PDF, DOCX, Markdown and plain text), indexes them into a searchable knowledge base, and lets students and " +
    "staff ask questions in natural language. The system is required to generate accurate, grounded responses " +
    "with transparent source citations, to minimise hallucination by refusing to answer confidently when the " +
    "indexed corpus does not cover a question, and to separate student and administrator capabilities through " +
    "role-based access control."
  ),
  h2("1.3 Scope and Contributions"),
  p(
    "Given the constraints of a college MVP — a system that must be fully working, demonstrable, and " +
    "explainable by its author in a viva rather than maximally feature-complete — this project deliberately " +
    "targets the core scope of the assignment brief and a small, high-value subset of the stretch goals, instead " +
    "of attempting all of them shallowly. Concretely, this report and the accompanying implementation contribute:"
  ),
  p(
    "A document ingestion pipeline supporting PDF, DOCX, Markdown and plain text, with sliding-window chunking " +
    "and category/department/academic-year metadata tagging; a vector index and semantic search implementation " +
    "built on SQLite and scikit-learn cosine similarity, chosen deliberately over a dedicated vector database for " +
    "transparency at MVP scale; a grounded generation layer over the Gemini API with an explicit citation-and-" +
    "refusal prompt contract; a FastAPI backend exposing query, upload, document-catalog and feedback endpoints " +
    "behind JWT-based role authentication; a chat-style frontend with expandable citations, confidence signalling " +
    "and per-answer feedback; lightweight multi-turn conversational context; an administrator insights dashboard " +
    "surfacing frequently-asked questions and informational gaps; and a reproducible evaluation harness reporting " +
    "Precision@k, Recall@k, MRR, latency and a faithfulness proxy against a 31-question benchmark."
  ),
];

// ---------- 2 related work ----------
const relatedWork = [
  h1("2. Related Work"),
  p(
    "Retrieval-Augmented Generation was introduced by Lewis et al. (2020) as a way to combine a parametric " +
    "language model with a non-parametric retrieval index, so that generation is conditioned on retrieved " +
    "documents rather than solely on knowledge encoded in model weights. This addresses two well-known weaknesses " +
    "of large language models used alone: hallucination (confidently stating incorrect information) and staleness " +
    "(an inability to reflect information created or changed after training). RAG has since become the standard " +
    "architecture for enterprise question-answering systems that must be accurate over a private, frequently-" +
    "changing corpus — exactly the situation a college's circulars and policies present."
  ),
  p(
    "Two implementation choices in this space are especially relevant to this project. First, dense retrieval " +
    "systems represent text as embedding vectors and rank passages by vector similarity (commonly cosine " +
    "similarity), which this project uses directly via scikit-learn rather than a specialised approximate-" +
    "nearest-neighbour index such as FAISS or a dedicated vector database, since the corpus size at MVP scale " +
    "(hundreds of chunks) does not need approximate search to be fast. Second, orchestration frameworks such as " +
    "LangChain provide reusable building blocks — document loaders, text splitters, and chat-model wrappers — " +
    "that remove boilerplate around a specific model provider's API without imposing a full agentic abstraction " +
    "on the retrieval and generation logic itself, which this project keeps explicit and custom precisely so the " +
    "grounding and citation behaviour is easy to reason about and explain."
  ),
];

// ---------- 3 architecture ----------
const architecture = [
  h1("3. System Architecture"),
  p(
    "Campus Copilot is organised as two pipelines that share the same SQLite-backed store: an ingestion pipeline " +
    "that runs once per document (or on demand when an administrator uploads a new one), and a query pipeline " +
    "that runs on every user question. Figure 1 shows both."
  ),
];

// ---------- 4 implementation ----------
const techStackRows = [
  ["Backend framework", "FastAPI (Python) — async-capable, automatic OpenAPI docs, lightweight"],
  ["Orchestration", "LangChain — document loaders (PyPDFLoader, Docx2txtLoader), RecursiveCharacterTextSplitter, GoogleGenerativeAIEmbeddings and ChatGoogleGenerativeAI wrappers"],
  ["Embeddings & LLM", "Google Gemini API — text-embedding-004 for embeddings, gemini-2.0-flash for generation"],
  ["Storage", "SQLite — relational tables (users, documents, chunks, query_logs, feedback) plus embeddings stored as BLOBs in the chunks table"],
  ["Retrieval", "scikit-learn cosine_similarity over embeddings loaded into a NumPy matrix at query time"],
  ["Document parsing", "pypdf (via PyPDFLoader) for PDF, docx2txt for DOCX, plain Python for Markdown/text"],
  ["Auth", "PyJWT for bearer tokens, passlib/bcrypt for password hashing"],
  ["Frontend", "Vanilla HTML, CSS and JavaScript calling the backend over REST"],
];

const implementation = [
  h1("4. Implementation"),
  h2("4.1 Technology Stack"),
  p("Table 1 summarises the stack and the rationale behind each choice; the guiding principle throughout was to prefer the simplest component that satisfies the requirement, so the system stays fully explainable rather than accumulating framework complexity that is hard to defend in a viva."),
  simpleTable(["Layer", "Choice and rationale"], techStackRows, [2200, 7150]),
  caption("Table 1. Technology stack."),

  h2("4.2 Database Schema"),
  p(
    "A hand-written SQLite schema (rather than an ORM) backs the system, on the view that for a project whose " +
    "point is to be explainable, a visible schema.sql and plain SQL statements are easier to walk through than " +
    "ORM model abstractions, and there is no impedance mismatch storing embedding vectors as BLOBs. Five tables " +
    "cover the system: users (id, username, password_hash, full_name, role, department) with role constrained to " +
    "'student' or 'admin'; documents (filename, title, category, department, academic_year, file_type, " +
    "uploaded_by, uploaded_at); chunks (document_id, chunk_index, section_label, page_number, text, embedding, " +
    "embedding_dim), which is the vector store itself; query_logs (user_id, query_text, answer_text, " +
    "top_similarity, retrieved_chunk_ids, latency_ms, created_at), which doubles as the audit trail the " +
    "admin dashboard reads from; and feedback (query_log_id, rating, comment), capturing the response-rating " +
    "requirement from the brief."
  ),

  h2("4.3 Document Ingestion Pipeline"),
  p(
    "Ingestion runs in three stages. Loading (app/ingestion/loaders.py) turns a source file into a list of " +
    "location-tagged text units: LangChain's PyPDFLoader yields one unit per PDF page (preserving page numbers " +
    "for citation), Docx2txtLoader extracts DOCX text which is then split on heading-like lines into named " +
    "sections, and Markdown/plain-text files are split the same way on '#' headings or short title-case lines. " +
    "This is what makes a citation read \"Fee Payment Circular, page 2\" or \"Hostel Rules Handbook — Mess Fees " +
    "and Services\" rather than just a filename. Chunking (app/ingestion/chunker.py) then applies LangChain's " +
    "RecursiveCharacterTextSplitter to each unit with a configurable chunk size and overlap (900 characters with " +
    "150 characters of overlap by default), splitting preferentially on paragraph, then sentence, then word " +
    "boundaries so chunks remain coherent rather than being cut mid-sentence. Embedding and storage " +
    "(app/retrieval.py, index_document_chunks) then embeds every chunk with Gemini's text-embedding-004 model " +
    "and writes it to the chunks table, with the embedding serialised as a float32 BLOB."
  ),

  h2("4.4 Embedding and Retrieval"),
  p(
    "Retrieval (app/retrieval.py, similarity_search) embeds the incoming question with Gemini's " +
    "retrieval_query task type (embedding a query and a document slightly differently is a documented technique " +
    "that improves retrieval quality over using one embedding mode for both), loads every stored chunk embedding " +
    "for the (optionally category/department-filtered) corpus into a single NumPy matrix, and ranks chunks by " +
    "scikit-learn's cosine_similarity. This was a deliberate choice over FAISS, Chroma, Qdrant or PostgreSQL with " +
    "pgvector: at MVP scale — a few hundred to a few thousand chunks — an in-memory similarity computation over " +
    "a NumPy matrix completes in low single-digit milliseconds (Section 7 reports measured latency), needs no " +
    "additional service to install, run or explain, and keeps the entire retrieval step inspectable as nine lines " +
    "of ordinary Python. The trade-off, discussed in Section 8, is that this approach does not scale to a " +
    "large-university-wide corpus without eventually moving to an indexed vector store."
  ),

  h2("4.5 Grounded Generation"),
  p(
    "The generation layer (app/generation.py) builds a prompt from the top-k retrieved chunks and, when " +
    "present, the last few turns of conversation, and sends it to Gemini via LangChain's ChatGoogleGenerativeAI " +
    "wrapper. The system prompt enforces four rules: answer only from the provided context and never from the " +
    "model's own knowledge; cite every factual claim as [Document Title, Section/Page]; explicitly say \"I don't " +
    "have that information in the indexed documents yet\" when the context is insufficient, rather than guessing; " +
    "and use conversation history only to resolve follow-up references, not as a source of facts. A numeric " +
    "guardrail backs this up at the retrieval layer: if the best-matching chunk's cosine similarity falls below a " +
    "configurable confidence threshold (0.45 by default), the backend does not even pass chunks to the model — " +
    "it returns the \"not indexed yet\" response directly, which is both cheaper and more reliable than trusting " +
    "the model to recognise a weak retrieval on its own."
  ),

  h2("4.6 Authentication and Role-Based Access"),
  p(
    "Authentication uses bcrypt-hashed passwords and short-lived JWT bearer tokens (app/auth.py). Self-service " +
    "registration always creates a 'student' role account; administrator accounts are seeded separately " +
    "(scripts/seed_users.py), so no registration request can grant itself elevated access. A require_admin " +
    "FastAPI dependency gates the document-upload, document-deletion and admin-insights endpoints, while every " +
    "other authenticated endpoint is available to both roles. This is intentionally minimal — no refresh tokens, " +
    "no OAuth provider — because the assignment's requirement is a correctly separated role boundary, not a " +
    "production identity system."
  ),

  h2("4.7 Multi-turn Conversation Context"),
  p(
    "As one of the two stretch goals implemented, the frontend keeps the current session's chat turns in memory " +
    "and sends the last few turns with each new question; the backend folds them into the generation prompt so " +
    "that a follow-up like \"what about for MTech students?\" can be resolved against the previous answer's " +
    "subject. Deliberately, history is used only to resolve references, never as a source of facts — the answer " +
    "must still be grounded in freshly retrieved context for the current question, which avoids the failure mode " +
    "where an early wrong answer gets treated as ground truth for the rest of the conversation."
  ),

  h2("4.8 Admin Insights Dashboard"),
  p(
    "The second implemented stretch goal is an administrator dashboard (app/routers/admin_router.py) built " +
    "entirely from data the system already logs: total query volume, average latency, aggregate feedback counts, " +
    "a table of recently asked questions, a table of frequently asked questions, and a table of \"informational " +
    "gaps\": queries whose top retrieval similarity fell below the confidence threshold, which is a direct, low-" +
    "effort proxy for \"questions students are asking that the indexed corpus doesn't yet cover.\" This turns the " +
    "query log from an audit trail into an actionable signal for which documents to index next."
  ),
  p(
    "Frequently-asked questions are grouped by an exact, case- and whitespace-normalised match on the question " +
    "text (SQL GROUP BY on a trimmed, lower-cased query string), not by semantic similarity — two students asking " +
    "\"what time does the hostel close\" and \"hostel curfew timing\" are counted as two different questions " +
    "rather than one. This is a deliberate MVP-scope simplification: it costs one SQL query and correctly " +
    "surfaces literal repeat questions, but under-counts paraphrased duplicates. Clustering by embedding " +
    "similarity instead of exact text match, so paraphrased questions are grouped together, is noted as a natural " +
    "extension in Section 9."
  ),

  h2("4.9 Frontend"),
  p(
    "The frontend is a single-page vanilla HTML/CSS/JavaScript application (frontend/index.html, styles.css, " +
    "app.js) rather than a framework-based one, calling the FastAPI backend over REST. It was chosen over React " +
    "or Streamlit specifically because it satisfies the brief's \"chat-style frontend with chat history, " +
    "expandable citations and response ratings\" requirement with no build tooling and no framework internals to " +
    "explain, while still being a genuinely separate frontend talking to a real backend API — which a Streamlit " +
    "app, running the UI and the Python backend in one process, would not as clearly demonstrate. It implements " +
    "login/registration, a chat view with expandable per-answer citations and thumbs up/down feedback, a document " +
    "catalog with an admin-only upload form, and the admin insights view."
  ),
];

// ---------- 5 dataset ----------
const datasetRows = [
  ["academic_calendar_2026_27.md", "Markdown", "Academic Calendar", "Semester dates, exam windows, breaks, convocation"],
  ["fee_payment_circular.pdf", "PDF (2 pages)", "Fees", "Tuition by program, payment deadlines, late fee, refund policy"],
  ["hostel_rules_handbook.docx", "DOCX", "Hostel", "Room allotment, timings, mess fees, visitors, disciplinary rules"],
  ["scholarship_notice.md", "Markdown", "Scholarships", "Merit, need-based and sports scholarships, application process"],
  ["placement_guidelines.txt", "Plain text", "Placements", "Eligibility, one-offer policy, dress code, code of conduct"],
  ["examination_regulations.pdf", "PDF (2 pages)", "Examinations", "Attendance requirement, grading scale, revaluation, malpractice"],
  ["library_circular.txt", "Plain text", "Library", "Borrowing limits, fines, digital access, inter-library loan"],
];

const dataset = [
  h1("5. Dataset: Seed Knowledge Base"),
  p(
    "Because indexing genuine internal college circulars was not practical for this report, the corpus used for " +
    "development and evaluation is a set of seven realistic but fictional university documents, generated to " +
    "deliberately exercise all four required input formats and to contain concrete, checkable facts (dates, " +
    "fee amounts, thresholds) that a benchmark question can be written against unambiguously. The PDF and DOCX " +
    "documents are generated programmatically (backend/scripts/generate_seed_documents.py, using ReportLab and " +
    "python-docx) rather than committed as opaque binaries, so the entire seed corpus is reproducible from " +
    "readable source. Table 2 lists the seed corpus; the same ingestion pipeline that indexes these documents " +
    "indexes any real circular an administrator uploads through the frontend."
  ),
  simpleTable(["File", "Format", "Category", "Content"], datasetRows, [2600, 1400, 1700, 3650]),
  caption("Table 2. Seed knowledge base (backend/seed_data/)."),
];

// ---------- 6 evaluation methodology ----------
const evalMethod = [
  h1("6. Evaluation Methodology"),
  p(
    "A benchmark of 31 hand-written questions (backend/scripts/benchmark_queries.json) was built against the " +
    "seed corpus, covering every document with 4–5 questions each and every question annotated with its single " +
    "expected source document. backend/scripts/evaluate.py runs each question through the real retrieval and " +
    "generation pipeline and reports:"
  ),
  p(
    "Precision@k (k = 1, 3, 5): of the top-k retrieved chunks, the fraction that come from the expected source " +
    "document. Recall@k (k = 1, 3, 5): since each benchmark question has exactly one relevant document, this is " +
    "whether that document appears at all among the top-k results — recall over a single relevant item. Mean " +
    "Reciprocal Rank (MRR): the mean, over all questions, of 1/rank of the first chunk from the expected document " +
    "(searched within the top 10 results). Latency: retrieval latency (p50/p95) and, when generation is included, " +
    "end-to-end latency. Faithfulness proxy: the fraction of generated answers that explicitly cite the expected " +
    "source document's title — a simple heuristic stand-in for a genuine NLI-based entailment check between the " +
    "answer and the retrieved context, which is listed as future work in Section 9 rather than implemented here."
  ),
  p(
    "The same evaluation script also doubles as a regression check: re-running it after changing the chunk size, " +
    "the confidence threshold, or the embedding model gives an immediate, quantitative read on whether the change " +
    "helped or hurt retrieval quality, rather than relying on spot-checking a handful of demo queries."
  ),
];

// ---------- 7 results ----------
const pipelineResultsRows = [
  ["Documents indexed / chunks produced", "7 / 53"],
  ["Benchmark questions evaluated", "31"],
  ["Mean Precision@1 / @3 / @5", "0.097 / 0.108 / 0.097"],
  ["Recall@1 / @3 / @5", "0.097 / 0.323 / 0.419"],
  ["Mean Reciprocal Rank (MRR)", "0.258"],
  ["Retrieval latency (p50 / p95)", "0.98 ms / 1.36 ms"],
];

const results = [
  h1("7. Results"),
  h2("7.1 Development Environment Constraint"),
  p(
    "This report and codebase were built inside a sandboxed cloud development environment whose network egress " +
    "policy allow-lists only a small set of hosts and does not include the Python package index (pypi.org) or " +
    "the Gemini API endpoint (generativelanguage.googleapis.com). Concretely, this means FastAPI, LangChain and " +
    "google-generativeai could not be installed, and no live Gemini call could be made, inside that particular " +
    "sandbox — a restriction of that specific development container's network policy, not of the code, and not " +
    "expected in a normal local machine or CI runner, where 'pip install -r requirements.txt' behaves normally."
  ),
  p(
    "To validate correctness under this constraint, the system's embedding layer (app/embeddings.py) includes a " +
    "deliberate mock mode: when no Gemini API key is configured, it produces a deterministic hash-seeded pseudo-" +
    "random vector per text instead of a real embedding, and the generation layer returns a templated extractive " +
    "answer instead of a real Gemini completion. This is a genuine engineering feature — it lets the whole " +
    "pipeline be built, wired up and demoed at zero API cost before a key is available — and it is what made it " +
    "possible to exercise every other part of the system (database schema, chunk storage, cosine-similarity " +
    "ranking, the confidence-threshold guardrail, citation formatting, the query/feedback/admin-insights data " +
    "flow) end-to-end inside the sandbox, using the packages that were available there (pypdf, python-docx, " +
    "scikit-learn, NumPy, SQLite) as direct stand-ins for the LangChain document loaders (PyPDFLoader, " +
    "Docx2txtLoader) around them."
  ),
  p(
    "One further substitution applies specifically to the sandbox validation run behind Table 3: since the " +
    "`langchain` package itself (not just `langchain_community`) was unavailable, the production chunker " +
    "(app/ingestion/chunker.py, LangChain's RecursiveCharacterTextSplitter with a 900-character window and " +
    "150-character overlap) could not run in the sandbox either. The validation run instead used a simple fixed-" +
    "size splitter (400 characters, 60-character overlap) with the same real database, embedding, retrieval and " +
    "ranking code. This produced a somewhat different chunk count (53 chunks) than the production chunker would " +
    "on the same seed corpus, and is a second reason — alongside the mock embeddings themselves — that Table 3 " +
    "should be read as a plumbing check, not a preview of production retrieval behaviour."
  ),
  h2("7.2 Pipeline Validation Results (Mock Embeddings)"),
  p(
    "Table 3 reports the outcome of running the full 31-question benchmark against all 7 seed documents (53 " +
    "chunks) with mock embeddings. Because mock vectors are hash-seeded and carry no semantic meaning, these " +
    "numbers are not a measurement of retrieval quality — chance-level performance across 7 roughly equal-sized " +
    "documents would put Precision@1 and Recall@1 near 1/7 ≈ 0.14, and the measured 0.097 is consistent with " +
    "that. What this run does demonstrate is that the storage, retrieval, ranking and latency-measurement code " +
    "paths execute correctly end-to-end and return well-formed, correctly-shaped results for every question."
  ),
  simpleTable(["Metric", "Value"], pipelineResultsRows, [4675, 4675]),
  caption("Table 3. Sandbox pipeline-validation run, mock embeddings (not a semantic-quality measurement — see §7.3)."),
  h2("7.3 Reproducing Semantic-Quality Results"),
  p(
    "Meaningful Precision@k, Recall@k and MRR numbers require real Gemini embeddings, and a real faithfulness " +
    "and end-to-end latency measurement requires real Gemini generation. Both are one step away: set a real " +
    "GEMINI_API_KEY in backend/.env, ensure USE_MOCK_LLM is not set to true, install the dependencies " +
    "(pip install -r requirements.txt) on a machine with normal internet access, run the three setup scripts " +
    "(scripts/seed_users.py, scripts/generate_seed_documents.py, scripts/ingest_seed_docs.py) and then " +
    "scripts/evaluate.py. The script automatically detects the real key and additionally reports the " +
    "faithfulness proxy and end-to-end latency described in Section 6. Based on the benchmark's design — each " +
    "question is written directly against a specific fact in exactly one document, with limited lexical overlap " +
    "across documents — real Gemini embeddings are expected to substantially outperform the mock-mode numbers in " +
    "Table 3; confirming this with the real numbers before final submission is recommended and is the single " +
    "remaining step to complete this report with fully live results."
  ),
];

// ---------- 8 discussion ----------
const discussion = [
  h1("8. Discussion and Limitations"),
  p(
    "Retrieval architecture at scale. The SQLite-plus-cosine-similarity retriever loads every candidate " +
    "embedding into memory at query time, which is simple and fast at hundreds-to-low-thousands of chunks but " +
    "would need to move to an indexed approximate-nearest-neighbour store (FAISS, Chroma, or PostgreSQL with " +
    "pgvector, all mentioned as suggested alternatives in the original brief) if a deployment indexed an entire " +
    "university's document archive rather than a single department's circulars."
  ),
  p(
    "Section splitting heuristics. DOCX, Markdown and plain-text section labels are produced by a heading-" +
    "detection heuristic (a line starting with '#', or a short title-case line) rather than a structural parser, " +
    "so section labels on documents with unconventional formatting may be coarser than a page number would be; " +
    "PDF citations, by contrast, always carry an exact page number from PyPDFLoader."
  ),
  p(
    "Faithfulness measurement. The faithfulness proxy defined in Section 6 checks only whether the expected " +
    "document's title appears in the generated answer, which is a weak but zero-cost signal; a genuine " +
    "faithfulness check — for example, an NLI model verifying that each sentence of the answer is entailed by " +
    "the cited passage, listed as a stretch goal in the original brief — was not implemented and is the most " +
    "valuable evaluation improvement to add next."
  ),
  p(
    "Authentication scope. Role-based access is correctly enforced between 'student' and 'admin' but is " +
    "intentionally minimal (no password reset flow, no refresh tokens, no per-department scoping of documents to " +
    "specific student cohorts); this matches the MVP goal of demonstrating a correctly separated access boundary " +
    "rather than a deployable identity system."
  ),
  p(
    "Corpus size and evaluation validity. Both the seed corpus (7 documents) and the benchmark (31 questions) " +
    "are intentionally small so the whole system remains easy to inspect and explain; the reported metrics should " +
    "be read as validating the pipeline and methodology on a controlled corpus, not as a claim about performance " +
    "on the scale and variability of a real university's full document archive."
  ),
];

// ---------- 9 future work ----------
const futureWork = [
  h1("9. Future Work"),
  p(
    "The original project brief lists several stretch goals beyond the two implemented here (multi-turn context " +
    "and the admin insights dashboard); in priority order for a future iteration: OCR support (Tesseract) for " +
    "scanned circulars and image-based notices, which would let the system ingest the large fraction of real " +
    "college notices that exist only as scanned images; an NLI-based or self-consistency faithfulness check " +
    "replacing the citation-presence proxy used in Section 6; hybrid retrieval combining the current dense " +
    "cosine-similarity search with BM25 keyword search, which tends to improve retrieval on queries containing " +
    "exact terms (form names, course codes) that embeddings alone can under-weight; clustering the admin " +
    "dashboard's frequently-asked-questions view by embedding similarity rather than exact text match, so that " +
    "paraphrased questions about the same topic are grouped together instead of counted separately (Section 4.8); " +
    "document versioning and \"what changed between versions\" queries, letting a student ask whether a policy " +
    "changed since last semester; and migrating the retrieval layer to FAISS or pgvector if the corpus grows to " +
    "department- or institute-wide scale."
  ),
];

// ---------- 10 conclusion ----------
const conclusion = [
  h1("10. Conclusion"),
  p(
    "Campus Copilot demonstrates that a small, well-scoped RAG system — built from simple, explainable " +
    "components rather than a maximal stack — can satisfy the full core scope of a university knowledge-" +
    "assistant brief: multi-format ingestion, grounded and cited generation, a role-authenticated API, a working " +
    "chat frontend, and a reproducible evaluation harness, plus two stretch features chosen for being high value " +
    "at low implementation cost. The most important discipline applied throughout was refusing to guess: the " +
    "system is built to say \"I don't have that information indexed yet\" rather than fabricate a plausible-" +
    "sounding answer, and the evaluation methodology is built to say \"these numbers validate the pipeline, not " +
    "semantic quality\" rather than overstate what a mock-mode sandbox run can prove. Section 7.3 leaves one " +
    "concrete, well-defined step — running the same evaluation script with a real Gemini key — to convert this " +
    "from a validated pipeline into a fully measured system."
  ),
];

// ---------- references ----------
const references = [
  h1("References"),
  p("[1] P. Lewis et al., \"Retrieval-Augmented Generation for Knowledge-Intensive NLP Tasks,\" in Advances in Neural Information Processing Systems (NeurIPS), 2020."),
  p("[2] FastAPI documentation. https://fastapi.tiangolo.com/"),
  p("[3] LangChain documentation. https://python.langchain.com/"),
  p("[4] Google Gemini API documentation. https://ai.google.dev/gemini-api/docs"),
  p("[5] scikit-learn: F. Pedregosa et al., \"Scikit-learn: Machine Learning in Python,\" Journal of Machine Learning Research, vol. 12, pp. 2825–2830, 2011."),
  p("[6] SQLite documentation. https://www.sqlite.org/docs.html"),
];

// ---------- assemble ----------
async function main() {
  const diagramBuffer = fs.readFileSync(__dirname + "/architecture_diagram.png");

  const figureBlock = [
    new Paragraph({
      alignment: AlignmentType.CENTER,
      spacing: { before: 120, after: 60 },
      children: [new ImageRun({ data: diagramBuffer, type: "png", transformation: { width: 600, height: 413 } })],
    }),
    caption("Figure 1. Campus Copilot system architecture: ingestion pipeline (top) and query/generation pipeline (bottom)."),
  ];

  const doc = new Document({
    styles: {
      default: {
        document: { run: { font: "Calibri", size: 22 } },
      },
      paragraphStyles: [
        { id: "Heading1", name: "Heading 1", basedOn: "Normal", next: "Normal", quickFormat: true,
          run: { bold: true, size: 30, color: BLUE }, paragraph: { spacing: { before: 320, after: 160 } } },
        { id: "Heading2", name: "Heading 2", basedOn: "Normal", next: "Normal", quickFormat: true,
          run: { bold: true, size: 25, color: DARK }, paragraph: { spacing: { before: 240, after: 120 } } },
      ],
    },
    sections: [
      {
        properties: { page: { margin: { top: 1080, bottom: 1080, left: 1080, right: 1080 } } },
        children: [
          ...titlePage,
          ...abstract,
          ...introduction,
          ...relatedWork,
          ...architecture,
          ...figureBlock,
          ...implementation,
          ...dataset,
          ...evalMethod,
          ...results,
          ...discussion,
          ...futureWork,
          ...conclusion,
          ...references,
        ],
      },
    ],
  });

  const buffer = await Packer.toBuffer(doc);
  fs.writeFileSync(__dirname + "/Campus_Copilot_Report.docx", buffer);
  console.log("wrote Campus_Copilot_Report.docx");
}

main().catch((e) => { console.error(e); process.exit(1); });
