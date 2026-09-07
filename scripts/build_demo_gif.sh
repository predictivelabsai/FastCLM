#!/usr/bin/env bash
set -euo pipefail

repo_dir="$(cd "$(dirname "$0")/.." && pwd)"
manifest="$repo_dir/screenshots/manifest.txt"
docs_gif="$repo_dir/docs/demo/fastclm-walkthrough.gif"
landing_gif="$repo_dir/static/product-demo.gif"

test -s "$manifest" || { echo "Missing screenshots/manifest.txt; run scripts/capture_demo.py first." >&2; exit 1; }
mkdir -p "$repo_dir/docs/demo"

frames=()
while IFS= read -r frame; do
  test -n "$frame" || continue
  path="$repo_dir/screenshots/$frame"
  test -s "$path" || { echo "Missing walkthrough frame: $path" >&2; exit 1; }
  frames+=("$path")
done < "$manifest"

test "${#frames[@]}" -gt 1 || { echo "Need at least two frames." >&2; exit 1; }
convert -delay 180 -loop 0 -resize 1080x -layers Optimize "${frames[@]}" "$docs_gif"
cp "$docs_gif" "$landing_gif"
cmp -s "$docs_gif" "$landing_gif"
echo "Built ${#frames[@]}-frame walkthrough: $docs_gif"
