import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import cv2, tempfile
from processing.reconstructor import Reconstructor
from file_io.loader import get_default_intrinsics

# --- Generate 10 synthetic RGB + depth image pairs in a temp folder ---
tmpdir = tempfile.mkdtemp()
pairs = []
for i in range(10):
    rgb = np.random.randint(0, 255, (480, 640, 3), dtype=np.uint8)
    depth = np.full((480, 640), 1000, dtype=np.uint16)   # flat plane at 1m
    rgb_path   = os.path.join(tmpdir, f'rgb_{i:04d}.png')
    depth_path = os.path.join(tmpdir, f'depth_{i:04d}.png')
    cv2.imwrite(rgb_path, rgb)
    cv2.imwrite(depth_path, depth)
    pairs.append((rgb_path, depth_path))

K, dist = get_default_intrinsics(640, 480)

frame_log = []
def on_frame(idx, total, pcd, fitness, rmse, status):
    frame_log.append(status)
    print(f'  Frame {idx}/{total} | {status} | fitness={fitness:.4f}')

final_pcd, succeed, fail = Reconstructor(
    pairs=pairs, K=K, dist=dist,
    depth_scale=1000.0,
    on_frame=on_frame
).run()

print(f'\nResult: {len(succeed)} success, {len(fail)} fail')
print(f'Final cloud points: {len(final_pcd.points)}')
assert len(final_pcd.points) > 0, 'Final cloud should not be empty'
print('\nSMOKE TEST PASSED')