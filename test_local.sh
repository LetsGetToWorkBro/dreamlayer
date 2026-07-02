#!/bin/bash
set -e
echo "== pytest ==" && cd ~/dreamlayer/host-python && pytest -q
echo "== static checks ==" && cd ~/dreamlayer
grep -rIn "frame.display.polygon(" halo-lua/ && exit 1 || echo "OK: no polygon"
grep -rIn "frame.display.bitmap" halo-lua/ && exit 1 || echo "OK: no bitmap"
LC_ALL=C grep -rIn '[^ -~]' halo-lua/*.lua halo-lua/**/*.lua && exit 1 || echo "OK: ASCII clean"
echo "== emulator boot ==" && cd ~/brilliant_sdk/python && uv run python -c "
from halo_emulator import HaloEmulator
d='/Users/aracelisilva/dreamlayer/halo-lua'
with HaloEmulator(sandbox_dir=d) as emu:
    emu.load_directory(d); emu.start('main.lua'); emu.wait(1.0)
    emu.get_framebuffer().save('/Users/aracelisilva/ready_card.png')
print('boot OK')
"
echo "ALL LOCAL TESTS PASSED"
