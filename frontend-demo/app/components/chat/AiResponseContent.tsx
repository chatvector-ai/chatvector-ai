import { Component, type ReactNode } from "react";
import ReactMarkdown from "react-markdown";
import rehypeSanitize from "rehype-sanitize";
import remarkGfm from "remark-gfm";
import {
  softFailureMessage,
  type ChatSource,
  type RetrievalDebugMetadata,
} from "../../lib/api";
import {
  formatCitationSummary,
  formatResponseMetadata,
} from "../../lib/citations";
import RetrievalInspector from "../RetrievalInspector";
import { InlineAlert } from "../ui/InlineAlert";

const remarkPlugins = [remarkGfm];
const rehypePlugins = [rehypeSanitize];

// rehype-sanitize drops raw HTML and unsafe URL protocols.
// disallowedElements rejects script-like tags if a plugin promotes them to elements.
const disallowedElements = ["script", "iframe", "object", "embed", "style"];

function StreamingCursor() {
  return (
    <span className="inline-block w-[2px] h-[1em] bg-accent animate-pulse ml-0.5 align-text-bottom" />
  );
}

type MarkdownBoundaryProps = {
  text: string;
  children: ReactNode;
};

type MarkdownBoundaryState = {
  hasError: boolean;
  failedText: string | null;
};

// A partial token slice can fail to parse. Show that slice as text and retry
// on the next update so a finished answer is not stuck as plain text.
class MarkdownRenderBoundary extends Component<
  MarkdownBoundaryProps,
  MarkdownBoundaryState
> {
  state: MarkdownBoundaryState = { hasError: false, failedText: null };

  static getDerivedStateFromError(): Partial<MarkdownBoundaryState> {
    return { hasError: true };
  }

  static getDerivedStateFromProps(
    props: MarkdownBoundaryProps,
    state: MarkdownBoundaryState
  ): Partial<MarkdownBoundaryState> | null {
    if (
      state.hasError &&
      state.failedText !== null &&
      props.text !== state.failedText
    ) {
      return { hasError: false, failedText: null };
    }
    return null;
  }

  componentDidCatch() {
    this.setState({ failedText: this.props.text });
  }

  render() {
    if (this.state.hasError) {
      return (
        <span className="whitespace-pre-wrap break-words">{this.props.text}</span>
      );
    }
    return this.props.children;
  }
}

function AssistantMarkdown({
  text,
  className,
  isStreaming,
}: {
  text: string;
  className?: string;
  isStreaming: boolean;
}) {
  const classes = [
    "assistant-markdown",
    isStreaming ? "assistant-markdown-streaming" : "",
    className,
  ]
    .filter(Boolean)
    .join(" ");

  return (
    <div className={classes}>
      <MarkdownRenderBoundary text={text}>
        <ReactMarkdown
          remarkPlugins={remarkPlugins}
          rehypePlugins={rehypePlugins}
          disallowedElements={disallowedElements}
        >
          {text}
        </ReactMarkdown>
      </MarkdownRenderBoundary>
      {isStreaming ? <StreamingCursor /> : null}
    </div>
  );
}

export type AiResponseContentProps = {
  text?: string;
  error?: { code: string; message: string };
  sources?: ChatSource[];
  chunks?: number;
  model?: string;
  latencyMs?: number;
  question?: string;
  retrievalDebug?: RetrievalDebugMetadata;
  /** When false, hide error, zero-chunks, metadata, and inspector. */
  detailsVisible?: boolean;
  /** Show a blinking cursor after text while tokens are in flight. */
  isStreaming?: boolean;
  /** Shown when there is no text and streaming is not active. */
  emptyMessage?: string;
  /** Shown when chunks === 0 and showZeroChunks is true. */
  zeroChunksMessage?: string;
  showZeroChunks?: boolean;
  textClassName?: string;
  citationClassName?: string;
  metadataClassName?: string;
  zeroChunksClassName?: string;
  emptyMessageClassName?: string;
};

export default function AiResponseContent({
  text,
  error,
  sources,
  chunks,
  model,
  latencyMs,
  question,
  retrievalDebug,
  detailsVisible = true,
  isStreaming = false,
  emptyMessage,
  zeroChunksMessage = "No relevant content found in this document.",
  showZeroChunks = true,
  textClassName = "",
  citationClassName = "mt-2 text-xs text-muted",
  metadataClassName = "mt-2 text-xs text-muted",
  zeroChunksClassName = "mt-1 text-sm text-muted italic",
  emptyMessageClassName = "text-sm text-muted italic",
}: AiResponseContentProps) {
  const citationSummary = formatCitationSummary(sources);
  const metadata = formatResponseMetadata({
    chunks,
    model,
    latency_ms: latencyMs,
  });

  return (
    <>
      {error && detailsVisible && (
        <div className="mb-2">
          <InlineAlert>{softFailureMessage(error)}</InlineAlert>
        </div>
      )}
      {text ? (
        <AssistantMarkdown
          text={text}
          className={textClassName || undefined}
          isStreaming={isStreaming}
        />
      ) : isStreaming ? (
        <span className="text-muted animate-pulse">Streaming...</span>
      ) : emptyMessage ? (
        <p className={emptyMessageClassName}>{emptyMessage}</p>
      ) : null}
      {showZeroChunks && chunks === 0 && detailsVisible && (
        <p className={zeroChunksClassName}>{zeroChunksMessage}</p>
      )}
      {citationSummary && detailsVisible && (
        <p className={citationClassName}>{citationSummary}</p>
      )}
      {metadata && detailsVisible && (
        <p className={metadataClassName}>{metadata}</p>
      )}
      {detailsVisible && (
        <RetrievalInspector
          data={{
            question,
            retrieval_debug: retrievalDebug,
            sources,
            chunks,
            model,
            latency_ms: latencyMs,
          }}
        />
      )}
    </>
  );
}
