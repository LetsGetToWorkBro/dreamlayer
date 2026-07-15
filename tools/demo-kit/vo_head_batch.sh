#!/bin/bash
# slice each block to wav, run Wav2Lip sequentially
cd /tmp/wav2lip
python3 - <<'PY'
import json, subprocess
blocks=json.load(open('/tmp/blocks_t2.json'))
TAKE='REPLACE_WITH_YOUR_TAKE.mp3'
for b in blocks:
    ss=max(0.0,b['s']-0.12); dur=(b['e']-ss)+0.15
    subprocess.run(['ffmpeg','-y','-ss',f"{ss:.2f}",'-t',f"{dur:.2f}",'-i',TAKE,
        '-ar','16000','-ac','1',f"/tmp/yt/wavs/{b['name']}.wav"],capture_output=True)
print('wavs done')
PY
for f in /tmp/yt/wavs/*.wav; do
  n=$(basename "$f" .wav)
  echo "=== $n $(date +%H:%M:%S)"
  /tmp/w2l-venv/bin/python inference.py --checkpoint_path checkpoints/wav2lip_gan.pth \
    --face /tmp/yt/sf_loop.mp4 --audio "$f" --outfile "/tmp/yt/heads/$n.mp4" --pads 0 15 0 0 >/dev/null 2>&1
  ls -la "/tmp/yt/heads/$n.mp4" 2>/dev/null || echo "FAILED $n"
done
echo "BATCH DONE"
