#!/usr/bin/env bash
# setup_paddleocr_vl_macos.sh
#
# Install PaddleOCR-VL on Apple Silicon for writeup2md.
#
# Two runtime modes are supported (see reports/PADDLEOCR_VL_IDENTITY.json):
#
#   * paddleocr-vl-element  — HF transformers + torch (MPS). Works on
#                              Apple Silicon without PaddlePaddle. This is
#                              the recommended path on macOS arm64 today.
#
#   * paddleocr-vl          — full official PaddleOCR v1 pipeline. Requires
#                              paddleocr + paddlepaddle. PaddlePaddle ships
#                              arm64 wheels for macOS, but the pipeline
#                              currently leans on PaddlePaddle's CPU backend
#                              under Rosetta-free arm64; performance is
#                              lower than the element-mode MPS path.
#
# Usage:
#
#   ./scripts/setup_paddleocr_vl_macos.sh element   # recommended on Apple Silicon
#   ./scripts/setup_paddleocr_vl_macos.sh full
#   ./scripts/setup_paddleocr_vl_macos.sh both
#
# After install, verify:
#
#   python -m writeup2md doctor --require-paddleocr-vl
#   python -m writeup2md doctor --smoke-ocr evaluation/golden/code_py_light_01.png \
#       --ocr-backend paddleocr-vl-element --require-exact-backend

set -euo pipefail

MODE="${1:-element}"

case "$MODE" in
  element)
    echo "[1/2] installing paddleocr-vl-element deps (transformers + torch + huggingface_hub)..."
    pip install -e ".[paddleocr-vl-element]"
    echo "[2/2] verifying install..."
    python -m writeup2md doctor --require-paddleocr-vl
    ;;
  full)
    echo "[1/2] installing paddleocr-vl deps (paddleocr + paddlepaddle + transformers + torch)..."
    pip install -e ".[paddleocr-vl]"
    echo "[2/2] verifying install..."
    python -m writeup2md doctor --require-paddleocr-vl
    ;;
  both)
    echo "[1/2] installing both paddleocr-vl + paddleocr-vl-element deps..."
    pip install -e ".[paddleocr-vl]"
    echo "[2/2] verifying install..."
    python -m writeup2md doctor --require-paddleocr-vl
    ;;
  *)
    echo "usage: $0 {element|full|both}" >&2
    exit 1
    ;;
esac

echo
echo "Next steps:"
echo "  python -m writeup2md doctor --smoke-ocr evaluation/golden/code_py_light_01.png \\"
echo "      --ocr-backend paddleocr-vl-element --require-exact-backend"
echo
echo "  python -m writeup2md evaluate-ocr evaluation/golden/ \\"
echo "      --backend paddleocr-vl-element --output reports/golden-eval-paddleocr-vl"
