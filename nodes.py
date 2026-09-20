import os
from typing import List, Tuple

import numpy as np
import torch
from PIL import Image, ImageDraw, ImageFont

MAX_RESOLUTION = 16384


# -------- 名称兼容：新中文键名 + 旧英文键名 --------
K_IMAGE_IN = ("输入图像", "input_image")
K_TEXT_PANEL_ENABLED = ("启用文字面板", "text_panel_enabled")
K_SELECTION_TOP = ("选区上边界(px)", "selection_top_px")
K_SELECTION_BOTTOM = ("选区下边界(px)", "selection_bottom_px")
K_PANEL_BACKGROUND = ("面板背景", "panel_background")
K_BACKGROUND_COLOR = ("背景颜色", "background_color")
K_TEXT = ("文字内容", "text")
K_TEXT_COLOR = ("文字颜色", "text_color")
K_FONT_NAME = ("字体名称或路径", "font_name_or_path")
K_FONT_SIZE = ("字号", "font_size")
K_PADDING = ("内边距", "padding")
K_LINE_SPACING = ("行距", "line_spacing")
K_HORIZONTAL_ALIGN = ("水平对齐", "horizontal_align")
K_VERTICAL_ALIGN = ("垂直对齐", "vertical_align")
K_INPUT_ALPHA_MASK = ("输入透明遮罩", "input_alpha_mask")


def _kw(kwargs, keys, default=None):
    for key in keys:
        if key in kwargs:
            return kwargs[key]
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
                int(value[0:2], 16),
                int(value[2:4], 16),
                int(value[4:6], 16),
                int(value[6:8], 16),
            )
    except ValueError:
        pass
    return default


def _font_candidates(user_value: str) -> List[str]:
    candidates: List[str] = []
    if user_value and user_value.strip():
        raw = user_value.strip().strip('"')
        candidates.append(raw)

        lowered = raw.lower()
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
        candidates.extend(aliases.get(lowered, []))

    candidates.extend(
        [
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
        ]
    )

    unique = []
    seen = set()
    for p in candidates:
        if p not in seen:
            seen.add(p)
            unique.append(p)
    return unique


def _load_font(font_name_or_path: str, font_size: int) -> ImageFont.FreeTypeFont:
    errors = []
    for candidate in _font_candidates(font_name_or_path):
        try:
            if os.path.exists(candidate) or os.path.sep not in candidate:
                return ImageFont.truetype(candidate, font_size)
        except Exception as exc:
            errors.append(f"{candidate}: {exc}")

    raise RuntimeError(
        "没有找到可用的简中字体。默认会尝试 SimHei / 微软雅黑 / Noto Sans CJK。"
        "请在“字体名称或路径”中填写字体文件完整路径，例如 "
        r"C:\Windows\Fonts\simhei.ttf。"
        + ("\n尝试记录：\n" + "\n".join(errors[-5:]) if errors else "")
    )


def _measure_text(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.FreeTypeFont) -> Tuple[int, int, int, int]:
    if text == "":
        return draw.textbbox((0, 0), "国Ag", font=font)
    return draw.textbbox((0, 0), text, font=font)


def _wrap_text_by_width(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.FreeTypeFont, max_width: int) -> List[str]:
    max_width = max(1, int(max_width))
    if not text:
        return [""]

    lines: List[str] = []
    paragraphs = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")

    for paragraph in paragraphs:
        if paragraph == "":
            lines.append("")
            continue

        current = ""
        for ch in paragraph:
            trial = current + ch
            bbox = _measure_text(draw, trial, font)
            width = bbox[2] - bbox[0]
            if current and width > max_width:
                lines.append(current)
                current = ch
            else:
                current = trial
        lines.append(current)

    return lines or [""]


def _text_layout(text: str, width: int, font: ImageFont.FreeTypeFont, padding: int, line_spacing: int) -> Tuple[List[str], int, int]:
    temp = Image.new("RGBA", (max(1, width), 8), (0, 0, 0, 0))
    draw = ImageDraw.Draw(temp)
    inner_width = max(1, width - padding * 2)
    lines = _wrap_text_by_width(draw, text, font, inner_width)

    ref_bbox = _measure_text(draw, "国Ag", font)
    line_height = max(1, ref_bbox[3] - ref_bbox[1])
    total_height = len(lines) * line_height + max(0, len(lines) - 1) * line_spacing
    return lines, line_height, total_height


