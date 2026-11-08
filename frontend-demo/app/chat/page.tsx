"use client";

import { useState, useRef, useEffect, useMemo } from "react";
import { PanelLeft } from "lucide-react";
import UploadModal from "../components/UploadModal";
import MessageList from "../components/chat/MessageList";
import ChatInput from "../components/chat/ChatInput";
import SessionDocumentList from "../components/chat/SessionDocumentList";
import SessionSidebar from "../components/chat/SessionSidebar";
import AdvancedRetrievalDrawer from "../components/AdvancedRetrievalDrawer";
import { InlineAlert } from "../components/ui/InlineAlert";
import { useChat } from "../lib/hooks/useChat";
import { useAdvancedRetrieval } from "../lib/hooks/useAdvancedRetrieval";
import { useSessionManager } from "../lib/hooks/useSessionManager";
import {
  effectiveScope,
  hasActiveMetadataFilter,
  resolveScopeIndicator,
} from "../lib/advancedRetrieval";
import { formatMetadataPair } from "../lib/documentMetadata";
import {
  metadataCorpusForSessionDocuments,
  metadataCorpusFromDocumentList,
} from "../lib/metadataCorpus";
import {
  deleteDocument,
  fetchRetrievalDiscovery,
  getSession,
  listDocuments,
  type DocumentSummary,
  type RetrievalDiscoveryResponse,
} from "../lib/api";

