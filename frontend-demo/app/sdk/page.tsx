export default function SdkPage() {
  return (
    <div className="max-w-[720px] mx-auto px-4 py-10 text-foreground text-[1rem] leading-[1.8]">

      {/* Header */}
      <div className="mb-12">
        <p className="font-mono text-[0.78rem] uppercase tracking-[2px] text-accent mb-3">
          Python SDK
        </p>
        <h1 className="text-foreground text-3xl font-semibold mb-4">
          ChatVector Python Client
        </h1>
        <p className="text-muted text-[1rem] leading-[1.8]">
          A lightweight Python client for uploading documents, polling ingestion status,
          and querying the ChatVector RAG backend over HTTP.
        </p>
      </div>

      {/* Requirements */}
      <section className="mb-10">
        <p className="font-mono text-[0.78rem] uppercase tracking-[2px] text-accent mb-4">
          Requirements
        </p>
        <ul className="list-disc list-inside space-y-1">
          <li>Python 3.10 or higher</li>
          <li>
            <code className="bg-surface border border-border rounded-xl font-mono text-[0.82rem] px-2 py-0.5">
              httpx
            </code>{" "}
            (installed automatically as a dependency)
          </li>
          <li>A running ChatVector backend at a reachable URL</li>
        </ul>
      </section>

      {/* Installation */}
      <section className="mb-10">
        <p className="font-mono text-[0.78rem] uppercase tracking-[2px] text-accent mb-4">
          Installation
        </p>
        <p className="mb-3">Install directly from the repo:</p>
        <pre className="bg-surface border border-border rounded-xl font-mono text-[0.82rem] p-4 overflow-x-auto">
          <code>pip install ./sdk/python</code>
        </pre>
      </section>

      {/* Quickstart */}
      <section className="mb-10">
        <p className="font-mono text-[0.78rem] uppercase tracking-[2px] text-accent mb-4">
          Quickstart
        </p>
        <p className="mb-3">
          Upload a document, wait for ingestion to complete, then ask a question:
        </p>
        <pre className="bg-surface border border-border rounded-xl font-mono text-[0.82rem] p-4 overflow-x-auto">
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
        </pre>
      </section>

      {/* Authentication */}
      <section className="mb-10">
        <p className="font-mono text-[0.78rem] uppercase tracking-[2px] text-accent mb-4">
          Authentication
        </p>
        <p className="mb-3">
          If your backend is configured with a bearer token, pass it at client initialization:
        </p>
        <pre className="bg-surface border border-border rounded-xl font-mono text-[0.82rem] p-4 overflow-x-auto">
          <code>{`client = ChatVectorClient(
    base_url="http://localhost:8000",
    api_key="your-bearer-token"
)`}</code>
        </pre>
        <p className="mt-3 text-muted">
          The token is optional. Omit it if your backend does not require authentication.
        </p>
      </section>

      {/* Error Handling */}
      <section className="mb-10">
        <p className="font-mono text-[0.78rem] uppercase tracking-[2px] text-accent mb-4">
          Error Handling
        </p>
        <p className="mb-4">
          The client raises typed exceptions so you can handle failures cleanly:
        </p>
        <div className="space-y-3">
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
              <code className="bg-surface border border-border rounded-xl font-mono text-[0.82rem] px-2 py-0.5 shrink-0 self-start">
                {name}
              </code>
              <span>{desc}</span>
            </div>
          ))}
        </div>

        <pre className="mt-5 bg-surface border border-border rounded-xl font-mono text-[0.82rem] p-4 overflow-x-auto">
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
        </pre>
      </section>

      {/* Examples */}
      <section className="mb-10">
        <p className="font-mono text-[0.78rem] uppercase tracking-[2px] text-accent mb-4">
          Examples
        </p>
        <p className="mb-4">
          More complete usage examples are available in the repository:
        </p>
        <ul className="space-y-2">
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
                className="bg-surface border border-border rounded-xl font-mono text-[0.82rem] px-2 py-0.5 shrink-0 self-start text-accent underline underline-offset-4 hover:opacity-80 transition-opacity"
              >
                {file}
              </a>
              <span>{desc}</span>
            </li>
          ))}
        </ul>
      </section>

      {/* Footer link */}
      <p className="mt-16 text-sm text-muted border-t border-border pt-6">
        For full SDK details, see the{" "}
        <a
          href="https://github.com/chatvector-ai/chatvector-ai/blob/main/sdk/python/README.md"
          target="_blank"
          rel="noopener noreferrer"
          className="text-accent underline underline-offset-4 hover:opacity-80 transition-opacity"
        >
          SDK README on GitHub
        </a>
        .
      </p>
    </div>
  );
}