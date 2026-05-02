"use client";

import { useState } from "react";
import UploadModal from "../components/UploadModal";
import MessageList from "../components/chat/MessageList";
import ChatInput from "../components/chat/ChatInput";
import { useChat } from "../lib/hooks/useChat";
import { useSessionManager } from "../lib/hooks/useSessionManager";

export default function ChatPage() {
  const [showModal, setShowModal] = useState(false);
  const { sessions, activeSessionId, createNewSession, switchSession, isLoaded } = useSessionManager();

  const {
    messages,
    input,
    setInput,
    inflight,
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
  } = useChat(activeSessionId);

  if (!isLoaded) {
    return (
      <div 
        className="flex h-full w-full items-center justify-center bg-background text-muted"
        style={{ height: "calc(100dvh - 60px)" }}
      >
        Loading sessions...
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
      <div className="w-64 border-r border-border bg-surface flex-col hidden md:flex">
        <div className="p-4 border-b border-border">
          <button
            onClick={createNewSession}
            className="w-full flex items-center justify-center gap-2 rounded-lg bg-primary px-4 py-2 font-medium text-primary-foreground hover:bg-primary/90 transition-colors"
          >
            <span className="text-lg leading-none">+</span>
            <span>New Session</span>
          </button>
        </div>
        <div className="flex-1 overflow-y-auto p-2 space-y-1">
          {sessions.map((session) => (
            <button
              key={session.id}
              onClick={() => switchSession(session.id)}
              className={`w-full text-left px-3 py-2 rounded-md text-sm transition-colors truncate ${
                session.id === activeSessionId
                  ? "bg-accent/10 text-accent font-medium"
                  : "text-muted hover:bg-surface hover:text-foreground"
              }`}
            >
              Session {session.id.substring(0, 8)}
            </button>
          ))}
        </div>
      </div>

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
                  }
                : null
            }
          />
        )}

        <div className="mx-auto flex min-h-0 w-full max-w-3xl flex-1 flex-col overflow-hidden">
          <MessageList messages={messages} inflight={inflight} bottomRef={bottomRef} />

          <ChatInput
            input={input}
            setInput={setInput}
            sendDisabled={sendDisabled}
            inflight={inflight}
            attachment={attachment}
            removeError={removeError}
            poll={poll}
            handleSend={handleSend}
            handleKeyDown={handleKeyDown}
            handleRemoveAttachment={handleRemoveAttachment}
            onUploadClick={() => setShowModal(true)}
          />
        </div>
      </div>
    </div>
  );
}
