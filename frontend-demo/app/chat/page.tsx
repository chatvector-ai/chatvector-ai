"use client";

import { useState } from "react";
import { Loader2 } from "lucide-react";
import UploadModal from "../components/UploadModal";
import MessageList from "../components/chat/MessageList";
import ChatInput from "../components/chat/ChatInput";
import SessionSidebar from "../components/chat/SessionSidebar";
import RetrievalSettingsPanel from "../components/RetrievalSettingsPanel";
import { useChat } from "../lib/hooks/useChat";
import { useRetrievalSettings } from "../lib/hooks/useRetrievalSettings";
import { useSessionManager } from "../lib/hooks/useSessionManager";

export default function ChatPage() {
  const [showModal, setShowModal] = useState(false);
  const { sessions, activeSessionId, createNewSession, switchSession, isLoaded } = useSessionManager();
  const { settings, setScope, setMatchCount, loaded: retrievalLoaded } = useRetrievalSettings();

  const {
    messages,
    input,
    setInput,
    inflight,
    streaming,
    attachment,
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
        className="flex h-full w-full flex-col items-center justify-center gap-3 bg-background text-muted"
        style={{ height: "calc(100dvh - 60px)" }}
      >
        <Loader2 className="h-6 w-6 animate-spin opacity-50" />
        <span className="text-sm">Loading sessions...</span>
      </div>
    );
  }

  return (
    <div
      className="flex min-h-0 w-full flex-1 overflow-hidden bg-background text-foreground"
      style={{
        height: "calc(100dvh - 60px)",
        maxHeight: "calc(100dvh - 60px)",
      }}
    >
      <SessionSidebar
        sessions={sessions}
        activeSessionId={activeSessionId}
        onCreateSession={createNewSession}
        onSwitchSession={switchSession}
      />

      <div className="flex-1 flex flex-col overflow-hidden min-h-0">
        <h1 className="sr-only">Chat with your documents</h1>
        {showModal && (
          <UploadModal
            onClose={() => setShowModal(false)}
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
          <MessageList messages={messages} inflight={inflight} streaming={streaming} bottomRef={bottomRef} />

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
            removeError={removeError}
            poll={poll}
            handleSend={handleSend}
            handleKeyDown={handleKeyDown}
            handleRemoveAttachment={handleRemoveAttachment}
            onUploadClick={() => setShowModal(true)}
            stopStreaming={stopStreaming}
          />
        </div>
      </div>
    </div>
  );
}
