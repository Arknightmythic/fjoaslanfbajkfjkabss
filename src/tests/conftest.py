"""
Shared Pytest Configuration and Test Fixtures.
Ensures zero touch to live production databases and external LLM APIs.
"""

import os

# Disable local file tracing and DB-backed answer auditing across all test sessions.
os.environ["CHATBOT_FILE_TRACE_ENABLED"] = "false"
os.environ["CHATBOT_ANSWER_AUDIT_ENABLED"] = "false"

# Set model defaults for test environment.
os.environ.setdefault("OPENAI_MODEL_NAME", "gemma4:31b-cloud")
os.environ.setdefault("OPENAI_API_KEY", "offline-test")