def _draw_text_panel(
    width: int,
    selected_height: int,
    text: str,
    font_name_or_path: str,
    font_size: int,
    text_color: str,
    panel_background: str,
    background_color: str,
    padding: int,
    line_spacing: int,
    horizontal_align: str,
    vertical_align: str,
) -> Image.Image:
    font = _load_font(font_name_or_path, font_size)
    lines, line_height, text_height = _text_layout(text, width, font, padding, line_spacing)
    required_height = max(1, text_height + padding * 2)
    panel_height = max(1, selected_height, required_height)

    if panel_background == "透明":
        bg_rgba = (0, 0, 0, 0)
    else:
        bg_rgba = _parse_hex_color(background_color, (255, 255, 255, 255))
        bg_rgba = (bg_rgba[0], bg_rgba[1], bg_rgba[2], 255)

    panel = Image.new("RGBA", (width, panel_height), bg_rgba)
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
    rgb_tensor = torch.from_numpy(rgb.copy()).unsqueeze(0)
    mask_tensor = torch.from_numpy((1.0 - alpha).copy()).unsqueeze(0)
    rgba_tensor = torch.from_numpy(rgba.copy()).unsqueeze(0)
    return rgb_tensor, mask_tensor, rgba_tensor


def _tensor_to_pil(input_image: torch.Tensor, input_alpha_mask=None) -> Image.Image:
    if input_image is None:
        raise ValueError("“输入图像”不能为空，请连接“加载图像”或其他 IMAGE 输出。")
    if not isinstance(input_image, torch.Tensor):
        input_image = torch.as_tensor(input_image)

    image_tensor = input_image.detach().cpu().float()
    if image_tensor.ndim == 4:
        image_tensor = image_tensor[0]
    if image_tensor.ndim != 3:
        raise ValueError(f"输入图像维度不正确，期望 [B,H,W,C] 或 [H,W,C]，实际为 {tuple(input_image.shape)}")

    image_np = image_tensor.clamp(0.0, 1.0).numpy()
    if image_np.shape[-1] < 3:
        raise ValueError("输入图像至少需要 3 个通道 (RGB)。")
    rgb = (image_np[..., :3] * 255.0).round().astype(np.uint8)

    alpha = np.full((rgb.shape[0], rgb.shape[1]), 255, dtype=np.uint8)
    if input_alpha_mask is not None:
        mask_tensor = input_alpha_mask.detach().cpu().float() if isinstance(input_alpha_mask, torch.Tensor) else torch.as_tensor(input_alpha_mask, dtype=torch.float32)
        if mask_tensor.ndim == 3:
            mask_tensor = mask_tensor[0]
        if mask_tensor.ndim != 2:
            raise ValueError(f"输入透明遮罩维度不正确，期望 [B,H,W] 或 [H,W]，实际为 {tuple(mask_tensor.shape)}")
        mask_np = mask_tensor.clamp(0.0, 1.0).numpy()
        if mask_np.shape != alpha.shape:
            raise ValueError(f"输入透明遮罩尺寸 {mask_np.shape[::-1]} 与输入图像尺寸 {alpha.shape[::-1]} 不一致。")
        alpha = ((1.0 - mask_np) * 255.0).round().astype(np.uint8)

    rgba = np.dstack([rgb, alpha])
    return Image.fromarray(rgba, mode="RGBA")