export default function ChatPage() {
  const [showModal, setShowModal] = useState(false);
  const [mobileSessionsOpen, setMobileSessionsOpen] = useState(false);
  const [inspectMode, setInspectMode] = useState(false);
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [discovery, setDiscovery] = useState<RetrievalDiscoveryResponse>({
    presets: [],
    reranker_providers: ["similarity"],
  });
  const [documentSummaries, setDocumentSummaries] = useState<DocumentSummary[]>([]);
  const [sessionDocumentIds, setSessionDocumentIds] = useState<string[]>([]);
  const [documentsRefreshKey, setDocumentsRefreshKey] = useState(0);
  const [replaceDocumentIdFromList, setReplaceDocumentIdFromList] = useState<
    string | null
  >(null);
  const uploadButtonRef = useRef<HTMLButtonElement>(null);
  const {
    sessions,
    activeSessionId,
    createNewSession,
    switchSession,
    deleteSession,
    isLoaded,
    error: sessionError,
    isCreating,
    deletingSessionId,
    noteUserQuestion,
    noteDocumentAttached,
    noteSessionHistory,
  } = useSessionManager();
  const {
    state: retrievalState,
    loaded: retrievalLoaded,
    setScope,
    setMatchCount,
    setHybridEnabled,
    setRerankingEnabled,
    setRerankerProvider,
    setQueryTransformationEnabled,
    setQueryTransformationStrategy,
    setHistoryAwareRetrieval,
    setRetrievalHistoryWindow,
    setGenerationHistoryWindow,
    setMetadataFilter,
    setPreset,
  } = useAdvancedRetrieval();

  useEffect(() => {
    if (!drawerOpen) return;
    void fetchRetrievalDiscovery().then(setDiscovery);
  }, [drawerOpen]);

  const {
    messages,
    historyLoading,
    input,
    setInput,
    inflight,
    streaming,
    attachment,
    sessionNotice,
    removeError,
    sendDisabled,
    bottomRef,
    poll,
    handleSend,
    handleKeyDown,
    handleUploadAccepted,
    handleRemoveAttachment,
    stopStreaming,
  } = useChat(
    activeSessionId,
    retrievalState,
    {
      onUserQuestion: noteUserQuestion,
      onDocumentAttached: noteDocumentAttached,
      onHistoryLoaded: noteSessionHistory,
    },
    inspectMode,
  );

  const attachedDocumentId = attachment?.documentId;
  const attachedDocumentStatus = attachment?.status;

  useEffect(() => {
    let cancelled = false;

    void (async () => {
      const [documentsResult, sessionResult] = await Promise.all([
        listDocuments().catch(() => null),
        activeSessionId
          ? getSession(activeSessionId).catch(() => null)
          : Promise.resolve(null),
      ]);

      if (cancelled) return;

      setDocumentSummaries(documentsResult?.documents ?? []);
      setSessionDocumentIds(sessionResult?.document_ids ?? []);
    })();

    return () => {
      cancelled = true;
    };
  }, [activeSessionId, attachedDocumentId, attachedDocumentStatus, documentsRefreshKey]);

  const refreshSessionDocuments = () => {
    setDocumentsRefreshKey((key) => key + 1);
  };

  const resolvedReplaceDocumentId =
    replaceDocumentIdFromList ??
    (attachment && attachment.status !== "processing"
      ? attachment.documentId
      : null);

  const handleReplaceDocument = (documentId: string) => {
    setReplaceDocumentIdFromList(documentId);
    setShowModal(true);
  };

  const handleDeleteListedDocument = async (documentId: string) => {
    if (attachment?.documentId === documentId) {
      await handleRemoveAttachment();
      refreshSessionDocuments();
      return;
    }
    try {
      const out = await deleteDocument(documentId);
      if (out.status === "gone") {
        refreshSessionDocuments();
      }
    } catch {
      // Row actions are best-effort; chip removeError covers the active attachment.
    }
  };

  const indicatorScope = effectiveScope(retrievalState);
  const scopeIndicator = resolveScopeIndicator(
    retrievalState,
    attachment?.fileName
  );
  const metadataCorpus = useMemo(() => {
    if (indicatorScope === "tenant") {
      return metadataCorpusFromDocumentList(documentSummaries);
    }
    return metadataCorpusForSessionDocuments(
      sessionDocumentIds,
      documentSummaries
    );
  }, [indicatorScope, documentSummaries, sessionDocumentIds]);

  const metadataFilterSummary = useMemo(() => {
    if (!hasActiveMetadataFilter(retrievalState)) return null;
    const filter = retrievalState.explicit.metadataFilter;
    if (!filter) return null;
    const entries = Object.entries(filter);
    if (entries.length !== 1) return null;
    const [key, value] = entries[0];
    return formatMetadataPair(key, value);
  }, [retrievalState]);

  if (!isLoaded || !retrievalLoaded) {
    return (
      <div
        className="flex min-h-0 w-full flex-1 overflow-hidden bg-background text-foreground"
        style={{
          height: "calc(100dvh - 60px)",
          maxHeight: "calc(100dvh - 60px)",
        }}
        aria-busy="true"
      >
        <div className="w-64 border-r border-border bg-surface hidden md:flex flex-col animate-pulse">
          <div className="p-4 border-b border-border">
            <div className="h-10 w-full rounded-lg bg-border" />
          </div>
          <div className="flex-1 p-2 space-y-1">
            {Array.from({ length: 5 }).map((_, i) => (
              <div
                key={i}
                className="h-9 w-full rounded-md bg-border"
              />
            ))}
          </div>
        </div>

        <div className="flex-1 flex flex-col overflow-hidden min-h-0 animate-pulse">
          <div className="mx-auto flex min-h-0 w-full max-w-3xl flex-1 flex-col overflow-hidden p-4">
            <div className="flex-1 space-y-4 py-4">
              <div className="flex justify-start">
                <div className="h-16 w-72 rounded-xl border border-border bg-surface" />
              </div>
              <div className="flex justify-end">
                <div className="h-12 w-56 rounded-xl border border-border bg-surface" />
              </div>
              <div className="flex justify-start">
                <div className="h-20 w-80 rounded-xl border border-border bg-surface" />
              </div>
            </div>

            <div className="shrink-0 space-y-3 pt-2">
              <div className="h-4 w-48 rounded bg-border" />
              <div className="flex items-end gap-2 rounded-xl border border-border bg-surface px-4 py-3">
                <div className="h-5 w-5 rounded bg-border" />
                <div className="flex-1 h-5 rounded bg-border" />
                <div className="h-8 w-8 rounded-lg bg-border" />
              </div>
            </div>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div
      className="relative flex min-h-0 w-full flex-1 overflow-hidden bg-background text-foreground"
      style={{
        height: "calc(100dvh - 60px)",
        maxHeight: "calc(100dvh - 60px)",
      }}
    >
      <SessionSidebar
        id="chat-session-sidebar"
        sessions={sessions}
        activeSessionId={activeSessionId}
        onCreateSession={createNewSession}
        onSwitchSession={switchSession}
        onDeleteSession={deleteSession}
        isCreating={isCreating}
        deletingSessionId={deletingSessionId}
        isOpen={mobileSessionsOpen}
        onClose={() => setMobileSessionsOpen(false)}
      />

      <div className="flex-1 flex flex-col overflow-hidden min-h-0">
        <h1 className="sr-only">Chat with your documents</h1>
        <div className="flex items-center border-b border-border bg-surface px-4 py-2 md:hidden">
          <button
            type="button"
            aria-expanded={mobileSessionsOpen}
            aria-controls="chat-session-sidebar"
            onClick={() => setMobileSessionsOpen((prev) => !prev)}
            className="inline-flex items-center gap-2 rounded-lg border border-border bg-background px-3 py-1.5 text-sm font-medium text-foreground transition-colors hover:bg-surface"
          >
            <PanelLeft size={16} aria-hidden />
            <span>Sessions</span>
          </button>
        </div>
        {sessionError && (
          <div className="px-4 pt-4">
            <InlineAlert>{sessionError}</InlineAlert>
          </div>
        )}
        {showModal && (
          <UploadModal
            sessionId={activeSessionId}
            onClose={() => {
              setShowModal(false);
              setReplaceDocumentIdFromList(null);
            }}
            returnFocusRef={uploadButtonRef}
            replaceDocumentId={resolvedReplaceDocumentId}
            onUploadAccepted={handleUploadAccepted}
            attachment={
              attachment
                ? {
                    documentId: attachment.documentId,
                    status: attachment.status,
                    stage: poll.stage,
                    chunks: poll.chunks,
                    processingTime: poll.processingTime,
                    errorMessage: poll.errorMessage,
                  }
                : null
            }
          />
        )}

        <div className="mx-auto flex min-h-0 w-full max-w-3xl flex-1 flex-col overflow-hidden">
          <MessageList
            messages={messages}
            inflight={inflight}
            streaming={streaming}
            historyLoading={historyLoading}
            sessionId={activeSessionId}
            bottomRef={bottomRef}
          />

          <SessionDocumentList
            sessionDocumentIds={sessionDocumentIds}
            documentSummaries={documentSummaries}
            retrievalState={retrievalState}
            attachment={attachment}
            onReplace={handleReplaceDocument}
            onDelete={(id) => void handleDeleteListedDocument(id)}
            actionsDisabled={inflight || streaming}
          />

          <div className="shrink-0 px-4 pb-2">
            <AdvancedRetrievalDrawer
              open={drawerOpen}
              onOpenChange={setDrawerOpen}
              state={retrievalState}
              onScopeChange={setScope}
              onMatchCountChange={setMatchCount}
              onHybridEnabledChange={setHybridEnabled}
              onRerankingEnabledChange={setRerankingEnabled}
              onRerankerProviderChange={setRerankerProvider}
              onQueryTransformationEnabledChange={setQueryTransformationEnabled}
              onQueryTransformationStrategyChange={setQueryTransformationStrategy}
              onHistoryAwareRetrievalChange={setHistoryAwareRetrieval}
              onRetrievalHistoryWindowChange={setRetrievalHistoryWindow}
              onGenerationHistoryWindowChange={setGenerationHistoryWindow}
              onMetadataFilterChange={setMetadataFilter}
              onPresetChange={setPreset}
              metadataCorpus={metadataCorpus}
              availablePresets={discovery.presets}
              availableRerankerProviders={discovery.reranker_providers}
              inspectMode={inspectMode}
              onInspectModeChange={setInspectMode}
            />
          </div>

          <ChatInput
            input={input}
            setInput={setInput}
            sendDisabled={sendDisabled}
            inflight={inflight}
            streaming={streaming}
            attachment={attachment}
            sessionNotice={sessionNotice}
            removeError={removeError}
            poll={poll}
            handleSend={handleSend}
            handleKeyDown={handleKeyDown}
            handleRemoveAttachment={handleRemoveAttachment}
            onUploadClick={() => setShowModal(true)}
            uploadButtonRef={uploadButtonRef}
            stopStreaming={stopStreaming}
            scopeIndicator={scopeIndicator}
            metadataFilterSummary={metadataFilterSummary}
          />
        </div>
      </div>
    </div>
  );
}
