import { DocLayout } from "@/app/components/DocLayout";
import { DocPageHeader } from "@/app/components/DocPageHeader";
import { Kicker } from "@/app/components/Kicker";
import CodeBlock from "../components/CodeBlock";
import { SYNTAX } from "../lib/constants";

export default function SdkPage() {
  const upload_chat_codeLines = [
  {
    parts: [
      { c: SYNTAX.kw, t: "from " },
      { c: SYNTAX.plain, t: "chatvector " },
      { c: SYNTAX.kw, t: "import " },
      { c: SYNTAX.fn, t: "ChatVectorClient" },
    ],
  },
  { parts: [{ c: SYNTAX.plain, t: " " }] },
  {
    parts: [
      { c: SYNTAX.kw, t: "with " },
      { c: SYNTAX.fn, t: "ChatVectorClient" },
      { c: SYNTAX.plain, t: "(" },
      { c: SYNTAX.str, t: '"http://localhost:8000"' },
      { c: SYNTAX.plain, t: ")" },
      { c: SYNTAX.kw, t: " as " },
      { c: SYNTAX.plain, t: "client:" },
    ],
  },
  {
    parts: [{ c: SYNTAX.cm, t: "    # Upload a document" }],
  },
  {
    parts: [
      { c: SYNTAX.plain, t: "    doc = client." },
      { c: SYNTAX.fn, t: "upload_document" },
      { c: SYNTAX.plain, t: "(" },
      { c: SYNTAX.str, t: '"report.pdf"' },
      { c: SYNTAX.plain, t: ")" },
    ],
  },
  { parts: [{ c: SYNTAX.plain, t: " " }] },
  {
    parts: [{ c: SYNTAX.cm, t: "    # Wait until the document is ready to query" }],
  },
  {
    parts: [
      { c: SYNTAX.plain, t: "    client." },
      { c: SYNTAX.fn, t: "wait_for_ready" },
      { c: SYNTAX.plain, t: "(doc.document_id, timeout=90)" },
    ],
  },
  { parts: [{ c: SYNTAX.plain, t: " " }] },
  {
    parts: [{ c: SYNTAX.cm, t: "    # Ask a question" }],
  },
  {
    parts: [
      { c: SYNTAX.plain, t: "    answer = client." },
      { c: SYNTAX.fn, t: "chat" },
      { c: SYNTAX.plain, t: "(" },
      { c: SYNTAX.str, t: '"What are the key findings?"' },
      { c: SYNTAX.plain, t: ", doc.document_id)" },
    ],
  },
  { parts: [{ c: SYNTAX.plain, t: " " }] },
  {
    parts: [{ c: SYNTAX.plain, t: "    print(answer.answer)" }],
  },
  { parts: [{ c: SYNTAX.plain, t: " " }] },
  {
    parts: [{ c: SYNTAX.cm, t: "    # Print cited sources" }],
  },
  {
    parts: [
      { c: SYNTAX.kw, t: "    for " },
      { c: SYNTAX.plain, t: "source " },
      { c: SYNTAX.kw, t: "in " },
      { c: SYNTAX.plain, t: "answer.sources:" },
    ],
  },
  {
    parts: [
      { c: SYNTAX.plain, t: "        print(source.file_name, source.page_number)" },
    ],
  },
];
  const error_handling_codeLines = [
  {
    parts: [
      { c: SYNTAX.kw, t: "from " },
      { c: SYNTAX.plain, t: "chatvector.exceptions " },
      { c: SYNTAX.kw, t: "import (" },
    ],
  },
  { parts: [{ c: SYNTAX.fn, t: "    ChatVectorAPIError," }] },
  { parts: [{ c: SYNTAX.fn, t: "    ChatVectorAuthError," }] },
  { parts: [{ c: SYNTAX.fn, t: "    ChatVectorRateLimitError," }] },
  { parts: [{ c: SYNTAX.fn, t: "    ChatVectorTimeoutError," }] },
  { parts: [{ c: SYNTAX.plain, t: ")" }] },
  { parts: [{ c: SYNTAX.plain, t: " " }] },
  { parts: [{ c: SYNTAX.kw, t: "try:" }] },
  {
    parts: [
      { c: SYNTAX.plain, t: "    doc = client." },
      { c: SYNTAX.fn, t: "upload_document" },
      { c: SYNTAX.plain, t: '("report.pdf")' },
    ],
  },
  {
    parts: [
      { c: SYNTAX.plain, t: "    client." },
      { c: SYNTAX.fn, t: "wait_for_ready" },
      { c: SYNTAX.plain, t: "(doc.document_id, timeout=60)" },
    ],
  },
  {
    parts: [
      { c: SYNTAX.plain, t: "    answer = client." },
      { c: SYNTAX.fn, t: "chat" },
      { c: SYNTAX.plain, t: '("Summarise the document.", doc.document_id)' },
    ],
  },
  {
    parts: [
      { c: SYNTAX.kw, t: "except " },
      { c: SYNTAX.fn, t: "ChatVectorAuthError" },
      { c: SYNTAX.plain, t: ":" },
    ],
  },
  {
    parts: [{ c: SYNTAX.plain, t: '    print("Authentication failed. Check your api_key.")' }],
  },
  {
    parts: [
      { c: SYNTAX.kw, t: "except " },
      { c: SYNTAX.fn, t: "ChatVectorRateLimitError" },
      { c: SYNTAX.plain, t: ":" },
    ],
  },
  {
    parts: [{ c: SYNTAX.plain, t: '    print("Rate limit hit. Wait and retry.")' }],
  },
  {
    parts: [
      { c: SYNTAX.kw, t: "except " },
      { c: SYNTAX.fn, t: "ChatVectorTimeoutError" },
      { c: SYNTAX.plain, t: ":" },
    ],
  },
  {
    parts: [{ c: SYNTAX.plain, t: '    print("Document took too long to process.")' }],
  },
  {
    parts: [
      { c: SYNTAX.kw, t: "except " },
      { c: SYNTAX.fn, t: "ChatVectorAPIError" },
      { c: SYNTAX.plain, t: " as e:" },
    ],
  },
  {
    parts: [{ c: SYNTAX.plain, t: '    print("SDK error:", e)' }],
  },
];
  return (
    <DocLayout>
      <div className="text-[1rem] leading-[1.8] text-foreground">
        <DocPageHeader
          kicker="python sdk"
          title="ChatVector Python Client"
          description="A lightweight Python client for uploading documents, polling ingestion status, and querying the ChatVector RAG backend over HTTP."
        />

        <div className="mt-12 space-y-10">
          <section>
            <Kicker spacing="lg">requirements</Kicker>
            <ul className="list-inside list-disc space-y-1 text-foreground/90">
              <li>Python 3.10 or higher</li>
              <li>
                <code className="rounded-xl border border-border bg-surface px-2 py-0.5 font-mono text-[0.82rem]">
                  httpx
                </code>{" "}
                (installed automatically as a dependency)
              </li>
              <li>A running ChatVector backend at a reachable URL</li>
            </ul>
          </section>

          <section>
            <Kicker spacing="lg">installation</Kicker>
            <p className="mb-3 text-foreground/90">
              Install directly from the repo:
            </p>
            <CodeBlock code="pip install ./sdk/python" language="bash" />
          </section>

          <section>
            <Kicker spacing="lg">quickstart</Kicker>
            <p className="mb-3 text-foreground/90">
              Upload a document, wait for ingestion to complete, then ask a
              question:
            </p>
            <CodeBlock language="python" filename="upload_and_chat.py">
             {upload_chat_codeLines.map((line, i) => (
              <div key={i}>
                {line.parts.map((p, j) => (
                  <span key={j} style={{ color: p.c }}>
                    {p.t}
                  </span>
                ))}
              </div>
            ))}
            </CodeBlock>
          </section>

          <section>
            <Kicker spacing="lg">authentication</Kicker>
            <p className="mb-3 text-foreground/90">
              If your backend is configured with a bearer token, pass it at
              client initialization:
            </p>
            <CodeBlock
              code={`client = ChatVectorClient(
    base_url="http://localhost:8000",
    api_key="your-bearer-token"
)`}
              language="python"
            />
            <p className="mt-3 text-foreground/90">
              The token is optional. Omit it if your backend does not require
              authentication.
            </p>
          </section>

          <section>
            <Kicker spacing="lg">error handling</Kicker>
            <p className="mb-4 text-foreground/90">
              The client raises typed exceptions so you can handle failures
              cleanly:
            </p>
            <div className="space-y-3 text-foreground/90">
              {[
                {
                  name: "ChatVectorAPIError",
                  desc: "Base exception for all SDK errors. Catch this to handle any client error in one place.",
                },
                {
                  name: "ChatVectorAuthError",
                  desc: "Raised when the request is rejected due to missing or invalid authentication credentials.",
                },
                {
                  name: "ChatVectorRateLimitError",
                  desc: "Raised when the backend returns a rate limit response. Back off and retry after a delay.",
                },
                {
                  name: "ChatVectorTimeoutError",
                  desc: "Raised by wait_for_ready when the document does not reach a ready state within the timeout window.",
                },
              ].map(({ name, desc }) => (
                <div key={name} className="flex gap-3">
                  <code className="shrink-0 self-start rounded-xl border border-border bg-surface px-2 py-0.5 font-mono text-[0.82rem]">
                    {name}
                  </code>
                  <span>{desc}</span>
                </div>
              ))}
            </div>
            <div className="mt-5">
              <CodeBlock language="python" filename="error_handling.py">
                {error_handling_codeLines.map((line, i) => (
              <div key={i}>
                {line.parts.map((p, j) => (
                  <span key={j} style={{ color: p.c }}>
                    {p.t}
                  </span>
                ))}
              </div>
            ))}
              </CodeBlock>
            </div>
          </section>

          <section>
            <Kicker spacing="lg">examples</Kicker>
            <p className="mb-4 text-foreground/90">
              More complete usage examples are available in the repository:
            </p>
            <ul className="space-y-2 text-foreground/90">
              {[
                {
                  file: "upload_wait_chat.py",
                  href: "https://github.com/chatvector-ai/chatvector-ai/blob/main/sdk/python/examples/upload_wait_chat.py",
                  desc: "Full end-to-end flow: upload, wait, chat, print sources.",
                },
                {
                  file: "check_status.py",
                  href: "https://github.com/chatvector-ai/chatvector-ai/blob/main/sdk/python/examples/check_status.py",
                  desc: "Poll document status and inspect each ingestion stage.",
                },
                {
                  file: "batch_chat.py",
                  href: "https://github.com/chatvector-ai/chatvector-ai/blob/main/sdk/python/examples/batch_chat.py",
                  desc: "Send multiple questions against the same document in sequence.",
                },
              ].map(({ file, href, desc }) => (
                <li key={file} className="flex gap-3">
                  <a
                    href={href}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="shrink-0 self-start rounded-xl border border-border bg-surface px-2 py-0.5 font-mono text-[0.82rem] text-accent underline underline-offset-4 transition-opacity hover:opacity-80"
                  >
                    {file}
                  </a>
                  <span>{desc}</span>
                </li>
              ))}
            </ul>
          </section>
        </div>

        <p className="mt-16 border-t border-border pt-6 text-sm text-foreground/80">
          For full SDK details, see the{" "}
          <a
            href="https://github.com/chatvector-ai/chatvector-ai/blob/main/sdk/python/README.md"
            target="_blank"
            rel="noopener noreferrer"
            className="text-accent underline underline-offset-4 transition-opacity hover:opacity-80"
          >
            SDK README on GitHub
          </a>
          .
        </p>
      </div>
    </DocLayout>
  );
}
