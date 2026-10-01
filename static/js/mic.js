/**
 * Web Speech API — click to toggle mic + English/Urdu language.
 */
(function () {
  const micBtn = document.getElementById('mic-btn');
  const transcript = document.getElementById('transcript');
  const micState = document.getElementById('mic-state');
  const langSelect = document.getElementById('speech-lang');
  if (!micBtn || !transcript) return;

  const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
  if (!SpeechRecognition) {
    micBtn.disabled = true;
    micBtn.textContent = 'Speech not supported';
    if (micState) micState.textContent = 'Use Chrome/Edge or type the order';
    return;
  }

  const LANG_KEY = 'billing_speech_lang';
  let listening = false;
  let recognition = null;
  let suppressParseOnEnd = false;

  function currentLang() {
    if (langSelect) return langSelect.value || 'en-PK';
    return localStorage.getItem(LANG_KEY) || 'en-PK';
  }

  function setButtonIdle() {
    micBtn.textContent = 'Start Listening';
    micBtn.classList.remove('ring-4', 'ring-red-300', 'bg-red-600');
    micBtn.classList.add('bg-accent');
    if (micState) {
      const lang = currentLang() === 'ur-PK' ? 'Urdu' : 'English';
      micState.textContent = 'Ready (' + lang + ') — click mic to speak';
    }
  }

  function setButtonListening() {
    micBtn.textContent = 'Stop Listening';
    micBtn.classList.remove('bg-accent');
    micBtn.classList.add('ring-4', 'ring-red-300', 'bg-red-600');
    if (micState) micState.textContent = 'Listening… click again to stop';
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

  function start() {
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

  function stop(opts) {
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

  function toggle() {
    if (listening) stop();
    else start();
  }

  /** Stop mic without triggering parse (used by New bill). */
  window.stopMicListening = function stopMicListening() {
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

  setButtonIdle();
})();
