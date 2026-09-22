# apps/captcha/generator.py
import base64
import io
import logging
import os
import random

from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageOps

from .conf import conf

logger = logging.getLogger(__name__)

ALLOWED_EXT = {'.jpg', '.jpeg', '.png', '.webp'}

# 兼容 Pillow 9.1+ 的新枚举名
try:
    _RESAMPLE = Image.Resampling.LANCZOS
except AttributeError:  # pragma: no cover - 老版本 Pillow
    _RESAMPLE = Image.LANCZOS


class CaptchaGenerateError(Exception):
    """生成失败"""


# ---------------- 图片池 ----------------

def list_backgrounds():
    bg_dir = conf.BG_DIR
    if not bg_dir or not os.path.isdir(bg_dir):
        return []

    paths = []
    for name in os.listdir(bg_dir):
        stem, ext = os.path.splitext(name)
        if ext.lower() not in ALLOWED_EXT:
            continue
        if not stem or name.startswith('.'):
            continue
        paths.append(os.path.join(bg_dir, name))
    paths.sort()
    return paths


def load_background():
    """随机取一张背景图并归一化到标准画布"""
    paths = list_backgrounds()
    if not paths:
        raise CaptchaGenerateError(
            f'验证码背景图池为空，请把图片放到：{conf.BG_DIR}'
        )

    path = random.choice(paths)
    try:
        with Image.open(path) as img:
            img = ImageOps.exif_transpose(img)          # 处理手机拍摄的旋转信息
            img = img.convert('RGB')
            img = ImageOps.fit(                          # 居中裁剪 + 缩放，比例自适应
                img,
                (conf.WIDTH, conf.HEIGHT),
                method=_RESAMPLE,
                centering=(0.5, 0.5),
            )
    except Exception as exc:
        logger.error(f'读取背景图失败 {path}: {exc}')
        raise CaptchaGenerateError('验证码图片加载失败，请稍后重试') from exc

    return img, os.path.basename(path)


# ==== 拼图块形状

def _tile_mask(size):
    """生成拼图块形状的蒙版（L 模式，255 = 块内）。

    形状 = 左上角对齐的圆角方块 + 右侧一个圆形凸起。
    想换成真正的拼图形状，把这里换成读一张形状 PNG 即可，其它逻辑不用动。
    """
    mask = Image.new('L', (size, size), 0)
    draw = ImageDraw.Draw(mask)

    knob = max(10, size // 4)        # 凸起直径
    body = size - knob               # 主体边长
    radius = max(4, body // 5)

    draw.rounded_rectangle([0, 0, body, body], radius=radius, fill=255)

    kr = knob // 2
    cx, cy = body, body // 2
    draw.ellipse([cx - kr, cy - kr, cx + kr, cy + kr], fill=255)
    return mask


# =====  出图

def _to_base64_jpeg(img, quality=82):
    buf = io.BytesIO()
    img.convert('RGB').save(buf, format='JPEG', quality=quality, optimize=True)
    return 'data:image/jpeg;base64,' + base64.b64encode(buf.getvalue()).decode('ascii')


def _to_base64_png(img):
    buf = io.BytesIO()
    img.save(buf, format='PNG', optimize=True)
    return 'data:image/png;base64,' + base64.b64encode(buf.getvalue()).decode('ascii')


def make_captcha():
    """生成一次滑块

    返回 dict（**不含正确答案 x**，答案由调用方写入服务端存储）
        bg / tile        base64 图片
        target_x         缺口 x    仅内部使用 不要下发给前端
        target_y         缺口 y    这个不保密 洞口本来就在图上可见
        tile_size / width / height / track_width
        bg_name          命中的背景图文件名   便于排查
    """
    width, height = conf.WIDTH, conf.HEIGHT
    size = conf.TILE_SIZE
    margin = 8

    if size + margin * 2 >= width or size + margin * 2 >= height:
        raise CaptchaGenerateError('CAPTCHA.TILE_SIZE 相对于画布过大，请调小')

    bg, bg_name = load_background()

    x_min = max(margin, int(width * conf.X_RATIO_MIN))
    x_max = min(int(width * conf.X_RATIO_MAX), width - size - margin)
    if x_max <= x_min:
        x_min, x_max = margin, width - size - margin

    y_min, y_max = margin, height - size - margin
    if y_max <= y_min:
        y_max = y_min = margin

    target_x = random.randint(x_min, x_max)
    target_y = random.randint(y_min, y_max)

    mask = _tile_mask(size)

    # 1) 抠出拼图块
    crop = bg.crop((target_x, target_y, target_x + size, target_y + size)).convert('RGBA')
    tile = Image.new('RGBA', (size, size), (0, 0, 0, 0))
    tile.paste(crop, (0, 0), mask)

    # 2) 在背景上挖洞
    master = bg.convert('RGBA')
    hole = master.crop((target_x, target_y, target_x + size, target_y + size))
    hole = hole.filter(ImageFilter.GaussianBlur(2))
    hole.alpha_composite(Image.new('RGBA', hole.size, (0, 0, 0, 145)))
    master.paste(hole, (target_x, target_y), mask)

    outline = ImageChops.subtract(mask.filter(ImageFilter.MaxFilter(3)), mask)
    master.paste(
        Image.new('RGBA', (size, size), (255, 255, 255, 95)),
        (target_x, target_y),
        outline,
    )

    return {
        'bg': _to_base64_jpeg(master),
        'tile': _to_base64_png(tile),
        'target_x': target_x,
        'target_y': target_y,
        'tile_size': size,
        'width': width,
        'height': height,
        'track_width': width - size,
        'bg_name': bg_name,
    }
