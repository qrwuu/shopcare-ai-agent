import { Suspense } from "react";
import ChatInterface from "@/components/ChatInterface";

export default function ChatPage() {
  return (
    <Suspense fallback={null}>
      <ChatInterface />
    </Suspense>
  );
}
