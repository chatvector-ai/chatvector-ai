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
    <div className="flex flex-col h-screen bg-gray-950 text-white">
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
  );
}
