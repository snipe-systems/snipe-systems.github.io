"""Voice enrollment CLI.

Records a handful of short phrases of YOUR voice and stores an averaged
speaker embedding so only your voice may execute trades. Run:

    voice-trader-enroll
"""

from __future__ import annotations

import sys

PHRASES = [
    "Buy ten shares of Apple at two hundred thirty.",
    "Sell half my Tesla position.",
    "Cancel all my open orders.",
    "What's my delta on my SPY put?",
    "This is my voice for trading authorization.",
]


def main() -> int:
    from ..audio.mic import Microphone, MicrophoneUnavailable
    from .verify import SpeakerVerifier

    mic = Microphone()
    if not mic.available():
        print("ERROR: sounddevice not installed. Run: pip install voice-trader[audio]")
        return 1

    verifier = SpeakerVerifier()
    if not verifier._load_classifier():
        print("ERROR: speaker model not available. Run: pip install voice-trader[speaker]")
        return 1

    print("Voice enrollment. Record each phrase clearly. Press Enter to record, or q to quit.")
    for i, phrase in enumerate(PHRASES, 1):
        answer = input(f"\n[{i}/{len(PHRASES)}] '{phrase}'\nPress Enter to record: ").strip()
        if answer.lower() == "q":
            break
        print("  Recording... speak now.")
        audio = mic.record(max_seconds=5.0)
        if audio is None:
            print("  No audio captured. Skipping.")
            continue
        verifier.enroll(audio, name="default")
        print(f"  Phrase {i} captured and enrolled.")

    if "default" in verifier.enrolled_speakers():
        print("\nEnrollment complete. Speaker 'default' is enrolled.")
        print("Set VOICE_AUTH_ENABLED=1 and VOICE_AUTH_REQUIRED=1 in .env to enforce it.")
        return 0
    print("\nNo phrases enrolled.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
