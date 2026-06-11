import os
import sys

os.environ.setdefault("MISTRAL_API_KEY", "test-mistral-api-key-for-tests")
os.environ.setdefault("LLM_PROVIDER", "mistral")
os.environ.setdefault("LLM_MODEL", "open-mistral-nemo")
os.environ.setdefault("VISION_MODEL", "pixtral-12b-2409")