class HorizontalBandEditor:
    """兼容原生控件与增强 DOM 面板的横向截断 / 文字面板编辑器。"""

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "输入图像": ("IMAGE", {"tooltip": "请连接 ComfyUI 的“加载图像”或其他 IMAGE 输出。"}),
                "启用文字面板": (
                    "BOOLEAN",
                    {
                        "default": False,
                        "label_on": "开启：替换为文字面板",
                        "label_off": "关闭：删除选区并拼接",
                    },
                ),
                "选区上边界(px)": ("INT", {"default": 0, "min": 0, "max": MAX_RESOLUTION, "step": 1}),
                "选区下边界(px)": ("INT", {"default": 1, "min": 1, "max": MAX_RESOLUTION, "step": 1}),
                "面板背景": (["纯色", "透明"], {"default": "纯色"}),
                "背景颜色": ("STRING", {"default": "#FFFFFF", "multiline": False}),
                "文字内容": ("STRING", {"default": "在这里输入文字", "multiline": True}),
                "文字颜色": ("STRING", {"default": "#000000", "multiline": False}),
                "字体名称或路径": (
                    "STRING",
                    {"default": "SimHei", "multiline": False, "tooltip": "默认简中黑体。也可填写字体文件完整路径。"},
                ),
                "字号": ("INT", {"default": 48, "min": 1, "max": 1024, "step": 1}),
                "内边距": ("INT", {"default": 24, "min": 0, "max": 2048, "step": 1}),
                "行距": ("INT", {"default": 8, "min": 0, "max": 1024, "step": 1}),
                "水平对齐": (["居中", "左对齐", "右对齐"], {"default": "居中"}),
                "垂直对齐": (["居中", "顶部", "底部"], {"default": "居中"}),
            },
            "optional": {"输入透明遮罩": ("MASK",)},
        }

    RETURN_TYPES = ("IMAGE", "MASK", "IMAGE", "INT", "INT")
    RETURN_NAMES = ("RGB图像", "透明遮罩", "RGBA图像", "宽度", "高度")
    FUNCTION = "process"
    CATEGORY = "图像/编辑"
    DESCRIPTION = (
        "连接“加载图像”后，可在增强面板中可视化拖拽横向选区；"
        "关闭文字面板时会删除选区并拼接上下部分；"
        "开启文字面板时会用纯色/透明面板替换选区；"
        "文字过多时会自动增加输出高度。"
    )

    @classmethod
    def VALIDATE_INPUTS(cls, **kwargs):
        return True

    @classmethod
    def IS_CHANGED(cls, **kwargs):
        return float("nan")

    def process(self, **kwargs):
        input_image = _kw(kwargs, K_IMAGE_IN)
        text_panel_enabled = bool(_kw(kwargs, K_TEXT_PANEL_ENABLED, False))
        selection_top_px = int(_kw(kwargs, K_SELECTION_TOP, 0))
        selection_bottom_px = int(_kw(kwargs, K_SELECTION_BOTTOM, 1))
        panel_background = _kw(kwargs, K_PANEL_BACKGROUND, "纯色")
        background_color = _kw(kwargs, K_BACKGROUND_COLOR, "#FFFFFF")
        text = _kw(kwargs, K_TEXT, "在这里输入文字")
        text_color = _kw(kwargs, K_TEXT_COLOR, "#000000")
        font_name_or_path = _kw(kwargs, K_FONT_NAME, "SimHei")
        font_size = int(_kw(kwargs, K_FONT_SIZE, 48))
        padding = int(_kw(kwargs, K_PADDING, 24))
        line_spacing = int(_kw(kwargs, K_LINE_SPACING, 8))
        horizontal_align = _kw(kwargs, K_HORIZONTAL_ALIGN, "居中")
        vertical_align = _kw(kwargs, K_VERTICAL_ALIGN, "居中")
        input_alpha_mask = _kw(kwargs, K_INPUT_ALPHA_MASK, None)

        src = _tensor_to_pil(input_image, input_alpha_mask)
        width, height = src.size

        y1 = max(0, min(int(selection_top_px), height - 1))
        y2 = max(1, min(int(selection_bottom_px), height))
        if y2 <= y1:
            y2 = min(height, y1 + 1)
            if y2 <= y1:
                y1 = max(0, height - 1)
                y2 = height

        top = src.crop((0, 0, width, y1))
        bottom = src.crop((0, y2, width, height))
        selected_height = y2 - y1

        if not text_panel_enabled:
            out_height = top.height + bottom.height
            if out_height <= 0:
                raise ValueError("不能删除整张图片。请至少保留上方或下方 1 像素。")
            out = Image.new("RGBA", (width, out_height), (0, 0, 0, 0))
            if top.height:
                out.alpha_composite(top, (0, 0))
            if bottom.height:
                out.alpha_composite(bottom, (0, top.height))
        else:
            panel = _draw_text_panel(
                width=width,
                selected_height=selected_height,
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
            )
            out_height = top.height + panel.height + bottom.height
            out = Image.new("RGBA", (width, out_height), (0, 0, 0, 0))
            if top.height:
                out.alpha_composite(top, (0, 0))
            out.alpha_composite(panel, (0, top.height))
            if bottom.height:
                out.alpha_composite(bottom, (0, top.height + panel.height))

        rgb, mask, rgba = _pil_to_tensors(out)
        return rgb, mask, rgba, out.width, out.height


NODE_CLASS_MAPPINGS = {"HorizontalBandEditor": HorizontalBandEditor}
NODE_DISPLAY_NAME_MAPPINGS = {"HorizontalBandEditor": "横向截断 / 文字面板编辑器"}
