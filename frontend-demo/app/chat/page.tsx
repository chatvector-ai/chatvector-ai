"use client";

import { useState, useRef } from "react";
import { PanelLeft } from "lucide-react";
import UploadModal from "../components/UploadModal";
import MessageList from "../components/chat/MessageList";
import ChatInput from "../components/chat/ChatInput";
import SessionSidebar from "../components/chat/SessionSidebar";
import RetrievalSettingsPanel from "../components/RetrievalSettingsPanel";
import { InlineAlert } from "../components/ui/InlineAlert";
import { useChat } from "../lib/hooks/useChat";
import { useRetrievalSettings } from "../lib/hooks/useRetrievalSettings";
import { useSessionManager } from "../lib/hooks/useSessionManager";

export default function ChatPage() {
  const [showModal, setShowModal] = useState(false);
  const [mobileSessionsOpen, setMobileSessionsOpen] = useState(false);
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
  } = useSessionManager();
  const { settings, setScope, setMatchCount, loaded: retrievalLoaded } = useRetrievalSettings();

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
    handleBeforeUpload,
    handleUploadAccepted,
    handleRemoveAttachment,
    stopStreaming,
  } = useChat(activeSessionId, settings);

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
        {/* Sidebar skeleton */}
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

        {/* Main area skeleton */}
        <div className="flex-1 flex flex-col overflow-hidden min-h-0 animate-pulse">
          <div className="mx-auto flex min-h-0 w-full max-w-3xl flex-1 flex-col overflow-hidden p-4">
            {/* Message bubbles */}
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

            {/* Input bar skeleton */}
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
            onClose={() => setShowModal(false)}
            returnFocusRef={uploadButtonRef}
            onBeforeUpload={handleBeforeUpload}
            onUploadAccepted={handleUploadAccepted}
            attachment={
              attachment
                ? {
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
            bottomRef={bottomRef}
          />

          <div className="shrink-0 px-4 pb-2">
            <RetrievalSettingsPanel
              settings={settings}
              onScopeChange={setScope}
              onMatchCountChange={setMatchCount}
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
            scope={settings.scope}
          />
        </div>
      </div>
    </div>
  );
}
