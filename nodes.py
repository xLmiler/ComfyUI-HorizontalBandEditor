import os
from typing import List, Tuple

import numpy as np
import torch
from PIL import Image, ImageDraw, ImageFont

MAX_RESOLUTION = 16384
REGION_LABELS = tuple("ABCDEFGHIJKL")


def _kw(kwargs, names, default=None):
    for name in names:
        if name in kwargs:
            return kwargs[name]
    return default


def _parse_hex_color(value: str, default: Tuple[int, int, int, int]) -> Tuple[int, int, int, int]:
    if not isinstance(value, str):
        return default
    value = value.strip().lstrip("#")
    try:
        if len(value) == 3:
            r, g, b = (int(ch * 2, 16) for ch in value)
            return r, g, b, 255
        if len(value) == 6:
            return int(value[0:2], 16), int(value[2:4], 16), int(value[4:6], 16), 255
        if len(value) == 8:
            return (
                int(value[0:2], 16), int(value[2:4], 16),
                int(value[4:6], 16), int(value[6:8], 16),
            )
    except ValueError:
        pass
    return default


def _font_candidates(user_value: str) -> List[str]:
    candidates: List[str] = []
    if user_value and user_value.strip():
        raw = user_value.strip().strip('"')
        candidates.append(raw)
        aliases = {
            "simhei": [r"C:\Windows\Fonts\simhei.ttf"],
            "黑体": [r"C:\Windows\Fonts\simhei.ttf"],
            "微软雅黑": [r"C:\Windows\Fonts\msyh.ttc", r"C:\Windows\Fonts\msyh.ttf"],
            "microsoft yahei": [r"C:\Windows\Fonts\msyh.ttc", r"C:\Windows\Fonts\msyh.ttf"],
            "noto sans cjk": [
                "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
                "/usr/share/fonts/opentype/noto/NotoSansCJKsc-Regular.otf",
            ],
        }
        candidates.extend(aliases.get(raw.lower(), []))

    candidates.extend([
        r"C:\Windows\Fonts\simhei.ttf",
        r"C:\Windows\Fonts\msyh.ttc",
        r"C:\Windows\Fonts\msyh.ttf",
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/opentype/noto/NotoSansCJKsc-Regular.otf",
        "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc",
        "/usr/share/fonts/truetype/wqy/wqy-microhei.ttc",
        "/System/Library/Fonts/PingFang.ttc",
        "/System/Library/Fonts/STHeiti Light.ttc",
        "/System/Library/Fonts/STHeiti Medium.ttc",
    ])

    out, seen = [], set()
    for p in candidates:
        if p not in seen:
            seen.add(p)
            out.append(p)
    return out


def _load_font(font_name_or_path: str, font_size: int) -> ImageFont.FreeTypeFont:
    errors = []
    for candidate in _font_candidates(font_name_or_path):
        try:
            if os.path.exists(candidate) or os.path.sep not in candidate:
                return ImageFont.truetype(candidate, font_size)
        except Exception as exc:
            errors.append(f"{candidate}: {exc}")
    raise RuntimeError(
        "没有找到可用的简中字体。默认尝试 SimHei / 微软雅黑 / Noto Sans CJK。"
        "请在“字体名称或路径”中填写字体文件完整路径，例如 C:\\Windows\\Fonts\\simhei.ttf。"
        + ("\n尝试记录：\n" + "\n".join(errors[-5:]) if errors else "")
    )


def _measure_text(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.FreeTypeFont):
    return draw.textbbox((0, 0), text if text else "国Ag", font=font)


def _wrap_text_by_width(draw, text, font, max_width):
    max_width = max(1, int(max_width))
    if not text:
        return [""]
    lines = []
    for paragraph in text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        if paragraph == "":
            lines.append("")
            continue
        current = ""
        for ch in paragraph:
            trial = current + ch
            bbox = _measure_text(draw, trial, font)
            if current and bbox[2] - bbox[0] > max_width:
                lines.append(current)
                current = ch
            else:
                current = trial
        lines.append(current)
    return lines or [""]


