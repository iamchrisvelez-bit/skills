"""Voice: talking to Brainiac and hearing him answer.

The main voice interface is the command console. It uses the browser's
speech recognition for input and speech synthesis for output, so there is
nothing to install. This module holds the shared rules for turning a written
answer into something worth hearing, plus an optional terminal voice loop:

    pip install SpeechRecognition pyttsx3 pyaudio
    python -m brainiac voice

If those packages are missing, the loop says what to install and exits.
"""

from __future__ import annotations

import re

# Brainiac's speaking voice: measured and a little low. The console applies the same values.
VOICE = {"rate": 0.98, "pitch": 0.82, "max_sentences": 4}


def speakable(text: str, max_sentences: int = VOICE["max_sentences"]) -> str:
    """Turn a written answer into speech: drop code and markup, keep it short."""
    t = re.sub(r"```.*?```", " (code is on screen) ", text, flags=re.S)
    t = re.sub(r"`([^`]*)`", r"\1", t)
    t = re.sub(r"!\[[^\]]*\]\([^)]*\)", "", t)
    t = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", t)
    t = re.sub(r"^\s{0,3}(#{1,6}|[-*+]|\d+\.)\s+", "", t, flags=re.M)
    t = re.sub(r"[*_~|>#]", "", t)
    t = re.sub(r"https?://\S+", "the link on screen", t)
    t = re.sub(r"\s+", " ", t).strip()
    sentences = re.split(r"(?<=[.!?])\s+", t)
    if len(sentences) > max_sentences:
        t = " ".join(sentences[:max_sentences]) + " The rest is on screen."
    return t


def main(brainiac, session: str = "voice") -> int:  # pragma: no cover - needs a microphone
    try:
        import pyttsx3
        import speech_recognition as sr
    except ImportError:
        print("Terminal voice needs: pip install SpeechRecognition pyttsx3 pyaudio\n"
              "Or use voice in the console: python -m brainiac console")
        return 2
    engine = pyttsx3.init()
    engine.setProperty("rate", int(engine.getProperty("rate") * VOICE["rate"]))
    recognizer, mic = sr.Recognizer(), sr.Microphone()
    with mic as source:
        recognizer.adjust_for_ambient_noise(source)
    print("Listening. Say 'goodbye Brainiac' to stop.")
    while True:
        with mic as source:
            audio = recognizer.listen(source, phrase_time_limit=20)
        try:
            heard = recognizer.recognize_google(audio)
        except (sr.UnknownValueError, sr.RequestError):
            continue
        print(f"› {heard}")
        if heard.strip().lower().startswith("goodbye brainiac"):
            engine.say("Until next time.")
            engine.runAndWait()
            brainiac.wait_idle()
            return 0
        reply = brainiac.converse(heard, session=session).text
        print(reply)
        engine.say(speakable(reply))
        engine.runAndWait()
