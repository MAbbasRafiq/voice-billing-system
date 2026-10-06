/**
 * Voice input: Local Parakeet (default) or browser Web Speech.
 * Parakeet mode auto-stops after silence (VAD). Status line stays quiet when idle.
 */
(function () {
  const micBtn = document.getElementById('mic-btn');
  const transcript = document.getElementById('transcript');
  const micState = document.getElementById('mic-state');
  const engineSelect = document.getElementById('speech-engine');
  if (!micBtn || !transcript) return;

  const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
  const ENGINE_KEY = 'billing_stt_engine';
  const SPEECH_LANG = 'en-PK';

  // One short item utterance; hard cap as safety net.
  const MAX_RECORDING_MS = 15000;
  const VAD_SPEECH_LEVEL = 0.02;
  const VAD_SILENCE_MS = 900;
  const VAD_MIN_SPEECH_MS = 250;
  const VAD_NO_SPEECH_MS = 5000;
  const VAD_POLL_MS = 50;

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

  let audioContext = null;
  let analyser = null;
  let vadSource = null;
  let vadTimer = null;
  let vadSpeechStarted = false;
  let vadSpeechStartedAt = 0;
  let vadLastLoudAt = 0;
  let vadRecordingStartedAt = 0;

  function currentEngine() {
    return engineSelect ? engineSelect.value : 'browser';
  }

  function engineSupported() {
    if (currentEngine() === 'whisper') {
      return Boolean(navigator.mediaDevices && navigator.mediaDevices.getUserMedia && window.MediaRecorder);
    }
    return Boolean(SpeechRecognition);
  }

  function setMicState(text) {
    if (micState) micState.textContent = text || '';
  }

  function setButtonIdle() {
    micBtn.textContent = 'Start Listening';
    micBtn.classList.remove('ring-4', 'ring-red-300', 'bg-red-600');
    micBtn.classList.add('bg-accent');
    micBtn.disabled = !engineSupported();
    if (!engineSupported()) {
      setMicState(
        currentEngine() === 'whisper'
          ? 'Audio recording is not supported — use Browser voice or type'
          : 'Browser speech is not supported — try Local Parakeet or type'
      );
    } else {
      setMicState('');
    }
  }

  function setButtonListening() {
    micBtn.disabled = false;
    micBtn.textContent = 'Stop Listening';
    micBtn.classList.remove('bg-accent');
    micBtn.classList.add('ring-4', 'ring-red-300', 'bg-red-600');
    setMicState('');
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
    rec.lang = SPEECH_LANG;
    rec.interimResults = true;
    // One utterance then auto-end (browser silence / end-of-speech).
    rec.continuous = false;

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
      if (event.error !== 'aborted') {
        setMicState('Mic error — type instead');
      }
    };

    rec.onend = () => {
      if (!listening) {
        setButtonIdle();
        maybeParseTranscript();
        return;
      }
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

  function stopVadMonitor() {
    if (vadTimer) {
      clearInterval(vadTimer);
      vadTimer = null;
    }
    try {
      if (vadSource) vadSource.disconnect();
    } catch (_) {}
    vadSource = null;
    analyser = null;
    if (audioContext) {
      try {
        audioContext.close();
      } catch (_) {}
      audioContext = null;
    }
    vadSpeechStarted = false;
    vadSpeechStartedAt = 0;
    vadLastLoudAt = 0;
    vadRecordingStartedAt = 0;
  }

  function rmsLevel(analyserNode) {
    const buf = new Float32Array(analyserNode.fftSize);
    analyserNode.getFloatTimeDomainData(buf);
    let sum = 0;
    for (let i = 0; i < buf.length; i++) {
      const v = buf[i];
      sum += v * v;
    }
    return Math.sqrt(sum / buf.length);
  }

  function startVadMonitor(stream) {
    stopVadMonitor();
    try {
      const Ctx = window.AudioContext || window.webkitAudioContext;
      if (!Ctx) return;
      audioContext = new Ctx();
      if (audioContext.state === 'suspended') {
        audioContext.resume().catch(() => {});
      }
      analyser = audioContext.createAnalyser();
      analyser.fftSize = 2048;
      vadSource = audioContext.createMediaStreamSource(stream);
      vadSource.connect(analyser);
      vadRecordingStartedAt = Date.now();
      vadSpeechStarted = false;
      vadLastLoudAt = Date.now();

      vadTimer = setInterval(() => {
        if (!listening || !analyser || !recorder || recorder.state !== 'recording') return;
        const level = rmsLevel(analyser);
        const now = Date.now();
        if (level >= VAD_SPEECH_LEVEL) {
          if (!vadSpeechStarted) {
            vadSpeechStarted = true;
            vadSpeechStartedAt = now;
          }
          vadLastLoudAt = now;
        }
        if (
          vadSpeechStarted &&
          now - vadSpeechStartedAt >= VAD_MIN_SPEECH_MS &&
          now - vadLastLoudAt >= VAD_SILENCE_MS
        ) {
          stopWhisper();
          return;
        }
        if (!vadSpeechStarted && now - vadRecordingStartedAt >= VAD_NO_SPEECH_MS) {
          stopWhisper({ quiet: true });
          setMicState('No speech detected — try again');
        }
      }, VAD_POLL_MS);
    } catch (_) {
      stopVadMonitor();
    }
  }

  function releaseStream() {
    clearTimeout(recordingTimer);
    recordingTimer = null;
    stopVadMonitor();
    if (mediaStream) mediaStream.getTracks().forEach((track) => track.stop());
    mediaStream = null;
  }

  async function uploadRecording(blob, extension) {
    if (!blob.size) {
      setButtonIdle();
      setMicState('No audio was recorded — please retry');
      return;
    }
    micBtn.disabled = true;
    micBtn.textContent = 'Transcribing…';
    setMicState('');
    uploadAbort = new AbortController();
    const form = new FormData();
    form.append('audio', blob, 'order.' + extension);
    form.append('language', 'en');
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
        throw new Error(data.detail || 'Transcription failed');
      }
      transcript.value = (data.text || '').trim();
      setButtonIdle();
      maybeParseTranscript();
    } catch (err) {
      setButtonIdle();
      if (err && err.name === 'AbortError') return;
      setMicState(
        (err && err.message)
          ? err.message
          : 'Transcription failed — retry, use Browser voice, or type'
      );
    } finally {
      uploadAbort = null;
    }
  }

  async function startWhisper() {
    if (listening || requestingMic || !engineSupported()) return;
    const session = ++micSession;
    requestingMic = true;
    micBtn.disabled = true;
    setMicState('');
    try {
      mediaStream = await navigator.mediaDevices.getUserMedia({ audio: true });
      requestingMic = false;
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
        setMicState('Recording failed — retry or use Browser voice');
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
      startVadMonitor(mediaStream);
      recordingTimer = setTimeout(() => stopWhisper(), MAX_RECORDING_MS);
    } catch (err) {
      requestingMic = false;
      listening = false;
      releaseStream();
      setButtonIdle();
      setMicState(
        err && err.name === 'NotAllowedError'
          ? 'Microphone permission denied'
          : 'Could not start recording — retry or use Browser voice'
      );
    }
  }

  function stopWhisper(opts) {
    const quiet = opts && opts.quiet;
    if (quiet) discardRecording = true;
    listening = false;
    clearTimeout(recordingTimer);
    recordingTimer = null;
    stopVadMonitor();
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

  window.stopMicListening = function stopMicListening() {
    if (uploadAbort) uploadAbort.abort();
    stop({ quiet: true });
  };

  micBtn.addEventListener('click', (e) => {
    e.preventDefault();
    toggle();
  });

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
