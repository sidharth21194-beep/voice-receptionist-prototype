"""Assemble deploy/agent/: the files LiveKit Cloud needs to build and run the live agent in a container.

Copies the agent modules (so there is one source of truth), and writes the Dockerfile and requirements.
Run: python scripts/make_deploy.py
"""
import os
import shutil

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "deploy", "agent")
FILES = ["live_agent.py", "agent_claude.py", "agent_text.py", "mock_records.py", "scenarios.py", "trace_text.py",
         "audio_warmup.py"]

REQUIREMENTS = """livekit-agents[anthropic,deepgram,silero,turn-detector]==1.8.12
anthropic==1.17.0
google-genai==3.4.0
python-dotenv==1.2.4
numpy
"""

DOCKERFILE = """FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends gcc g++ && rm -rf /var/lib/apt/lists/*
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
# fetch the turn-detector and voice-activity models at build time so calls start fast
RUN python live_agent.py download-files
CMD ["python", "live_agent.py", "start"]
"""

os.makedirs(OUT, exist_ok=True)
for f in FILES:
    shutil.copy(os.path.join(ROOT, "agent", f), os.path.join(OUT, f))
open(os.path.join(OUT, "requirements.txt"), "w", newline="\n").write(REQUIREMENTS)
open(os.path.join(OUT, "Dockerfile"), "w", newline="\n").write(DOCKERFILE)
open(os.path.join(OUT, ".dockerignore"), "w", newline="\n").write(".env\n__pycache__\n*.pyc\n")
print("wrote", OUT, os.listdir(OUT))