def _text_layout(text, width, font, padding, line_spacing):
    temp = Image.new("RGBA", (max(1, width), 8), (0, 0, 0, 0))
    draw = ImageDraw.Draw(temp)
    lines = _wrap_text_by_width(draw, text, font, max(1, width - padding * 2))
    ref = _measure_text(draw, "国Ag", font)
    line_height = max(1, ref[3] - ref[1])
    total_height = len(lines) * line_height + max(0, len(lines) - 1) * line_spacing
    return lines, line_height, total_height


def _draw_text_panel(width, selected_height, text, font_name_or_path, font_size,
                     text_color, panel_background, background_color, padding,
                     line_spacing, horizontal_align, vertical_align):
    font = _load_font(font_name_or_path, font_size)
    lines, line_height, text_height = _text_layout(text, width, font, padding, line_spacing)
    panel_height = max(1, selected_height, text_height + padding * 2)

    if panel_background == "透明":
        bg = (0, 0, 0, 0)
    else:
        c = _parse_hex_color(background_color, (255, 255, 255, 255))
        bg = (c[0], c[1], c[2], 255)

    panel = Image.new("RGBA", (width, panel_height), bg)
    draw = ImageDraw.Draw(panel)
    fg = _parse_hex_color(text_color, (0, 0, 0, 255))

    if vertical_align == "顶部":
        y = padding
    elif vertical_align == "底部":
        y = max(padding, panel_height - padding - text_height)
    else:
        y = max(padding, (panel_height - text_height) // 2)

    for line in lines:
        bbox = _measure_text(draw, line if line else " ", font)
        line_width = max(0, bbox[2] - bbox[0]) if line else 0
        if horizontal_align == "左对齐":
            x = padding
        elif horizontal_align == "右对齐":
            x = max(padding, width - padding - line_width)
        else:
            x = max(padding, (width - line_width) // 2)
        if line:
            draw.text((x - bbox[0], y - bbox[1]), line, font=font, fill=fg)
        y += line_height + line_spacing
    return panel


def _pil_to_tensors(img_rgba: Image.Image):
    rgba = np.asarray(img_rgba.convert("RGBA"), dtype=np.float32) / 255.0
    rgb = rgba[..., :3]
    alpha = rgba[..., 3]
    return (
        torch.from_numpy(rgb.copy()).unsqueeze(0),
        torch.from_numpy((1.0 - alpha).copy()).unsqueeze(0),
        torch.from_numpy(rgba.copy()).unsqueeze(0),
    )


def _tensor_to_pil(input_image: torch.Tensor, input_alpha_mask=None) -> Image.Image:
    if input_image is None:
        raise ValueError("“输入图像”不能为空，请连接“加载图像”或其他 IMAGE 输出。")
    if not isinstance(input_image, torch.Tensor):
        input_image = torch.as_tensor(input_image)
    image_tensor = input_image.detach().cpu().float()
    if image_tensor.ndim == 4:
        image_tensor = image_tensor[0]
    if image_tensor.ndim != 3:
        raise ValueError(f"输入图像维度不正确：{tuple(input_image.shape)}")
    image_np = image_tensor.clamp(0.0, 1.0).numpy()
    if image_np.shape[-1] < 3:
        raise ValueError("输入图像至少需要 RGB 三个通道。")
    rgb = (image_np[..., :3] * 255.0).round().astype(np.uint8)

    alpha = np.full((rgb.shape[0], rgb.shape[1]), 255, dtype=np.uint8)
    if input_alpha_mask is not None:
        mask_tensor = input_alpha_mask.detach().cpu().float() if isinstance(input_alpha_mask, torch.Tensor) else torch.as_tensor(input_alpha_mask, dtype=torch.float32)
        if mask_tensor.ndim == 3:
            mask_tensor = mask_tensor[0]
        if mask_tensor.ndim != 2:
            raise ValueError(f"输入透明遮罩维度不正确：{tuple(mask_tensor.shape)}")
        mask_np = mask_tensor.clamp(0.0, 1.0).numpy()
        if mask_np.shape != alpha.shape:
            raise ValueError(f"输入透明遮罩尺寸 {mask_np.shape[::-1]} 与输入图像尺寸 {alpha.shape[::-1]} 不一致。")
        alpha = ((1.0 - mask_np) * 255.0).round().astype(np.uint8)
    return Image.fromarray(np.dstack([rgb, alpha]), mode="RGBA")


def _collect_regions(kwargs, height):
    count = int(_kw(kwargs, ("截面数量", "region_count"), 1))
    count = max(1, min(len(REGION_LABELS), count))
    regions = []

    for i, label in enumerate(REGION_LABELS[:count]):
        legacy_top = "selection_top_px" if i == 0 else f"region_{label.lower()}_top"
        legacy_bottom = "selection_bottom_px" if i == 0 else f"region_{label.lower()}_bottom"
        top = int(_kw(kwargs, (f"截面{label}上边界(px)", "选区上边界(px)" if i == 0 else "", legacy_top), 0))
        bottom = int(_kw(kwargs, (f"截面{label}下边界(px)", "选区下边界(px)" if i == 0 else "", legacy_bottom), 0))
        top = max(0, min(height - 1, top))
        bottom = max(0, min(height, bottom))
        if bottom > top:
            regions.append([top, bottom])

    if not regions:
        regions = [[0, min(1, height)]]

    regions.sort(key=lambda v: (v[0], v[1]))
    merged = []
    for top, bottom in regions:
        if not merged or top > merged[-1][1]:
            merged.append([top, bottom])
        else:
            merged[-1][1] = max(merged[-1][1], bottom)
    return merged


class HorizontalBandEditor:
    @classmethod
    def INPUT_TYPES(cls):
        required = {
            "输入图像": ("IMAGE", {"tooltip": "连接 ComfyUI 的“加载图像”或其他 IMAGE 输出。"}),
            "截面数量": ("INT", {
                "default": 1, "min": 1, "max": len(REGION_LABELS), "step": 1,
                "tooltip": "最多可同时编辑 12 个横向截面。增加数量后会自动切换到新截面。",
            }),
            "编辑截面": (list(REGION_LABELS), {
                "default": "A",
                "tooltip": "选择当前在预览中编辑的截面。也可以直接点击预览中的已有截面切换。",
            }),
        }

        for i, label in enumerate(REGION_LABELS):
            required[f"截面{label}上边界(px)"] = (
                "INT", {"default": 0, "min": 0, "max": MAX_RESOLUTION, "step": 1}
            )
            required[f"截面{label}下边界(px)"] = (
                "INT", {"default": 1 if i == 0 else 0, "min": 0, "max": MAX_RESOLUTION, "step": 1}
            )

        required.update({
            "启用文字面板": ("BOOLEAN", {
                "default": False,
                "label_on": "开启：以文字面板替换截面",
                "label_off": "关闭：删除截面并拼接",
            }),
            "面板背景": (["纯色", "透明"], {"default": "纯色"}),
            "背景颜色": ("STRING", {"default": "#FFFFFF", "multiline": False}),
            "文字内容": ("STRING", {"default": "在这里输入文字", "multiline": True}),
            "文字颜色": ("STRING", {"default": "#000000", "multiline": False}),
            "字体名称或路径": ("STRING", {
                "default": "SimHei", "multiline": False,
                "tooltip": "默认使用简中黑体。也可以填写字体文件完整路径。",
            }),
            "字号": ("INT", {"default": 48, "min": 1, "max": 1024, "step": 1}),
            "内边距": ("INT", {"default": 24, "min": 0, "max": 2048, "step": 1}),
            "行距": ("INT", {"default": 8, "min": 0, "max": 1024, "step": 1}),
            "水平对齐": (["居中", "左对齐", "右对齐"], {"default": "居中"}),
            "垂直对齐": (["居中", "顶部", "底部"], {"default": "居中"}),
        })

        return {
            "required": required,
            "optional": {"输入透明遮罩": ("MASK",)},
        }

    RETURN_TYPES = ("IMAGE", "MASK", "IMAGE", "INT", "INT")
    RETURN_NAMES = ("RGB图像", "透明遮罩", "RGBA图像", "宽度", "高度")
    FUNCTION = "process"
    CATEGORY = "图像/编辑"
    DESCRIPTION = "使用 ComfyUI 原生参数控件配置多个横向截面；预览固定在节点参数下方。"

    @classmethod
    def VALIDATE_INPUTS(cls, **kwargs):
        return True

    @classmethod
    def IS_CHANGED(cls, **kwargs):
        return float("nan")

    def process(self, **kwargs):
        input_image = _kw(kwargs, ("输入图像", "input_image"))
        input_alpha_mask = _kw(kwargs, ("输入透明遮罩", "input_alpha_mask"), None)
        src = _tensor_to_pil(input_image, input_alpha_mask)
        width, height = src.size

        regions = _collect_regions(kwargs, height)
        text_panel_enabled = bool(_kw(kwargs, ("启用文字面板", "text_panel_enabled"), False))

        panel_background = _kw(kwargs, ("面板背景", "panel_background"), "纯色")
        background_color = _kw(kwargs, ("背景颜色", "background_color"), "#FFFFFF")
        text = _kw(kwargs, ("文字内容", "text"), "在这里输入文字")
        text_color = _kw(kwargs, ("文字颜色", "text_color"), "#000000")
        font_name_or_path = _kw(kwargs, ("字体名称或路径", "font_name_or_path"), "SimHei")
        font_size = int(_kw(kwargs, ("字号", "font_size"), 48))
        padding = int(_kw(kwargs, ("内边距", "padding"), 24))
        line_spacing = int(_kw(kwargs, ("行距", "line_spacing"), 8))
        horizontal_align = _kw(kwargs, ("水平对齐", "horizontal_align"), "居中")
        vertical_align = _kw(kwargs, ("垂直对齐", "vertical_align"), "居中")

        pieces = []
        cursor = 0
        for top, bottom in regions:
            if top > cursor:
                pieces.append(src.crop((0, cursor, width, top)))

            if text_panel_enabled:
                pieces.append(_draw_text_panel(
                    width=width,
                    selected_height=bottom - top,
                    text=text,
                    font_name_or_path=font_name_or_path,
                    font_size=font_size,
                    text_color=text_color,
                    panel_background=panel_background,
                    background_color=background_color,
                    padding=padding,
                    line_spacing=line_spacing,
                    horizontal_align=horizontal_align,
                    vertical_align=vertical_align,
                ))
            cursor = max(cursor, bottom)

        if cursor < height:
            pieces.append(src.crop((0, cursor, width, height)))

        if not pieces:
            raise ValueError("不能删除整张图片。请至少保留一部分原图，或开启文字面板。")

        out_height = sum(piece.height for piece in pieces)
        out = Image.new("RGBA", (width, out_height), (0, 0, 0, 0))
        y = 0
        for piece in pieces:
            if piece.height <= 0:
                continue
            out.alpha_composite(piece, (0, y))
            y += piece.height

        rgb, mask, rgba = _pil_to_tensors(out)
        return rgb, mask, rgba, out.width, out.height


NODE_CLASS_MAPPINGS = {"HorizontalBandEditor": HorizontalBandEditor}
NODE_DISPLAY_NAME_MAPPINGS = {"HorizontalBandEditor": "横向截断 / 文字面板编辑器"}
