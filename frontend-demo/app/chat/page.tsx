"use client";

import { useState } from "react";
import UploadModal from "../components/UploadModal";
import MessageList from "../components/chat/MessageList";
import ChatInput from "../components/chat/ChatInput";
import { useChat } from "../lib/hooks/useChat";

export default function ChatPage() {
  const [showModal, setShowModal] = useState(false);
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
  } = useChat();

  return (
    <div
      className="flex min-h-0 w-full flex-1 flex-col overflow-hidden bg-background text-foreground"
      style={{
        height: "calc(100dvh - 60px)",
        maxHeight: "calc(100dvh - 60px)",
      }}
    >
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
  );
}
