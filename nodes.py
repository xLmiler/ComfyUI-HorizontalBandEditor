import hashlib
import os
from typing import List, Tuple

import numpy as np
import torch
from PIL import Image, ImageDraw, ImageFont, ImageOps

import folder_paths
import node_helpers


MAX_RESOLUTION = 16384


def _parse_hex_color(value: str, default: Tuple[int, int, int, int]) -> Tuple[int, int, int, int]:
    """解析 #RGB / #RRGGBB / #RRGGBBAA。非法值回退到 default。"""
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
    """优先使用用户指定字体，其次按平台寻找常见简中黑体。"""
    candidates: List[str] = []
    if user_value and user_value.strip():
        raw = user_value.strip().strip('"')
        candidates.append(raw)

        # 允许只输入常用字体名，不要求完整路径。
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
            # Windows：简中黑体优先。
            r"C:\Windows\Fonts\simhei.ttf",
            r"C:\Windows\Fonts\msyh.ttc",
            r"C:\Windows\Fonts\msyh.ttf",
            # Linux 常见 CJK 字体。
            "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
            "/usr/share/fonts/opentype/noto/NotoSansCJKsc-Regular.otf",
            "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc",
            "/usr/share/fonts/truetype/wqy/wqy-microhei.ttc",
            # macOS。
            "/System/Library/Fonts/PingFang.ttc",
            "/System/Library/Fonts/STHeiti Light.ttc",
            "/System/Library/Fonts/STHeiti Medium.ttc",
        ]
    )

    # 去重但保持优先顺序。
    unique = []
    seen = set()
    for p in candidates:
        if p not in seen:
            seen.add(p)
            unique.append(p)
    return unique


def _load_font(font_name_or_path: str, font_size: int) -> ImageFont.FreeTypeFont:
    """加载可显示中文的字体；找不到时给出明确错误，而不是静默乱码。"""
    errors = []
    for candidate in _font_candidates(font_name_or_path):
        try:
            # 路径存在时直接加载；某些 Pillow/系统也支持通过字体名加载。
            if os.path.exists(candidate) or os.path.sep not in candidate:
                return ImageFont.truetype(candidate, font_size)
        except Exception as exc:  # noqa: BLE001 - 需要继续尝试后备字体
            errors.append(f"{candidate}: {exc}")

    raise RuntimeError(
        "没有找到可用的简中字体。默认会尝试 SimHei / 微软雅黑 / Noto Sans CJK。"
        "请在 font_name_or_path 中填写字体文件完整路径，例如 "
        r"C:\Windows\Fonts\simhei.ttf。"
        + ("\n尝试记录：\n" + "\n".join(errors[-5:]) if errors else "")
    )


def _measure_text(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.FreeTypeFont) -> Tuple[int, int, int, int]:
    if text == "":
        # 用代表性中文字符取字体高度。
        return draw.textbbox((0, 0), "国Ag", font=font)
    return draw.textbbox((0, 0), text, font=font)


def _wrap_text_by_width(
    draw: ImageDraw.ImageDraw,
    text: str,
    font: ImageFont.FreeTypeFont,
    max_width: int,
) -> List[str]:
    """
    按像素宽度自动换行。

    为了兼容中文不带空格的句子，这里按字符递增测量；英文同样可稳定工作，
    代价只是极端情况下可能在单词内部换行，但绝不会横向溢出。
    """
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


def _text_layout(
    text: str,
    width: int,
    font: ImageFont.FreeTypeFont,
    padding: int,
    line_spacing: int,
) -> Tuple[List[str], int, int]:
    """返回 lines、单行基准高度、总文字高度。"""
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
    """生成文字面板；文字放不下时自动增高，永不裁切。"""
    font = _load_font(font_name_or_path, font_size)
    lines, line_height, text_height = _text_layout(text, width, font, padding, line_spacing)
    required_height = max(1, text_height + padding * 2)
    panel_height = max(1, selected_height, required_height)

    if panel_background == "透明":
        bg_rgba = (0, 0, 0, 0)
    else:
        bg_rgba = _parse_hex_color(background_color, (255, 255, 255, 255))
        # “纯色背景”始终是不透明底色；若用户在颜色里写了 alpha 也统一为 255。
        bg_rgba = (bg_rgba[0], bg_rgba[1], bg_rgba[2], 255)

    panel = Image.new("RGBA", (width, panel_height), bg_rgba)
    draw = ImageDraw.Draw(panel)
    fg = _parse_hex_color(text_color, (0, 0, 0, 255))

    if text_height <= 0:
        return panel

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

        # bbox 可能有负 top/left，减去偏移让视觉位置更准确。
        if line:
            draw.text((x - bbox[0], y - bbox[1]), line, font=font, fill=fg)
        y += line_height + line_spacing

    return panel


