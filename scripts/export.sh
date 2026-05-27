#!/usr/bin/env bash
# Platform-specific FFmpeg encoding for exported shorts
# Usage: bash export.sh --input-dir DIR --platform PLATFORM --output-dir DIR
set -euo pipefail

INPUT_DIR=""
PLATFORM="all"
OUTPUT_DIR="./shorts"

while [[ $# -gt 0 ]]; do
    case "$1" in
        --input-dir) INPUT_DIR="$2"; shift 2 ;;
        --platform) PLATFORM="$2"; shift 2 ;;
        --output-dir) OUTPUT_DIR="$2"; shift 2 ;;
        --force) FORCE=true; shift ;;
        *) echo "Unknown option: $1" >&2; exit 1 ;;
    esac
done

if [ -z "$INPUT_DIR" ]; then
    echo "Usage: export.sh --input-dir DIR [--platform youtube|tiktok|instagram|all] [--output-dir DIR]"
    exit 1
fi

mkdir -p "$OUTPUT_DIR"

# Detect GPU
HAS_NVENC=false
if command -v nvidia-smi &>/dev/null && ffmpeg -hide_banner -encoders 2>/dev/null | grep -q h264_nvenc; then
    HAS_NVENC=true
fi

encode_youtube() {
    local input="$1" output="$2"
    if [ "$HAS_NVENC" = true ]; then
        ffmpeg -y -i "$input" \
            -c:v h264_nvenc -preset p5 -tune hq \
            -b:v 12M -maxrate 14M -bufsize 24M \
            -profile:v high -level 4.2 \
            -c:a aac -b:a 192k -ar 48000 \
            -pix_fmt yuv420p -movflags +faststart "$output"
    else
        ffmpeg -y -i "$input" \
            -c:v libx264 -preset slow \
            -b:v 12M -maxrate 14M -bufsize 24M \
            -profile:v high -level 4.2 \
            -c:a aac -b:a 192k -ar 48000 \
            -pix_fmt yuv420p -movflags +faststart "$output"
    fi
}

encode_tiktok() {
    local input="$1" output="$2"
    if [ "$HAS_NVENC" = true ]; then
        ffmpeg -y -i "$input" \
            -c:v h264_nvenc -preset p5 -tune hq \
            -cq 18 -maxrate 10M -bufsize 20M \
            -c:a aac -b:a 128k -ar 44100 \
            -pix_fmt yuv420p -movflags +faststart "$output"
    else
        ffmpeg -y -i "$input" \
            -c:v libx264 -preset slow -crf 18 \
            -maxrate 10M -bufsize 20M \
            -c:a aac -b:a 128k -ar 44100 \
            -pix_fmt yuv420p -movflags +faststart "$output"
    fi
}

encode_instagram() {
    local input="$1" output="$2"
    if [ "$HAS_NVENC" = true ]; then
        ffmpeg -y -i "$input" \
            -c:v h264_nvenc -preset p5 -tune hq \
            -b:v 4500k -maxrate 5000k -bufsize 10M \
            -profile:v high -level 4.2 \
            -c:a aac -b:a 128k -ar 44100 \
            -pix_fmt yuv420p -movflags +faststart "$output"
    else
        ffmpeg -y -i "$input" \
            -c:v libx264 -preset slow \
            -b:v 4500k -maxrate 5000k -bufsize 10M \
            -profile:v high -level 4.2 \
            -c:a aac -b:a 128k -ar 44100 \
            -pix_fmt yuv420p -movflags +faststart "$output"
    fi
}

# Process each rendered short
COUNT=0
for input_file in "$INPUT_DIR"/*_v.mp4; do
    [ -f "$input_file" ] || continue
    COUNT=$((COUNT + 1))

    base=$(basename "$input_file" _v.mp4)

    platforms=()
    if [ "$PLATFORM" = "all" ]; then
        platforms=("youtube" "tiktok" "instagram")
    else
        platforms=("$PLATFORM")
    fi

    for plat in "${platforms[@]}"; do
        case "$plat" in
            youtube)   suffix="_yt"; encode_func="encode_youtube" ;;
            tiktok)    suffix="_tt"; encode_func="encode_tiktok" ;;
            instagram) suffix="_ig"; encode_func="encode_instagram" ;;
            *) echo "Unknown platform: $plat" >&2; continue ;;
        esac

        output_file="$OUTPUT_DIR/${base}${suffix}.mp4"
        $encode_func "$input_file" "$output_file"
        echo "Exported: $output_file"
    done
done

echo "Exported $COUNT clips to $OUTPUT_DIR/"
