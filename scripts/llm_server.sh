#!/bin/sh
# The local LLM for everything (the Ask, briefs, text extraction): Qwen3.8-27B on llama.cpp, all on the GPU.
#   scripts/llm_server.sh            # serves llamacpp/qwen3.8-27b on 127.0.0.1:8081 (KEPT_LLAMACPP_API_BASE)
# Two 16k-token slots (the Ask's lookup prompt is ~9k tokens), 8-bit KV cache, thinking off. Needs ~15 GB of
# VRAM, so Ollama's model is unloaded first and `kept serve` keeps its own models on the CPU.
MODEL=${KEPT_LLM_GGUF:-$HOME/models/Qwen3.8-27B-UD-Q3_K_XL.gguf}
SERVER=${LLAMA_SERVER:-$HOME/llama.cpp/build/bin/llama-server}
command -v ollama >/dev/null && ollama ps 2>/dev/null | awk 'NR>1{print $1}' | xargs -r -n1 ollama stop
exec "$SERVER" -m "$MODEL" --alias qwen3.8-27b --host 127.0.0.1 --port 8081 \
  -ngl 99 -fa on -np 2 -c 32768 -ctk q8_0 -ctv q8_0 -ub 256 -b 1024 \
  --jinja --chat-template-kwargs '{"enable_thinking":false}' "$@"
