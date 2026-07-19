"use client";

import { useEffect, useState, useRef } from "react";

interface Props {
  onTranscript: (text: string) => void;
  disabled?: boolean;
  elevenLabsKey?: string | null;
}

declare global {
  interface SpeechRecognitionEvent extends Event {
    readonly results: SpeechRecognitionResultList;
  }
  interface SpeechRecognition extends EventTarget {
    lang: string;
    interimResults: boolean;
    maxAlternatives: number;
    start(): void;
    stop(): void;
    onresult: ((event: SpeechRecognitionEvent) => void) | null;
    onend: (() => void) | null;
    onerror: ((event: Event) => void) | null;
  }
  interface Window {
    SpeechRecognition: new () => SpeechRecognition;
    webkitSpeechRecognition: new () => SpeechRecognition;
  }
}

type Mode = "native" | "elevenlabs" | "unsupported";

function detectMode(elevenLabsKey?: string | null): Mode {
  if (typeof window === "undefined") return "unsupported";
  if ("SpeechRecognition" in window || "webkitSpeechRecognition" in window) return "native";
  if (elevenLabsKey && typeof MediaRecorder !== "undefined") return "elevenlabs";
  return "unsupported";
}

export default function VoiceInput({ onTranscript, disabled, elevenLabsKey }: Props) {
  const [mounted, setMounted] = useState(false);
  const [listening, setListening] = useState(false);
  const [transcribing, setTranscribing] = useState(false);
  const recognitionRef = useRef<SpeechRecognition | null>(null);
  const mediaRecorderRef = useRef<MediaRecorder | null>(null);
  const chunksRef = useRef<Blob[]>([]);


  useEffect(() => {
    setMounted(true);
  }, []);

  const mode = mounted ? detectMode(elevenLabsKey) : "unsupported";

  // ── Native SpeechRecognition ─────────────────────────────────────────────
  const toggleNative = () => {
    if (listening) {
      recognitionRef.current?.stop();
      setListening(false);
      return;
    }
    const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
    const r = new SR();
    r.lang = "en-US";
    r.interimResults = false;
    r.maxAlternatives = 1;
    r.onresult = (e) => onTranscript(e.results[0][0].transcript);
    r.onend = () => setListening(false);
    r.onerror = () => setListening(false);
    r.start();
    recognitionRef.current = r;
    setListening(true);
  };

  // ── ElevenLabs STT via MediaRecorder ────────────────────────────────────
  const toggleElevenLabs = async () => {
    if (listening) {
      mediaRecorderRef.current?.stop();
      setListening(false);
      return;
    }

    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      chunksRef.current = [];
      const mr = new MediaRecorder(stream);
      mediaRecorderRef.current = mr;

      mr.ondataavailable = (e) => { if (e.data.size > 0) chunksRef.current.push(e.data); };

      mr.onstop = async () => {
        stream.getTracks().forEach((t) => t.stop());
        setTranscribing(true);
        try {
          const blob = new Blob(chunksRef.current, { type: "audio/webm" });
          const form = new FormData();
          form.append("file", blob, "recording.webm");
          form.append("model_id", "scribe_v1");

          const res = await fetch("https://api.elevenlabs.io/v1/speech-to-text", {
            method: "POST",
            headers: { "xi-api-key": elevenLabsKey! },
            body: form,
          });
          const data = await res.json();
          const text = data.text?.trim();
          if (text) onTranscript(text);
        } catch { /* silently skip */ } finally {
          setTranscribing(false);
        }
      };

      mr.start();
      setListening(true);
    } catch { /* mic permission denied */ }
  };

  const toggle = () => {
    if (disabled || transcribing) return;
    if (mode === "native") toggleNative();
    else if (mode === "elevenlabs") toggleElevenLabs();
  };

  const isUnsupported = mode === "unsupported";
  const title = isUnsupported
    ? "Voice input unavailable — browser lacks SpeechRecognition and no ElevenLabs key configured"
    : transcribing
    ? "Transcribing…"
    : listening
    ? "Stop recording"
    : mode === "elevenlabs"
    ? "Record voice (ElevenLabs STT)"
    : "Speak your message";

  return (
    <button
      type="button"
      onClick={toggle}
      disabled={disabled || isUnsupported || transcribing}
      title={title}
      className={`p-2.5 rounded border transition-all duration-150 shrink-0 relative ${
        transcribing
          ? "bg-accent/10 border-accent/30 text-accent cursor-wait"
          : listening
          ? "bg-danger/10 border-danger/40 text-danger animate-pulse"
          : isUnsupported
          ? "bg-background-raised border-border-col text-text-col-tertiary opacity-30 cursor-not-allowed"
          : "bg-background-raised border-border-col text-text-col-tertiary hover:border-accent hover:text-accent"
      } disabled:cursor-not-allowed`}
    >
      {transcribing ? (
        // Spinner
        <svg className="w-4 h-4 animate-spin" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24">
          <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
          <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v8H4z" />
        </svg>
      ) : listening ? (
        // Stop icon
        <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="currentColor" className="w-4 h-4">
          <path fillRule="evenodd" d="M4.5 7.5a3 3 0 0 1 3-3h9a3 3 0 0 1 3 3v9a3 3 0 0 1-3 3h-9a3 3 0 0 1-3-3v-9Z" clipRule="evenodd" />
        </svg>
      ) : (
        // Mic icon
        <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="currentColor" className="w-4 h-4">
          <path d="M8.25 4.5a3.75 3.75 0 1 1 7.5 0v8.25a3.75 3.75 0 1 1-7.5 0V4.5Z" />
          <path d="M6 10.5a.75.75 0 0 1 .75.75v1.5a5.25 5.25 0 1 0 10.5 0v-1.5a.75.75 0 0 1 1.5 0v1.5a6.751 6.751 0 0 1-6 6.709v2.291h3a.75.75 0 0 1 0 1.5h-7.5a.75.75 0 0 1 0-1.5h3v-2.291A6.751 6.751 0 0 1 5.25 12.75v-1.5A.75.75 0 0 1 6 10.5Z" />
        </svg>
      )}
      {/* ElevenLabs badge */}
      {mode === "elevenlabs" && !listening && !transcribing && (
        <span className="absolute -top-1 -right-1 w-2 h-2 rounded-full bg-accent border border-background-base" title="Powered by ElevenLabs" />
      )}
    </button>
  );
}