def _pil_to_tensors(img_rgba: Image.Image):
    """
    输出：
      1) RGB IMAGE：标准 3 通道，适合绝大多数 ComfyUI 图像节点；
      2) MASK：ComfyUI 约定 1=透明；
      3) RGBA IMAGE：4 通道，可直接交给支持 alpha 的保存/处理节点。
    """
    rgba = np.asarray(img_rgba.convert("RGBA"), dtype=np.float32) / 255.0
    rgb = rgba[..., :3]
    alpha = rgba[..., 3]

    rgb_tensor = torch.from_numpy(rgb.copy()).unsqueeze(0)
    mask_tensor = torch.from_numpy((1.0 - alpha).copy()).unsqueeze(0)
    rgba_tensor = torch.from_numpy(rgba.copy()).unsqueeze(0)
    return rgb_tensor, mask_tensor, rgba_tensor


class HorizontalBandEditor:
    """加载图片，在节点预览中横向框选，然后删除该带状区域或替换成文字面板。"""

    @classmethod
    def INPUT_TYPES(cls):
        input_dir = folder_paths.get_input_directory()
        files = []
        if os.path.isdir(input_dir):
            files = [
                f
                for f in os.listdir(input_dir)
                if os.path.isfile(os.path.join(input_dir, f))
            ]
            try:
                files = folder_paths.filter_files_content_types(files, ["image"])
            except Exception:
                # 兼容较旧 ComfyUI。
                allowed = (".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tif", ".tiff")
                files = [f for f in files if f.lower().endswith(allowed)]

        return {
            "required": {
                "image": (sorted(files), {"image_upload": True}),
                "text_panel_enabled": (
                    "BOOLEAN",
                    {
                        "default": False,
                        "label_on": "开启：替换为文字面板",
                        "label_off": "关闭：删除选区并拼接",
                    },
                ),
                "selection_top_px": (
                    "INT",
                    {"default": 0, "min": 0, "max": MAX_RESOLUTION, "step": 1},
                ),
                "selection_bottom_px": (
                    "INT",
                    {"default": 1, "min": 1, "max": MAX_RESOLUTION, "step": 1},
                ),
                "panel_background": (["纯色", "透明"], {"default": "纯色"}),
                "background_color": (
                    "STRING",
                    {"default": "#FFFFFF", "multiline": False},
                ),
                "text": (
                    "STRING",
                    {"default": "在这里输入文字", "multiline": True},
                ),
                "text_color": (
                    "STRING",
                    {"default": "#000000", "multiline": False},
                ),
                "font_name_or_path": (
                    "STRING",
                    {
                        "default": "SimHei",
                        "multiline": False,
                        "tooltip": "默认简中黑体。也可填写字体文件完整路径。",
                    },
                ),
                "font_size": (
                    "INT",
                    {"default": 48, "min": 1, "max": 1024, "step": 1},
                ),
                "padding": (
                    "INT",
                    {"default": 24, "min": 0, "max": 2048, "step": 1},
                ),
                "line_spacing": (
                    "INT",
                    {"default": 8, "min": 0, "max": 1024, "step": 1},
                ),
                "horizontal_align": (["居中", "左对齐", "右对齐"], {"default": "居中"}),
                "vertical_align": (["居中", "顶部", "底部"], {"default": "居中"}),
            }
        }

    RETURN_TYPES = ("IMAGE", "MASK", "IMAGE", "INT", "INT")
    RETURN_NAMES = ("RGB_IMAGE", "TRANSPARENCY_MASK", "RGBA_IMAGE", "WIDTH", "HEIGHT")
    FUNCTION = "process"
    CATEGORY = "image/editing"
    DESCRIPTION = (
        "在节点预览里拖拽选择一个贯穿整张图片宽度的横向区域。"
        "可删除该区域并把上下两部分无缝拼接，也可把该区域替换成纯色/透明文字面板；"
        "文字超出选区高度时会自动扩展输出高度。"
    )

    @classmethod
    def VALIDATE_INPUTS(cls, image, **kwargs):
        if not folder_paths.exists_annotated_filepath(image):
            return f"找不到输入图像：{image}"
        return True

    @classmethod
    def IS_CHANGED(cls, image, **kwargs):
        path = folder_paths.get_annotated_filepath(image)
        h = hashlib.sha256()
        with open(path, "rb") as f:
            for block in iter(lambda: f.read(1024 * 1024), b""):
                h.update(block)
        # 其余 widget 值由 ComfyUI 自己参与缓存 key；这里负责图像文件内容变化。
        return h.hexdigest()

    def process(
        self,
        image,
        text_panel_enabled,
        selection_top_px,
        selection_bottom_px,
        panel_background,
        background_color,
        text,
        text_color,
        font_name_or_path,
        font_size,
        padding,
        line_spacing,
        horizontal_align,
        vertical_align,
    ):
        image_path = folder_paths.get_annotated_filepath(image)
        src = node_helpers.pillow(Image.open, image_path)
        src = node_helpers.pillow(ImageOps.exif_transpose, src).convert("RGBA")
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
                font_size=int(font_size),
                text_color=text_color,
                panel_background=panel_background,
                background_color=background_color,
                padding=int(padding),
                line_spacing=int(line_spacing),
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


NODE_CLASS_MAPPINGS = {
    "HorizontalBandEditor": HorizontalBandEditor,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "HorizontalBandEditor": "横向区域截断 / 文字面板编辑器",
}
