# voice-trader — local HTTP API / headless runner image.
# Defaults to PAPER trading. It binds 0.0.0.0 so it is reachable from the host;
# do not expose this container to an untrusted network without authentication.

FROM python:3.12-slim

WORKDIR /app

COPY . .

# Core installs only (httpx, pyyaml, python-dotenv, numpy).
# Add audio/stt/speaker extras inside the image if you need voice input:
#   RUN pip install --no-cache-dir ".[audio,stt,speaker,tts]"
RUN pip install --no-cache-dir .

ENV VOICE_TRADER_MODE=paper

EXPOSE 8010

# Run the HTTP API. Override the command to run `voice-trader --json` instead.
CMD ["voice-trader", "--serve", "--host", "0.0.0.0", "--port", "8010"]
