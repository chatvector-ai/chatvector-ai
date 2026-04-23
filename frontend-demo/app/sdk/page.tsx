import { DocLayout } from "@/app/components/DocLayout";
import { DocPageHeader } from "@/app/components/DocPageHeader";
import { Kicker } from "@/app/components/Kicker";

import CodeBlock from "../components/CodeBlock";

export default function SdkPage() {
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
              <code>{`from chatvector import ChatVectorClient

with ChatVectorClient("http://localhost:8000") as client:
    # Upload a document
    doc = client.upload_document("report.pdf")

    # Wait until the document is ready to query
    client.wait_for_ready(doc.document_id, timeout=90)

    # Ask a question
    answer = client.chat("What are the key findings?", doc.document_id)

    print(answer.answer)

    # Print cited sources
    for source in answer.sources:
        print(source.file_name, source.page_number)`}</code>
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
                <code>{`from chatvector.exceptions import (
    ChatVectorAPIError,
    ChatVectorAuthError,
    ChatVectorRateLimitError,
    ChatVectorTimeoutError,
)

try:
    doc = client.upload_document("report.pdf")
    client.wait_for_ready(doc.document_id, timeout=60)
    answer = client.chat("Summarise the document.", doc.document_id)
except ChatVectorAuthError:
    print("Authentication failed. Check your api_key.")
except ChatVectorRateLimitError:
    print("Rate limit hit. Wait and retry.")
except ChatVectorTimeoutError:
    print("Document took too long to process.")
except ChatVectorAPIError as e:
    print("SDK error:", e)`}</code>
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
