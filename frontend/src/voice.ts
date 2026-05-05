/**
 * Voice input (Web Speech API) and audio output (AudioContext) for LIS.
 */

// ---------------------------------------------------------------------------
// Speech Recognition
// ---------------------------------------------------------------------------

export interface VoiceInput {
  start(): void;
  stop(): void;
  pause(): void;
  resume(): void;
}

// eslint-disable-next-line @typescript-eslint/no-explicit-any
declare const webkitSpeechRecognition: any;

export function createVoiceInput(
  onTranscript: (text: string) => void,
  onError: (msg: string) => void,
  onInterruption?: () => void
): VoiceInput {
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const SR = (window as any).SpeechRecognition || (typeof webkitSpeechRecognition !== "undefined" ? webkitSpeechRecognition : null);
  if (!SR) {
    onError("Speech recognition not supported in this browser");
    return { start() {}, stop() {}, pause() {}, resume() {} };
  }

  const recognition = new SR();
  recognition.continuous = true;
  recognition.interimResults = true;
  recognition.lang = "en-US"; // Reverted to en-US for maximum Edge compatibility

  let shouldListen = false;
  let paused = false;
  let isListening = false;

  recognition.onstart = () => {
    isListening = true;
  };

  recognition.onresult = (event: any) => {
    let hasSpeech = false;
    for (let i = event.resultIndex; i < event.results.length; i++) {
      const transcript = event.results[i][0].transcript;
      if (transcript.trim().length > 0) hasSpeech = true;
      
      if (event.results[i].isFinal) {
        console.log("[mic] FINAL:", transcript);
        const text = transcript.trim();
        if (text) onTranscript(text);
      } else {
        console.log("[mic] interim:", transcript);
      }
    }
    
    if (hasSpeech && onInterruption) {
      onInterruption();
    }
  };

  recognition.onend = () => {
    isListening = false;
    if (shouldListen && !paused) {
      setTimeout(() => {
        try {
          recognition.start();
        } catch {
          // Already started
        }
      }, 50);
    }
  };

  // Bulletproof fallback watchdog: aggressively restarts mic if it randomly dies (e.g. network timeout)
  setInterval(() => {
    if (shouldListen && !paused && !isListening) {
      try {
        recognition.start();
      } catch {}
    }
  }, 1000);

  recognition.onerror = (event: any) => {
    if (event.error === "not-allowed") {
      onError("Microphone access denied. Please allow microphone access.");
      shouldListen = false;
    } else if (event.error === "no-speech") {
      // Normal, just restart
    } else if (event.error === "aborted") {
      // Expected during pause
    } else {
      console.warn("[voice] recognition error:", event.error);
    }
  };

  return {
    start() {
      shouldListen = true;
      paused = false;
      try {
        recognition.start();
      } catch {
        // Already started
      }
    },
    stop() {
      shouldListen = false;
      paused = false;
      recognition.stop();
    },
    pause() {
      paused = true;
      recognition.stop();
    },
    resume() {
      paused = false;
      if (shouldListen) {
        try {
          recognition.start();
        } catch {
          // Already started
        }
      }
    },
  };
}

// ---------------------------------------------------------------------------
// Audio Player (Clean Sequential Engine)
// ---------------------------------------------------------------------------

export interface AudioPlayer {
  enqueue(base64: string): Promise<void>;
  stop(): void;
  getAnalyser(): AnalyserNode;
  onFinished(cb: () => void): void;
}

export function createAudioPlayer(): AudioPlayer {
  const audioCtx = new (window.AudioContext || (window as any).webkitAudioContext)();
  const analyser = audioCtx.createAnalyser();
  analyser.fftSize = 256;
  analyser.smoothingTimeConstant = 0.8;
  analyser.connect(audioCtx.destination);

  const queue: AudioBuffer[] = [];
  let isPlaying = false;
  let currentSource: AudioBufferSourceNode | null = null;
  let finishedCallback: (() => void) | null = null;

  function playNext() {
    if (queue.length === 0) {
      isPlaying = false;
      currentSource = null;
      finishedCallback?.();
      return;
    }

    isPlaying = true;
    const buffer = queue.shift()!;
    const source = audioCtx.createBufferSource();
    const gain = audioCtx.createGain();

    source.buffer = buffer;

    // Gentle fade-in to avoid click at start (20ms)
    gain.gain.setValueAtTime(0, audioCtx.currentTime);
    gain.gain.linearRampToValueAtTime(1, audioCtx.currentTime + 0.02);

    source.connect(gain);
    gain.connect(analyser);

    source.start(0);
    currentSource = source;

    // When this buffer finishes, play the next one
    source.onended = () => {
      playNext();
    };
  }

  return {
    async enqueue(base64: string) {
      if (audioCtx.state === "suspended") {
        await audioCtx.resume();
      }

      try {
        const binary = atob(base64);
        const bytes = new Uint8Array(binary.length);
        for (let i = 0; i < binary.length; i++) {
          bytes[i] = binary.charCodeAt(i);
        }
        
        const audioBuffer = await audioCtx.decodeAudioData(bytes.buffer.slice(0));
        queue.push(audioBuffer);
        
        // Start playback if not already playing
        if (!isPlaying) {
          playNext();
        }
      } catch (err) {
        console.error("[audio] decode error:", err);
      }
    },

    stop() {
      queue.length = 0;
      if (currentSource) {
        try { currentSource.stop(); } catch {}
        currentSource = null;
      }
      isPlaying = false;
    },

    getAnalyser() {
      return analyser;
    },

    onFinished(cb: () => void) {
      finishedCallback = cb;
    },
  };
}
