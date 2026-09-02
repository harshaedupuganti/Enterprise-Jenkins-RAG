# Installation Notes

## Standard Install
pip install -r requirements.txt

## LLaMA 3 GGUF (GPU-Accelerated — NVIDIA RTX A3000)
pip install llama-cpp-python --extra-index-url [https://abetlen.github.io/llama-cpp-python/whl/cu121](https://abetlen.github.io/llama-cpp-python/whl/cu121)

## LLaMA 3 GGUF (CPU only fallback)
pip install llama-cpp-python

## Model Download
Download: Meta-Llama-3-8B-Instruct.Q4_K_M.gguf
Place at: C:\models\AI LOCAL\Meta-Llama-3-8B-Instruct.Q4_K_M.gguf
Source: [https://huggingface.co/QuantFactory/Meta-Llama-3-8B-Instruct-GGUF](https://huggingface.co/QuantFactory/Meta-Llama-3-8B-Instruct-GGUF)