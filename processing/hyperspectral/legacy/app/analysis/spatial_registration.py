import numpy as np
import cv2
import spectral
import matplotlib.pyplot as plt
from scipy.optimize import minimize

def normalize(img):
    img = img - img.min()
    img = img / (img.max() + 1e-8)
    return img


# ---------------- Mutual Information ----------------
def mutual_information(hgram):
    pxy = hgram / float(np.sum(hgram))
    px = np.sum(pxy, axis=1)
    py = np.sum(pxy, axis=0)

    px_py = px[:, None] * py[None, :]
    nz = pxy > 0

    return np.sum(pxy[nz] * np.log(pxy[nz] / (px_py[nz] + 1e-12)))


# ---------------- Registration Pipeline ----------------
def register_fx10_fx17(fx10_hdr, fx17_hdr):

    print("Loading cubes...")

    fx10 = spectral.open_image(fx10_hdr)
    fx17 = spectral.open_image(fx17_hdr)

    cube10 = fx10.load().astype(np.float32)
    cube17 = fx17.load().astype(np.float32)

    print("FX10:", cube10.shape)
    print("FX17:", cube17.shape)

    # wavelength filtering
    wl10 = np.array(fx10.metadata["wavelength"], dtype=float)
    wl17 = np.array(fx17.metadata["wavelength"], dtype=float)

    idx10 = np.where((wl10 >= 900) & (wl10 <= 1000))[0]
    idx17 = np.where((wl17 >= 900) & (wl17 <= 1000))[0]

    print(idx10)
    print(idx17)

    # grayscale projection
    I10 = normalize(np.mean(cube10[:, :, idx10], axis=2))
    I17 = normalize(np.mean(cube17[:, :, idx17], axis=2))

    H10, W10 = I10.shape
    I17 = cv2.resize(I17, (W10, H10))

    img1 = (I10 * 255).astype(np.uint8)
    img2 = (I17 * 255).astype(np.uint8)

    # ---------------- SIFT ----------------
    sift = cv2.SIFT_create()

    kp1, des1 = sift.detectAndCompute(img1, None)
    kp2, des2 = sift.detectAndCompute(img2, None)

    print("Keypoints FX10:", len(kp1))
    print("Keypoints FX17:", len(kp2))

    # ---------------- Matching ----------------
    matcher = cv2.BFMatcher(cv2.NORM_L2)
    matches = matcher.knnMatch(des1, des2, k=2)

    good = []
    for m, n in matches:
        if m.distance < 0.75 * n.distance:
            good.append(m)

    print("Good matches:", len(good))

    pts1 = np.float32([kp1[m.queryIdx].pt for m in good])
    pts2 = np.float32([kp2[m.trainIdx].pt for m in good])

    # ---------------- RANSAC ----------------
    M, inliers = cv2.estimateAffine2D(
        pts2,
        pts1,
        method=cv2.RANSAC,
        ransacReprojThreshold=5
    )

    print("Affine inliers:", np.sum(inliers))

    # ---------------- MI Refinement ----------------
    print("Refining with Mutual Information...")

    def warp_with_params(params, img):
        a, b, c, d, tx, ty = params
        M_ref = np.array([[a, b, tx],
                          [c, d, ty]], dtype=np.float32)

        return cv2.warpAffine(img, M_ref, (W10, H10))

    def mi_cost(params):
        warped = warp_with_params(params, I17)

        hgram, _, _ = np.histogram2d(
            I10.ravel(),
            warped.ravel(),
            bins=64
        )

        return -mutual_information(hgram)

    init_params = np.array([
        M[0, 0], M[0, 1],
        M[1, 0], M[1, 1],
        M[0, 2], M[1, 2]
    ])

    res = minimize(mi_cost, init_params, method='Powell')

    p = res.x
    M = np.array([[p[0], p[1], p[4]],
                  [p[2], p[3], p[5]]], dtype=np.float32)

    print("MI refinement done.")

    # ---------------- Warp full cube ----------------
    print("Warping cube...")

    bands = cube17.shape[2]
    cube17_resized = np.zeros((H10, W10, bands), dtype=np.float32)

    for b in range(bands):
        cube17_resized[:, :, b] = cv2.resize(
            cube17[:, :, b],
            (W10, H10)
        )

    cube17_registered = np.zeros_like(cube17_resized)

    for b in range(bands):
        cube17_registered[:, :, b] = cv2.warpAffine(
            cube17_resized[:, :, b],
            M,
            (W10, H10)
        )

    warped = cv2.warpAffine(I17, M, (W10, H10))

    # ---------------- Metrics ----------------
    print("\n========== REGISTRATION METRICS ==========")

    # 1. Mutual Information
    hgram, _, _ = np.histogram2d(
        I10.ravel(),
        warped.ravel(),
        bins=64
    )
    final_mi = mutual_information(hgram)
    print(f"Mutual Information: {final_mi:.6f}")

    # 2. Reprojection Error (using affine inliers)
    if inliers is not None:
        inlier_mask = inliers.ravel().astype(bool)

        pts2_in = pts2[inlier_mask]
        pts1_in = pts1[inlier_mask]

        pts2_h = np.hstack([pts2_in, np.ones((pts2_in.shape[0], 1))])
        pts2_warped = (M @ pts2_h.T).T

        reproj_errors = np.linalg.norm(pts2_warped - pts1_in, axis=1)

        mean_reproj = np.mean(reproj_errors)
        std_reproj = np.std(reproj_errors)
        max_reproj = np.max(reproj_errors)

        print(f"Mean Reprojection Error: {mean_reproj:.4f} pixels")
        print(f"Std Reprojection Error : {std_reproj:.4f} pixels")
        print(f"Max Reprojection Error : {max_reproj:.4f} pixels")

    # 3. Match statistics
    print(f"Detected keypoints FX10 : {len(kp1)}")
    print(f"Detected keypoints FX17 : {len(kp2)}")
    print(f"Good matches           : {len(good)}")

    if inliers is not None:
        num_inliers = np.sum(inliers)
        inlier_ratio = num_inliers / len(good)

        print(f"Affine Inliers         : {num_inliers}")
        print(f"Inlier Ratio           : {inlier_ratio:.4f}")

    print("==========================================\n")

    # ---------------- Visualization ----------------
    overlay = np.zeros((H10, W10, 3))
    overlay[:, :, 1] = normalize(I10)
    overlay[:, :, 0] = normalize(warped)
    overlay = np.clip(overlay, 0, 1)

    plt.figure(figsize=(12, 6))

    plt.subplot(151)
    plt.title("FX10")
    plt.imshow(I10, cmap='gray')

    plt.subplot(152)
    plt.title("FX17 (orig)")
    plt.imshow(img2, cmap='gray')

    plt.subplot(153)
    plt.title("Resized FX17")
    plt.imshow(I17, cmap='gray')

    plt.subplot(154)
    plt.title("Warped FX17")
    plt.imshow(warped, cmap='gray')

    plt.subplot(155)
    plt.title("Overlay")
    plt.imshow(overlay)

    plt.tight_layout()
    plt.show()

    return cube17_registered, M, inliers


# ---------------- Main ----------------
if __name__ == "__main__":

    # fx10_hdr = "/home/sriram/ANU/data/aruco_only_arucoplants/calibrated/nobg/004-specim-fx10_no_background.hdr"
    # fx17_corr_hdr = "/home/sriram/ANU/data/aruco_only_arucoplants/calibrated/nobg/004-specim-fx17_no_background.hdr"

    fx10_hdr = "/home/sriram/ANU/data/csiro_fx10_17_2_wheat/calibrated/004-specim-fx10_calibrated.hdr"
    fx17_corr_hdr = "/home/sriram/ANU/data/csiro_fx10_17_2_wheat/calibrated/corrected/004-specim-fx17_calibrated_corrected-FX17.hdr"

    cube17_registered, M, inliers = register_fx10_fx17(fx10_hdr, fx17_corr_hdr)
    msg = f"Registration Complete!\n\n"
    msg += f"Wrap Matrix (Affine 2x3):\n{M}\n\n"
    msg += f"Number of Affine Inliers: {np.sum(inliers)}\n"
    msg += f"Total Inliers: {np.sum(inliers)}"
    print(msg)
    