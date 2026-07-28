import os
import sys

# Добавляем корень проекта в sys.path для импорта модулей
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

os.environ.setdefault("MISTRAL_API_KEY", "test-mistral-api-key-for-tests")
os.environ.setdefault("API_KEY", "test-api-key-for-tests")
os.environ.setdefault("LLM_PROVIDER", "mistral")
os.environ.setdefault("LLM_MODEL", "open-mistral-nemo")
os.environ.setdefault("VISION_MODEL", "pixtral-12b-2409")
