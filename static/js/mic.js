/**
 * Voice input: Browser Web Speech by default, optional Groq Whisper recording.
 * Both engines write the same transcript and enter the existing parse flow.
 */
(function () {
  const micBtn = document.getElementById('mic-btn');
  const transcript = document.getElementById('transcript');
  const micState = document.getElementById('mic-state');
  const langSelect = document.getElementById('speech-lang');
  const engineSelect = document.getElementById('speech-engine');
  if (!micBtn || !transcript) return;

  const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
  const LANG_KEY = 'billing_speech_lang';
  const ENGINE_KEY = 'billing_stt_engine';
  const MAX_RECORDING_MS = 120000;
  let listening = false;
  let recognition = null;
  let suppressParseOnEnd = false;
  let recorder = null;
  let mediaStream = null;
  let audioChunks = [];
  let discardRecording = false;
  let recordingTimer = null;
  let uploadAbort = null;
  let micSession = 0;
  let requestingMic = false;

  function currentEngine() {
    return engineSelect ? engineSelect.value : 'browser';
  }

  function engineSupported() {
    if (currentEngine() === 'whisper') {
      return Boolean(navigator.mediaDevices && navigator.mediaDevices.getUserMedia && window.MediaRecorder);
    }
    return Boolean(SpeechRecognition);
  }

  function currentLang() {
    if (langSelect) return langSelect.value || 'en-PK';
    return localStorage.getItem(LANG_KEY) || 'en-PK';
  }

  function setButtonIdle() {
    micBtn.textContent = 'Start Listening';
    micBtn.classList.remove('ring-4', 'ring-red-300', 'bg-red-600');
    micBtn.classList.add('bg-accent');
    micBtn.disabled = !engineSupported();
    if (micState) {
      const lang = currentLang() === 'ur-PK' ? 'Urdu' : 'English';
      if (!engineSupported()) {
        micState.textContent = currentEngine() === 'whisper'
          ? 'Audio recording is not supported — use Browser voice or type'
          : 'Browser speech is not supported — try Groq Whisper or type';
      } else {
        const engine = currentEngine() === 'whisper' ? 'Whisper' : 'Browser';
        micState.textContent = 'Ready (' + lang + ', ' + engine + ') — stop mic to auto-match';
      }
    }
  }

  function setButtonListening() {
    micBtn.disabled = false;
    micBtn.textContent = 'Stop Listening';
    micBtn.classList.remove('bg-accent');
    micBtn.classList.add('ring-4', 'ring-red-300', 'bg-red-600');
    if (micState) {
      micState.textContent = currentEngine() === 'whisper'
        ? 'Recording… click again to stop and transcribe'
        : 'Listening… click again to stop';
    }
  }

  function maybeParseTranscript() {
    if (suppressParseOnEnd) {
      suppressParseOnEnd = false;
      return;
    }
    const text = transcript.value.trim();
    if (text && typeof window.parseOrder === 'function') {
      window.parseOrder(text);
    }
  }

  function createRecognition() {
    const rec = new SpeechRecognition();
    rec.lang = currentLang();
    rec.interimResults = true;
    rec.continuous = true;

    rec.onresult = (event) => {
      let text = '';
      for (let i = 0; i < event.results.length; i++) {
        text += event.results[i][0].transcript;
      }
      transcript.value = text;
    };

    rec.onerror = (event) => {
      listening = false;
      setButtonIdle();
      if (micState && event.error !== 'aborted') {
        micState.textContent = 'Mic error — type instead';
      }
    };

    rec.onend = () => {
      // If user still wants listening and browser stopped us, don't auto-restart
      // (continuous can end on silence). Treat as stopped.
      if (!listening) {
        setButtonIdle();
        maybeParseTranscript();
        return;
      }
      // Browser ended session while we thought we were listening — finalize
      listening = false;
      setButtonIdle();
      maybeParseTranscript();
    };

    return rec;
  }

  function startBrowser() {
    if (listening) return;
    try {
      recognition = createRecognition();
      recognition.start();
      listening = true;
      setButtonListening();
    } catch (_) {
      listening = false;
      setButtonIdle();
    }
  }

  function stopBrowser(opts) {
    const quiet = opts && opts.quiet;
    if (!listening && !recognition) return;
    if (quiet) suppressParseOnEnd = true;
    listening = false;
    try {
      if (recognition) recognition.stop();
    } catch (_) {}
    recognition = null;
    if (quiet) setButtonIdle();
  }

  function preferredMimeType() {
    const choices = ['audio/webm;codecs=opus', 'audio/webm', 'audio/mp4'];
    return choices.find((type) => MediaRecorder.isTypeSupported(type)) || '';
  }

  function releaseStream() {
    clearTimeout(recordingTimer);
    recordingTimer = null;
    if (mediaStream) mediaStream.getTracks().forEach((track) => track.stop());
    mediaStream = null;
  }

  async function uploadRecording(blob, extension) {
    if (!blob.size) {
      setButtonIdle();
      if (micState) micState.textContent = 'No audio was recorded — please retry';
      return;
    }
    micBtn.disabled = true;
    micBtn.textContent = 'Transcribing…';
    if (micState) micState.textContent = 'Uploading audio to Groq Whisper…';
    uploadAbort = new AbortController();
    const form = new FormData();
    form.append('audio', blob, 'order.' + extension);
    form.append('language', currentLang() === 'ur-PK' ? 'ur' : 'en');
    try {
      const response = await fetch('/api/transcribe', {
        method: 'POST',
        body: form,
        signal: uploadAbort.signal,
      });
      let data = {};
      try {
        data = await response.json();
      } catch (_) {}
      if (!response.ok) {
        throw new Error(data.detail || 'Whisper transcription failed');
      }
      transcript.value = (data.text || '').trim();
      setButtonIdle();
      if (micState) micState.textContent = 'Transcript ready — matching order…';
      maybeParseTranscript();
    } catch (err) {
      setButtonIdle();
      if (err && err.name === 'AbortError') return;
      if (micState) {
        micState.textContent = (err && err.message)
          ? err.message
          : 'Whisper failed — retry, use Browser voice, or type the order';
      }
    } finally {
      uploadAbort = null;
    }
  }

  async function startWhisper() {
    if (listening || requestingMic || !engineSupported()) return;
    const session = ++micSession;
    requestingMic = true;
    micBtn.disabled = true;
    if (micState) micState.textContent = 'Requesting microphone permission…';
    try {
      mediaStream = await navigator.mediaDevices.getUserMedia({ audio: true });
      requestingMic = false;
      // The user may switch engines while the permission prompt is open.
      if (session !== micSession || currentEngine() !== 'whisper') {
        releaseStream();
        setButtonIdle();
        return;
      }
      const mimeType = preferredMimeType();
      recorder = mimeType
        ? new MediaRecorder(mediaStream, { mimeType })
        : new MediaRecorder(mediaStream);
      audioChunks = [];
      discardRecording = false;
      recorder.ondataavailable = (event) => {
        if (event.data && event.data.size) audioChunks.push(event.data);
      };
      recorder.onerror = () => {
        listening = false;
        releaseStream();
        setButtonIdle();
        if (micState) micState.textContent = 'Recording failed — retry or use Browser voice';
      };
      recorder.onstop = () => {
        const type = recorder && recorder.mimeType ? recorder.mimeType : 'audio/webm';
        const extension = type.includes('mp4') ? 'mp4' : type.includes('ogg') ? 'ogg' : 'webm';
        const blob = new Blob(audioChunks, { type });
        const shouldDiscard = discardRecording;
        recorder = null;
        audioChunks = [];
        releaseStream();
        if (shouldDiscard) {
          setButtonIdle();
          return;
        }
        uploadRecording(blob, extension);
      };
      recorder.start(250);
      listening = true;
      setButtonListening();
      recordingTimer = setTimeout(() => stopWhisper(), MAX_RECORDING_MS);
    } catch (err) {
      requestingMic = false;
      listening = false;
      releaseStream();
      setButtonIdle();
      if (micState) {
        micState.textContent = err && err.name === 'NotAllowedError'
          ? 'Microphone permission denied'
          : 'Could not start recording — retry or use Browser voice';
      }
    }
  }

  function stopWhisper(opts) {
    const quiet = opts && opts.quiet;
    if (quiet) discardRecording = true;
    listening = false;
    clearTimeout(recordingTimer);
    recordingTimer = null;
    if (recorder && recorder.state !== 'inactive') {
      recorder.stop();
    } else {
      releaseStream();
      if (quiet) setButtonIdle();
    }
  }

  function stop(opts) {
    micSession++;
    if (recorder || mediaStream) stopWhisper(opts);
    else if (recognition) stopBrowser(opts);
    else if (currentEngine() === 'whisper') stopWhisper(opts);
    else stopBrowser(opts);
  }

  function toggle() {
    if (listening) {
      stop();
    } else if (currentEngine() === 'whisper') {
      startWhisper();
    } else {
      startBrowser();
    }
  }

  /** Stop mic without triggering parse (used by New bill). */
  window.stopMicListening = function stopMicListening() {
    if (uploadAbort) uploadAbort.abort();
    stop({ quiet: true });
  };

  micBtn.addEventListener('click', (e) => {
    e.preventDefault();
    toggle();
  });

  if (langSelect) {
    const saved = localStorage.getItem(LANG_KEY);
    if (saved) langSelect.value = saved;
    langSelect.addEventListener('change', () => {
      localStorage.setItem(LANG_KEY, langSelect.value);
      if (listening) {
        stop({ quiet: true });
        // brief delay then restart in new language if they were mid-order
      }
      setButtonIdle();
    });
  }

  if (engineSelect) {
    const savedEngine = localStorage.getItem(ENGINE_KEY);
    if (savedEngine === 'whisper' || savedEngine === 'browser') {
      engineSelect.value = savedEngine;
    }
    engineSelect.addEventListener('change', () => {
      if (uploadAbort) uploadAbort.abort();
      if (listening || recognition || recorder || mediaStream) stop({ quiet: true });
      localStorage.setItem(ENGINE_KEY, engineSelect.value);
      setButtonIdle();
    });
  }

  setButtonIdle();
})();
