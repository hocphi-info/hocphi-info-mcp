#!/usr/bin/env bash
# Sinh src/hocphi_mcp/api_models.py tu openapi.json cua BE.
#
#   scripts/gen_models.sh                       # doc raw `main` cua hocphi-info-be
#   OPENAPI_SRC=../hocphi-info-be/openapi.json scripts/gen_models.sh   # file local
#
# Model sinh ra CHI de phan tich response cua BE (thuoc tinh snake_case, alias camelCase);
# model dau ra cua tool (U4) viet tay rieng. Khong sua api_models.py bang tay.
set -euo pipefail
cd "$(dirname "$0")/.."

SRC="${OPENAPI_SRC:-https://raw.githubusercontent.com/hocphi-info/hocphi-info-be/main/openapi.json}"
# Ten file co dinh ("openapi.json"): datamodel-codegen ghi ten file vao dau output,
# nen ten ngau nhien se lam moi lan sinh ra ban khac nhau va `gen-check` do oan.
DIR="$(mktemp -d)"
trap 'rm -rf "$DIR"' EXIT
TMP="$DIR/openapi.json"

if [[ "$SRC" =~ ^https?:// ]]; then
  curl -fsSL "$SRC" -o "$TMP"
else
  cp "$SRC" "$TMP"
fi

uv run datamodel-codegen \
  --input "$TMP" --input-file-type openapi \
  --output src/hocphi_mcp/api_models.py \
  --output-model-type pydantic_v2.BaseModel \
  --target-python-version 3.12 \
  --snake-case-field \
  --use-standard-collections --use-union-operator \
  --enum-field-as-literal all --collapse-root-models \
  --use-annotated --disable-timestamp \
  --formatters ruff-format

echo "Da sinh src/hocphi_mcp/api_models.py tu $SRC"
