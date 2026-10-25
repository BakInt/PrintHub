"""OpenCV 卡片自动识别（可选依赖，导入失败整体降级为仅手动四点裁剪）。

方法：灰度 → 模糊 → Canny 边缘 → 最大四边形轮廓 → 多边形逼近 → 角点排序。
置信度不足（轮廓面积占比过低、长宽比与目标偏差过大）视为失败，交回手动裁剪，
绝不动用户的图。首版只做「找到卡片并摆正」，不做遮挡/反光修复类重处理。
"""

from PIL import Image

try:  # opencv-python-headless 是可选依赖：不装时全流程仍可用（手动裁剪兜底）。
    import cv2
    import numpy as np

    OPENCV_AVAILABLE = True
except Exception:  # pragma: no cover - 环境相关
    cv2 = None
    np = None
    OPENCV_AVAILABLE = False

# 轮廓面积占整图比例低于该值视为不可信（卡片应占画面主体）。
MIN_AREA_RATIO = 0.15
# 长宽比与目标偏差超过该比例视为可疑（用户可能拍的是别的东西）。
MAX_ASPECT_DEVIATION = 0.45


def opencv_available() -> bool:
    return OPENCV_AVAILABLE


def _order_corners(points) -> list[tuple[float, float]]:
    """任意四点 → 顺时针 TL,TR,BR,BL（按坐标和/差投影定位四角）。"""
    summed = [p[0] + p[1] for p in points]
    diffed = [p[0] - p[1] for p in points]
    tl = points[summed.index(min(summed))]
    br = points[summed.index(max(summed))]
    tr = points[diffed.index(max(diffed))]
    bl = points[diffed.index(min(diffed))]
    return [tl, tr, br, bl]


def detect_card_quad(image: Image.Image, target_aspect: float) -> list[list[float]] | None:
    """在照片里找卡片主体，返回归一化四点（TL,TR,BR,BL，顺时针）；不可信返回 None。"""
    if not OPENCV_AVAILABLE:
        return None
    try:
        rgb = np.array(image.convert("RGB"))
        # 限制处理尺寸，避免超大照片拖慢识别（不影响归一化坐标语义）。
        max_side = 1600
        scale = min(1.0, max_side / max(rgb.shape[0], rgb.shape[1]))
        if scale < 1.0:
            rgb = cv2.resize(rgb, (int(rgb.shape[1] * scale), int(rgb.shape[0] * scale)), interpolation=cv2.INTER_AREA)
        height, width = rgb.shape[:2]

        gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
        blurred = cv2.GaussianBlur(gray, (5, 5), 0)
        edges = cv2.Canny(blurred, 50, 150)
        edges = cv2.dilate(edges, np.ones((3, 3), np.uint8), iterations=2)

        contours, _ = cv2.findContours(edges, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        if not contours:
            return None
        image_area = width * height
        candidates = sorted(contours, key=cv2.contourArea, reverse=True)[:5]
        for contour in candidates:
            area = cv2.contourArea(contour)
            if area < MIN_AREA_RATIO * image_area:
                continue
            peri = cv2.arcLength(contour, True)
            approx = cv2.approxPolyDP(contour, 0.02 * peri, True)
            if len(approx) != 4 or not cv2.isContourConvex(approx):
                continue
            corners = _order_corners([(float(p[0][0]), float(p[0][1])) for p in approx])
            top = ((corners[0][0] - corners[1][0]) ** 2 + (corners[0][1] - corners[1][1]) ** 2) ** 0.5
            left = ((corners[0][0] - corners[3][0]) ** 2 + (corners[0][1] - corners[3][1]) ** 2) ** 0.5
            if top <= 0 or left <= 0:
                continue
            aspect = top / left
            if target_aspect > 0 and abs(aspect - target_aspect) / target_aspect > MAX_ASPECT_DEVIATION:
                continue
            return [[max(0.0, min(1.0, x / width)), max(0.0, min(1.0, y / height))] for x, y in corners]
        return None
    except Exception:
        # 识别是尽力而为的增强，任何异常都交回手动裁剪，绝不阻断生成。
        return None
