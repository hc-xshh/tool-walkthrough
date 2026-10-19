#!/usr/bin/env bash
# OCR a screenshot and print words with bounding boxes (for locating click targets).
# Usage: ocr.sh <image.png> [lang] [psm]
set -euo pipefail
IMG="${1:?usage: ocr.sh <image.png> [lang] [psm]}"
LANG_="${2:-chi_sim+eng}"
PSM="${3:-11}"
TMP="$(mktemp -d)"
tesseract "$IMG" "$TMP/out" -l "$LANG_" --psm "$PSM" tsv >/dev/null 2>&1 || true
awk -F'\t' 'NR>1 && $12!="" && $11>=40 {printf "%s\tx=%s y=%s w=%s h=%s\tconf=%s\n",$12,$7,$8,$9,$10,$11}' "$TMP/out.tsv"
rm -rf "$TMP"
