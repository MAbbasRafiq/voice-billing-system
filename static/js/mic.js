/**
 * Web Speech API voice input for billing.
 */
(function () {
  const micBtn = document.getElementById('mic-btn');
  const transcript = document.getElementById('transcript');
  const micState = document.getElementById('mic-state');
  if (!micBtn || !transcript) return;

  const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
  if (!SpeechRecognition) {
    micBtn.disabled = true;
    micBtn.textContent = 'Speech not supported';
    if (micState) micState.textContent = 'Use Chrome/Edge or type the order';
    return;
  }

  const recognition = new SpeechRecognition();
  recognition.lang = 'en-PK';
  recognition.interimResults = true;
  recognition.continuous = false;

  let listening = false;

  function start() {
    if (listening) return;
    try {
      recognition.start();
      listening = true;
      micBtn.classList.add('ring-4', 'ring-red-300');
      if (micState) micState.textContent = 'Listening…';
    } catch (_) {}
  }

  function stop() {
    try {
      recognition.stop();
    } catch (_) {}
  }

  micBtn.addEventListener('mousedown', (e) => { e.preventDefault(); start(); });
  micBtn.addEventListener('mouseup', stop);
  micBtn.addEventListener('mouseleave', () => { if (listening) stop(); });
  micBtn.addEventListener('touchstart', (e) => { e.preventDefault(); start(); }, { passive: false });
  micBtn.addEventListener('touchend', (e) => { e.preventDefault(); stop(); });

  recognition.onresult = (event) => {
    const text = Array.from(event.results)
      .map((r) => r[0].transcript)
      .join('');
    transcript.value = text;
  };

  recognition.onerror = () => {
    listening = false;
    micBtn.classList.remove('ring-4', 'ring-red-300');
    if (micState) micState.textContent = 'Mic error — type instead';
  };

  recognition.onend = () => {
    listening = false;
    micBtn.classList.remove('ring-4', 'ring-red-300');
    if (micState) micState.textContent = 'Ready';
    const text = transcript.value.trim();
    if (text && typeof window.parseOrder === 'function') {
      window.parseOrder(text);
    }
  };
})();
