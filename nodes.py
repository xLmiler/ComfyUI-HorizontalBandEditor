import json
import os
import struct
import zlib
from types import SimpleNamespace
from pathlib import Path
from typing import List, Tuple
from xml.etree import ElementTree as ET

import numpy as np
import torch
from PIL import Image, ImageChops, ImageDraw, ImageFont, ImageOps, ImageSequence, PngImagePlugin

import folder_paths

try:
    from comfy.cli_args import args as comfy_cli_args
except Exception:
    comfy_cli_args = None

try:
    from comfy_api.latest._ui import ImageSaveHelper as ComfyNativeImageSaveHelper
except Exception:
    ComfyNativeImageSaveHelper = None

MAX_RESOLUTION = 16384
REGION_LABELS = tuple("ABCDEFGHIJKL")


def _kw(kwargs, names, default=None):
    for name in names:
        if name and name in kwargs:
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
    for path in candidates:
        if path not in seen:
            seen.add(path)
            out.append(path)
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



def _pil_frames_to_image_batch(frames: List[Image.Image]) -> torch.Tensor:
    if not frames:
        raise ValueError("没有可输出的图像帧。")
    tensors = []
    for frame in frames:
        rgba = np.asarray(frame.convert("RGBA"), dtype=np.float32) / 255.0
        tensors.append(torch.from_numpy(rgba[..., :3].copy()))
    return torch.stack(tensors, dim=0)


def _normalize_output_directory(custom_output_dir: str, default_output_dir: str) -> str:
    raw = str(custom_output_dir or "").strip().strip('\"').strip("'")
    if not raw:
        return default_output_dir

    expanded = os.path.expandvars(os.path.expanduser(raw))

    # 兼容 Windows 绝对路径与 UNC 路径。
    is_windows_abs = False
    if len(expanded) >= 3 and expanded[1] == ':' and expanded[2] in ('\\', '/') and expanded[0].isalpha():
        is_windows_abs = True
    if expanded.startswith('\\\\'):
        is_windows_abs = True

    if os.path.isabs(expanded) or is_windows_abs:
        return os.path.normpath(expanded)

    # 兼容用户手写的 Windows 相对路径分隔符，例如 subdir\nested。
    expanded = expanded.replace('\\', os.sep)
    return os.path.normpath(os.path.join(default_output_dir, expanded))
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



SUPPORTED_IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp"}


def _list_available_input_images():
    """与 ComfyUI 原生 LoadImage 一致：只枚举 input 根目录，避免递归扫描导致节点定义/工作流切换变慢。"""
    input_dir = folder_paths.get_input_directory()
    if not os.path.isdir(input_dir):
        return [""]
    files = [f for f in os.listdir(input_dir) if os.path.isfile(os.path.join(input_dir, f))]
    try:
        files = folder_paths.filter_files_content_types(files, ["image"])
    except Exception:
        files = [f for f in files if os.path.splitext(f)[1].lower() in SUPPORTED_IMAGE_EXTS]
    return sorted(files) or [""]

def _list_available_webp_images():
    """列出 input 根目录中的 PNG / WebP，供读取里图节点使用。"""
    input_dir = folder_paths.get_input_directory()
    if not os.path.isdir(input_dir):
        return [""]
    exts = {".webp", ".png"}
    files = [
        f for f in os.listdir(input_dir)
        if os.path.isfile(os.path.join(input_dir, f)) and os.path.splitext(f)[1].lower() in exts
    ]
    return sorted(files) or [""]


def _resolve_any_image_path(path_or_name: str):
    raw = str(path_or_name or "").strip().strip('"').strip("'")
    if not raw:
        return None
    expanded = os.path.expandvars(os.path.expanduser(raw))

    candidates = []
    try:
        if folder_paths.exists_annotated_filepath(expanded):
            resolved = folder_paths.get_annotated_filepath(expanded)
            if resolved:
                candidates.append(resolved)
    except Exception:
        pass

    candidates.append(expanded)
    candidates.append(os.path.join(folder_paths.get_input_directory(), expanded))
    try:
        candidates.append(os.path.join(folder_paths.get_output_directory(), expanded))
    except Exception:
        pass

    seen = set()
    for candidate in candidates:
        if not candidate:
            continue
        normalized = os.path.normpath(candidate)
        if normalized in seen:
            continue
        seen.add(normalized)
        if os.path.exists(normalized):
            return normalized
    return None


def _load_image_tensors_with_comfy_native(image_name: str):
    """优先直接复用 ComfyUI 原生 LoadImage，避免本插件重复解码动画并复制整批 Tensor。"""
    try:
        import nodes as comfy_core_nodes
        loader_cls = getattr(comfy_core_nodes, "LoadImage", None)
        if loader_cls is not None:
            return loader_cls().load_image(image_name)
    except Exception:
        pass

    # 仅用于非常旧或特殊环境的兼容回退。
    resolved, frames, _ = _load_image_frames_from_path(image_name)
    return _pil_frames_to_image_mask_batch(frames)


def _path_to_ui_image_descriptor(path: str):
    if not path:
        return None
    path = os.path.normpath(path)
    locations = []
    try:
        locations.append((os.path.normpath(folder_paths.get_input_directory()), "input"))
    except Exception:
        pass
    try:
        locations.append((os.path.normpath(folder_paths.get_output_directory()), "output"))
    except Exception:
        pass
    try:
        temp_dir = folder_paths.get_temp_directory()
        locations.append((os.path.normpath(temp_dir), "temp"))
    except Exception:
        pass

    for base, kind in locations:
        try:
            rel = os.path.relpath(path, base)
        except Exception:
            continue
        if rel.startswith(".."):
            continue
        subfolder = os.path.dirname(rel).replace("\\", "/")
        return {
            "filename": os.path.basename(path),
            "subfolder": "" if subfolder == "." else subfolder,
            "type": kind,
        }
    return None


def _pil_frames_to_image_mask_batch(frames: List[Image.Image]):
    if not frames:
        raise ValueError("没有可输出的图像帧。")
    image_tensors = []
    mask_tensors = []
    for frame in frames:
        rgba = np.asarray(frame.convert("RGBA"), dtype=np.float32) / 255.0
        image_tensors.append(torch.from_numpy(rgba[..., :3].copy()))
        mask_tensors.append(torch.from_numpy((1.0 - rgba[..., 3]).copy()))
    return torch.stack(image_tensors, dim=0), torch.stack(mask_tensors, dim=0)


def _make_json_safe(value):
    if isinstance(value, dict):
        return {str(k): _make_json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_make_json_safe(v) for v in value]
    if isinstance(value, (bytes, bytearray)):
        try:
            return value.decode("utf-8", errors="ignore")
        except Exception:
            return repr(value)
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def _parse_json_text(value, fallback=None):
    if value is None:
        return fallback
    if isinstance(value, (dict, list)):
        return value
    if isinstance(value, (bytes, bytearray)):
        try:
            value = value.decode("utf-8", errors="ignore")
        except Exception:
            return fallback
    text = str(value).strip()
    if not text:
        return fallback
    try:
        return json.loads(text)
    except Exception:
        return fallback


def _coerce_metadata_value(value):
    if isinstance(value, (dict, list, int, float, bool)) or value is None:
        return _make_json_safe(value)
    if isinstance(value, (bytes, bytearray)):
        value = value.decode("utf-8", errors="ignore")
    text = str(value)
    stripped = text.strip()
    if (stripped.startswith("{") and stripped.endswith("}")) or (stripped.startswith("[") and stripped.endswith("]")):
        parsed = _parse_json_text(stripped, None)
        if parsed is not None:
            return _make_json_safe(parsed)
    return text


def _store_metadata_value(target: dict, key: str, value):
    if value is None:
        return
    target[str(key)] = _coerce_metadata_value(value)


def _metadata_to_strings(metadata: dict):
    metadata = _make_json_safe(metadata or {})
    prompt = metadata.get("prompt", "")
    workflow = metadata.get("workflow", "")

    def value_to_text(value):
        if isinstance(value, str):
            return value
        try:
            return json.dumps(value, ensure_ascii=False, separators=(",", ":"))
        except Exception:
            return str(value)

    try:
        all_json = json.dumps(metadata, ensure_ascii=False, separators=(",", ":"))
    except Exception:
        all_json = "{}"
    return value_to_text(prompt), value_to_text(workflow), all_json


def _split_comfy_exif_text(value):
    """解析 ComfyUI 原生 WebP EXIF 中的 `key:<json>` ASCII 文本。"""
    if not isinstance(value, str) or ":" not in value:
        return None, None
    key, payload = value.split(":", 1)
    key = key.strip()
    if not key:
        return None, None
    parsed = _parse_json_text(payload, None)
    return key, parsed if parsed is not None else payload


def _extract_metadata_from_open_image(img: Image.Image, path: str):
    """
    读取图片文件里实际保存的元数据。

    目标是与 ComfyUI 原生保存节点的数据语义一致：
    - PNG: prompt + EXTRA_PNGINFO 各 key 的 PNG text chunk
    - WebP: EXIF ASCII `key:<json>`，与原生 Save Animated WEBP 相同
    - GIF: Comment Extension 中的 JSON（ComfyUI 原生目前没有对应 GIF workflow saver，
      这里作为插件扩展兼容）
    """
    ext = os.path.splitext(path or "")[1].lower()
    fmt = str(getattr(img, "format", "") or "").upper()
    info = dict(getattr(img, "info", {}) or {})
    metadata = {}

    if ext == ".gif" or fmt == "GIF":
        comment = info.get("comment")
        parsed_comment = _parse_json_text(comment, None)
        if isinstance(parsed_comment, dict):
            for key, value in parsed_comment.items():
                _store_metadata_value(metadata, key, value)
        elif comment:
            _store_metadata_value(metadata, "comment", comment)
        for key in ("loop", "background", "transparency"):
            if key in info:
                _store_metadata_value(metadata, key, info[key])
        return metadata

    if ext == ".webp" or fmt == "WEBP":
        try:
            exif = img.getexif()
            for _, value in exif.items():
                key, parsed = _split_comfy_exif_text(value)
                if key:
                    _store_metadata_value(metadata, key, parsed)
        except Exception:
            pass
        return metadata

    # PNG 以及其他静态图片：Pillow 会把 PNG 文本块放在 info 中。
    # ComfyUI 原生 SaveImage 保存的是 prompt 与 EXTRA_PNGINFO 每个 key 的 json.dumps(value)。
    for key, value in info.items():
        if key in {"exif", "xmp", "icc_profile"}:
            continue
        _store_metadata_value(metadata, key, value)
    return metadata


def _read_source_media_info(path_or_name: str):
    resolved = _resolve_any_image_path(path_or_name)
    result = {
        "resolved": resolved,
        "ext": os.path.splitext(resolved or str(path_or_name or ""))[1].lower(),
        "is_gif": False,
        "gif_durations_ms": [],
        "gif_loop": 0,
    }
    if not resolved:
        return result

    try:
        with Image.open(resolved) as img:
            ext = os.path.splitext(resolved)[1].lower()
            is_gif = ext == ".gif" or getattr(img, "format", "") == "GIF"
            result["is_gif"] = bool(is_gif)
            if is_gif:
                result["gif_loop"] = int(img.info.get("loop", 0) or 0)
                durations = []
                frame_count = int(getattr(img, "n_frames", 1) or 1)
                for i in range(frame_count):
                    try:
                        img.seek(i)
                    except EOFError:
                        break
                    duration = int(img.info.get("duration", 0) or 0)
                    durations.append(duration if duration > 0 else 100)
                result["gif_durations_ms"] = durations
    except Exception:
        pass
    return result


def _extract_metadata_from_image(path: str):
    resolved = _resolve_any_image_path(path)
    if not resolved:
        return {}
    try:
        with Image.open(resolved) as img:
            metadata = _extract_metadata_from_open_image(img, resolved)
        # APNG 的文本元数据可能被放在动画数据之后。Pillow 初次 open 时不一定已经
        # 扫描到尾部，因此额外从原始 PNG chunk 中读取并合并，保证 hbe/workflow 可用。
        if os.path.splitext(resolved)[1].lower() == ".png":
            for key, value in _parse_png_text_chunks_raw(resolved).items():
                _store_metadata_value(metadata, key, value)
        return metadata
    except Exception:
        return {}


def _load_image_frames_from_path(path: str):
    resolved = _resolve_any_image_path(path)
    if not resolved:
        raise FileNotFoundError(f"找不到图片文件：{path}")

    frames = []
    with Image.open(resolved) as img:
        metadata = _extract_metadata_from_open_image(img, resolved)
        ext = os.path.splitext(resolved)[1].lower()
        is_gif = ext == ".gif" or getattr(img, "format", "") == "GIF"
        gif_durations = []
        gif_loop = int(img.info.get("loop", 0) or 0) if is_gif else 0

        frame_count = int(getattr(img, "n_frames", 1) or 1)
        for i in range(frame_count):
            try:
                img.seek(i)
            except EOFError:
                break
            frame = img.convert("RGBA")
            frame.load()
            frames.append(frame.copy())
            if is_gif:
                duration = int(img.info.get("duration", 0) or 0)
                gif_durations.append(duration if duration > 0 else 100)

        if is_gif:
            metadata["_gif_durations_ms"] = gif_durations
            metadata["_gif_loop"] = gif_loop

    if not frames:
        raise RuntimeError("未能从图片中读取到任何帧。")
    return resolved, frames, metadata


def _resolve_input_image_path(source_image_filename: str):
    if not source_image_filename:
        return None
    try:
        if folder_paths.exists_annotated_filepath(source_image_filename):
            return folder_paths.get_annotated_filepath(source_image_filename)
    except Exception:
        pass
    candidate = os.path.join(folder_paths.get_input_directory(), source_image_filename)
    return candidate if os.path.exists(candidate) else None


def _extract_source_workflow_metadata(source_image_filename: str):
    path = _resolve_input_image_path(source_image_filename) or _resolve_any_image_path(source_image_filename)
    if not path:
        return {}
    return _extract_metadata_from_image(path)


def _tensor_to_pil_frames(image_tensor) -> List[Image.Image]:
    if image_tensor is None:
        return []
    if not isinstance(image_tensor, torch.Tensor):
        image_tensor = torch.as_tensor(image_tensor)
    tensor = image_tensor.detach().cpu().float()
    if tensor.ndim == 3:
        tensor = tensor.unsqueeze(0)
    if tensor.ndim != 4:
        raise ValueError(f"输入图像维度不正确：{tuple(image_tensor.shape)}")

    frames: List[Image.Image] = []
    for frame in tensor:
        frame = frame.clamp(0.0, 1.0)
        arr = (frame.numpy() * 255.0).round().astype(np.uint8)
        if arr.shape[-1] < 3:
            raise ValueError("输入图像至少需要 RGB 三个通道。")
        if arr.shape[-1] >= 4:
            rgba = arr[..., :4]
            if rgba.shape[-1] == 4:
                img = Image.fromarray(rgba, mode="RGBA")
            else:
                img = Image.fromarray(rgba[..., :3], mode="RGB").convert("RGBA")
        else:
            alpha = np.full(arr.shape[:2] + (1,), 255, dtype=np.uint8)
            img = Image.fromarray(np.concatenate([arr[..., :3], alpha], axis=-1), mode="RGBA")
        frames.append(img)
    return frames


def _fit_to_canvas(img: Image.Image, size: Tuple[int, int]) -> Image.Image:
    rgba = img.convert("RGBA")
    if rgba.size == size:
        return rgba.copy()
    fitted = ImageOps.contain(rgba, size, method=Image.Resampling.LANCZOS)
    canvas = Image.new("RGBA", size, (0, 0, 0, 0))
    x = (size[0] - fitted.width) // 2
    y = (size[1] - fitted.height) // 2
    canvas.alpha_composite(fitted, (x, y))
    return canvas


def _crop_to_canvas(img: Image.Image, size: Tuple[int, int]) -> Image.Image:
    rgba = img.convert("RGBA")
    if rgba.size == size:
        return rgba.copy()
    return ImageOps.fit(
        rgba,
        size,
        method=Image.Resampling.LANCZOS,
        centering=(0.5, 0.5),
    )


def _make_distinct_duplicate_frame(img: Image.Image, step: int = 1) -> Image.Image:
    dup = img.convert("RGBA").copy()
    x = max(0, dup.width - 1)
    y = max(0, dup.height - 1)
    r, g, b, a = dup.getpixel((x, y))
    if a > 0:
        dup.putpixel((x, y), (r, g, b, max(0, a - min(step, 254))))
    else:
        dup.putpixel((x, y), ((r + step) % 256, g, b, 0))
    return dup


def _prepare_cover_inner_webp_frames(
    cover_image: Image.Image | None,
    inner_frames: List[Image.Image],
    cover_frame_count: int,
    placeholder_color: str,
):
    if not inner_frames:
        raise ValueError("里图不能为空，至少需要连接 1 帧图像。")

    target_size = inner_frames[0].size
    if cover_image is None:
        rgba = _parse_hex_color(placeholder_color, (255, 255, 255, 255))
        cover = Image.new("RGBA", target_size, rgba)
    else:
        cover = _crop_to_canvas(cover_image, target_size)

    frames: List[Image.Image] = []
    cover_frame_count = max(1, int(cover_frame_count))
    for i in range(cover_frame_count):
        frames.append(cover.copy() if i == 0 else _make_distinct_duplicate_frame(cover, i))

    normalized_inner: List[Image.Image] = []
    for frame in inner_frames:
        if frame.size == target_size:
            normalized_inner.append(frame.convert("RGBA"))
        else:
            normalized_inner.append(_fit_to_canvas(frame, target_size))

    frames.extend(normalized_inner)

    # 表图是真正的首帧封面，而不是依靠长时间 duration 伪装静态。
    # 静态缩略图若只读取第 1 帧，就会一直显示表图；真正播放动画时才进入里图。
    durations = [1] * cover_frame_count
    if len(normalized_inner) == 1:
        durations.append(600_000)
    else:
        durations.extend([100] * len(normalized_inner))

    return frames, durations, target_size


def _resolve_inner_frame_durations(frame_count: int, media_info: dict, inherit_gif_timing: bool,
                                   custom_frame_duration_ms: int, playback_speed: float):
    frame_count = max(1, int(frame_count))
    speed = max(0.05, float(playback_speed or 1.0))
    custom_ms = max(1, int(custom_frame_duration_ms or 100))

    source_durations = []
    if inherit_gif_timing and bool((media_info or {}).get("is_gif")):
        raw = (media_info or {}).get("gif_durations_ms", []) or []
        if len(raw) >= frame_count:
            source_durations = [max(1, int(v or custom_ms)) for v in raw[:frame_count]]

    if not source_durations:
        source_durations = [custom_ms] * frame_count

    # 倍速 > 1 表示更快，因此每帧持续时间缩短；倍速 < 1 表示更慢。
    return [max(1, int(round(ms / speed))) for ms in source_durations]


def _subsample_animation_frames(frames: List[Image.Image], durations: List[int], step: int):
    """
    每 step 帧保留 1 帧，并把被跳过帧的时长累加到保留帧。
    这样能显著降低动画 WebP 的帧数/文件体积，同时大致保持总播放时长。
    """
    step = max(1, int(step or 1))
    if step <= 1 or len(frames) <= 1:
        return list(frames), list(durations)

    out_frames = []
    out_durations = []
    for start in range(0, len(frames), step):
        end = min(len(frames), start + step)
        out_frames.append(frames[start])
        out_durations.append(max(1, int(sum(durations[start:end]))))
    return out_frames, out_durations


def _repeat_animation_to_minimum(frames: List[Image.Image], durations: List[int], min_frames: int):
    """
    对极少帧动画进行循环补帧，确保导出的动画至少达到最小帧数。
    这样可以显著提高某些聊天软件把 WebP 识别为“可点击查看原图的动画里图”
    而不是直接在聊天流里瞬间播放完毕的概率。
    """
    if not frames or not durations:
        return list(frames), list(durations)
    min_frames = max(1, int(min_frames or 1))
    if len(frames) >= min_frames:
        return list(frames), list(durations)

    out_frames = []
    out_durations = []
    i = 0
    while len(out_frames) < min_frames:
        src_idx = i % len(frames)
        out_frames.append(frames[src_idx].copy())
        out_durations.append(int(durations[src_idx]))
        i += 1
    return out_frames, out_durations


def _native_json_dumps(value):
    """与 ComfyUI 原生 SaveImage / SaveAnimatedWEBP 一样直接 json.dumps。"""
    return json.dumps(_make_json_safe(value))


def _clean_metadata_for_embedding(metadata: dict):
    metadata = _make_json_safe(metadata or {})
    cleaned = {}
    for key, value in metadata.items():
        key = str(key)
        if key == "hbe" or key.startswith("hbe_"):
            continue
        if key in {"_gif_durations_ms", "_gif_loop"}:
            continue
        # Pillow 会把 APNG 运行时状态放进 image.info；这些不是 ComfyUI 工作流元数据，
        # 继承源图时不应被再次写成 tEXt。
        if key in {"loop", "default_image", "duration", "disposal", "blend", "background", "transparency"}:
            continue
        cleaned[key] = value
    return cleaned


def _current_workflow_metadata(prompt=None, extra_pnginfo=None):
    """构造与 ComfyUI 原生保存节点 hidden PROMPT / EXTRA_PNGINFO 相同的数据集合。"""
    metadata = {}
    if prompt is not None:
        metadata["prompt"] = _make_json_safe(prompt)
    if isinstance(extra_pnginfo, dict):
        for key, value in extra_pnginfo.items():
            metadata[str(key)] = _make_json_safe(value)
    return metadata


def _metadata_to_native_prompt_and_extra(metadata: dict, marker: dict | None = None):
    """
    将“图片内置元数据”转换为 ComfyUI 原生保存节点的数据模型：
    prompt 单独保存，其余所有 key 都视为 EXTRA_PNGINFO。
    """
    metadata = _clean_metadata_for_embedding(metadata)
    prompt = metadata.get("prompt", None)
    extra = {k: v for k, v in metadata.items() if k != "prompt"}
    if marker is not None:
        extra["hbe"] = _make_json_safe(marker)
    return prompt, extra


def _build_native_comfy_webp_exif(pil_image: Image.Image, prompt=None, extra_pnginfo=None):
    """
    优先直接调用当前 ComfyUI 自带 ImageSaveHelper._create_webp_metadata。
    这样 prompt / EXTRA_PNGINFO 的 EXIF tag 与序列化行为和原生 Save Animated WEBP 完全一致。
    仅在旧版 ComfyUI 不存在该 helper 时使用兼容回退。
    """
    if ComfyNativeImageSaveHelper is not None:
        try:
            carrier = SimpleNamespace(hidden=SimpleNamespace(prompt=prompt, extra_pnginfo=extra_pnginfo))
            return ComfyNativeImageSaveHelper._create_webp_metadata(pil_image, carrier)
        except Exception:
            pass

    exif_data = pil_image.getexif()
    if comfy_cli_args is not None and bool(getattr(comfy_cli_args, "disable_metadata", False)):
        return exif_data
    if prompt is not None:
        exif_data[0x0110] = "prompt:{}".format(_native_json_dumps(prompt))
    if extra_pnginfo is not None:
        initial_exif_tag = 0x010F
        for key, value in extra_pnginfo.items():
            exif_data[initial_exif_tag] = "{}:{}".format(key, _native_json_dumps(value))
            initial_exif_tag -= 1
    return exif_data


def _build_native_pnginfo_from_metadata(metadata: dict):
    """优先复用 ComfyUI 原生 PNG metadata helper；旧版环境再回退到等价实现。"""
    if comfy_cli_args is not None and bool(getattr(comfy_cli_args, "disable_metadata", False)):
        return None
    metadata = _clean_metadata_for_embedding(metadata)
    prompt = metadata.get("prompt", None)
    extras = {k: v for k, v in metadata.items() if k != "prompt"}

    if ComfyNativeImageSaveHelper is not None:
        try:
            carrier = SimpleNamespace(hidden=SimpleNamespace(prompt=prompt, extra_pnginfo=extras))
            return ComfyNativeImageSaveHelper._create_png_metadata(carrier)
        except Exception:
            pass

    pnginfo = PngImagePlugin.PngInfo()
    if prompt is not None:
        pnginfo.add_text("prompt", _native_json_dumps(prompt))
    for key, value in extras.items():
        pnginfo.add_text(str(key), _native_json_dumps(value))
    return pnginfo


def _build_native_pnginfo_from_prompt_extra(prompt=None, extra_pnginfo=None):
    """
    直接按 ComfyUI 原生 SaveImage 的 prompt / EXTRA_PNGINFO 语义构建 PNG metadata。

    与 _build_native_pnginfo_from_metadata() 不同，这里不会清理 hbe / hbe_* 字段，
    因为 HBE marker 本身就是读取表里图所必需的结构元数据。
    """
    if comfy_cli_args is not None and bool(getattr(comfy_cli_args, "disable_metadata", False)):
        return None

    if ComfyNativeImageSaveHelper is not None:
        try:
            carrier = SimpleNamespace(hidden=SimpleNamespace(prompt=prompt, extra_pnginfo=extra_pnginfo))
            return ComfyNativeImageSaveHelper._create_png_metadata(carrier)
        except Exception:
            pass

    pnginfo = PngImagePlugin.PngInfo()
    if prompt is not None:
        pnginfo.add_text("prompt", _native_json_dumps(prompt))
    if isinstance(extra_pnginfo, dict):
        for key, value in extra_pnginfo.items():
            pnginfo.add_text(str(key), _native_json_dumps(value))
    return pnginfo


def _build_webp_metadata_payload(metadata_source: str, source_image_filename: str,
                                 cover_frame_count: int, inner_frame_count: int,
                                 prompt=None, extra_pnginfo=None,
                                 media_type_override: str | None = None,
                                 source_ext_override: str | None = None):
    media_info = _read_source_media_info(source_image_filename)
    source_ext = source_ext_override or media_info.get("ext") or ".png"
    inferred_is_gif = bool(media_info.get("is_gif"))
    media_type = str(media_type_override or ("gif" if inferred_is_gif else "image"))
    is_gif = media_type == "gif"

    if metadata_source == "当前工作流元数据":
        selected_metadata = _current_workflow_metadata(prompt, extra_pnginfo)
        source_key = "current_workflow"
    elif metadata_source == "不保存元数据":
        selected_metadata = {}
        source_key = "none"
    else:
        selected_metadata = _extract_metadata_from_image(source_image_filename) if source_image_filename else {}
        source_key = "image_embedded"

    selected_metadata = _clean_metadata_for_embedding(selected_metadata)

    marker = {
        "hbe_cover_inner_webp": True,
        "hbe_marker_version": 3,
        "hbe_inner_start_index": int(max(0, cover_frame_count)),
        "hbe_inner_start_frame": int(max(1, cover_frame_count + 1)),
        "hbe_inner_frame_count": int(max(0, inner_frame_count)),
        "hbe_inner_media_type": media_type,
        "hbe_inner_source_ext": source_ext or (".gif" if is_gif else ".png"),
        "hbe_inner_source_is_gif": bool(is_gif),
        "hbe_metadata_source": source_key,
    }
    if is_gif:
        marker["hbe_inner_gif_durations_ms"] = media_info.get("gif_durations_ms", [])
        marker["hbe_inner_gif_loop"] = int(media_info.get("gif_loop", 0) or 0)

    native_prompt, native_extra = _metadata_to_native_prompt_and_extra(selected_metadata, marker=marker)
    return selected_metadata, marker, native_prompt, native_extra


def _read_comfy_webp_metadata_native_compatible(path: str):
    """
    按 ComfyUI frontend 当前 getWebpMetadata() 的实际规则读取 WebP EXIF：
    - 遍历 RIFF chunk
    - 找到 EXIF
    - 解析第一层 TIFF IFD
    - 只读取 type=2 (ASCII)
    - 每条字符串按第一个 ':' 拆成 key/value

    这个函数用于保存后自检，确保生成的 WebP 真的能被 ComfyUI 前端识别，
    而不是只保证 Pillow 自己能读回来。
    """
    result = {}
    try:
        with open(path, "rb") as f:
            webp = f.read()
        if len(webp) < 12 or webp[0:4] != b"RIFF" or webp[8:12] != b"WEBP":
            return result

        offset = 12
        exif_data = None
        while offset + 8 <= len(webp):
            chunk_type = webp[offset:offset + 4]
            chunk_length = struct.unpack_from("<I", webp, offset + 4)[0]
            data_start = offset + 8
            data_end = data_start + chunk_length
            if data_end > len(webp):
                break
            if chunk_type == b"EXIF":
                exif_data = webp[data_start:data_end]
                break
            offset = data_end + (chunk_length % 2)

        if not exif_data:
            return result
        if exif_data.startswith(b"Exif\x00\x00"):
            exif_data = exif_data[6:]
        if len(exif_data) < 8:
            return result

        byte_order = exif_data[0:2]
        if byte_order == b"II":
            endian = "<"
        elif byte_order == b"MM":
            endian = ">"
        else:
            return result

        def u16(pos):
            if pos < 0 or pos + 2 > len(exif_data):
                raise ValueError("EXIF u16 越界")
            return struct.unpack_from(endian + "H", exif_data, pos)[0]

        def u32(pos):
            if pos < 0 or pos + 4 > len(exif_data):
                raise ValueError("EXIF u32 越界")
            return struct.unpack_from(endian + "I", exif_data, pos)[0]

        ifd_offset = u32(4)
        entry_count = u16(ifd_offset)
        for i in range(entry_count):
            entry_offset = ifd_offset + 2 + i * 12
            if entry_offset + 12 > len(exif_data):
                break
            value_type = u16(entry_offset + 2)
            num_values = u32(entry_offset + 4)
            value_offset = u32(entry_offset + 8)
            if value_type != 2 or num_values <= 1:
                continue
            # 与 ComfyUI frontend 当前实现保持一致：ASCII 数据通过 valueOffset 读取。
            if value_offset < 0 or value_offset + num_values - 1 > len(exif_data):
                continue
            raw = exif_data[value_offset:value_offset + num_values - 1]
            try:
                value = raw.decode("utf-8")
            except UnicodeDecodeError:
                value = raw.decode("utf-8", errors="ignore")
            index = value.find(":")
            if index <= 0:
                continue
            result[value[:index]] = value[index + 1:]
    except Exception:
        return {}
    return result


def _verify_comfy_webp_drag_metadata(path: str):
    """
    仅做非阻断诊断：按 ComfyUI 前端规则读取保存后的 WebP 元数据。
    不再因为 Python 侧对象比较差异而让图片保存失败。
    """
    return _read_comfy_webp_metadata_native_compatible(path)


def _extract_cover_inner_info(metadata: dict):
    metadata = metadata or {}
    marker = metadata.get("hbe", {})
    if isinstance(marker, str):
        marker = _parse_json_text(marker, {}) or {}
    if not isinstance(marker, dict):
        marker = {}

    # Backward compatibility: old versions stored hbe_* keys at the root.
    for key, value in metadata.items():
        if str(key).startswith("hbe_") and key not in marker:
            marker[key] = value

    has_marker = bool(marker.get("hbe_cover_inner_webp", False)) or ("hbe_inner_start_index" in marker) or ("hbe_inner_start_frame" in marker)
    try:
        start_index = int(marker.get("hbe_inner_start_index", max(0, int(marker.get("hbe_inner_start_frame", 1)) - 1)))
    except Exception:
        start_index = 0
    try:
        start_frame = int(marker.get("hbe_inner_start_frame", start_index + 1))
    except Exception:
        start_frame = start_index + 1
    try:
        inner_frame_count = int(marker.get("hbe_inner_frame_count", 0))
    except Exception:
        inner_frame_count = 0

    media_type = str(marker.get("hbe_inner_media_type", "gif" if marker.get("hbe_inner_source_is_gif") else "image") or "image")
    source_ext = str(marker.get("hbe_inner_source_ext", ".gif" if media_type == "gif" else ".png") or ".png")

    # v1.10 compatibility: old payload duplicated source metadata inside marker.
    old_inner_meta = marker.get("hbe_inner_metadata", metadata.get("hbe_inner_metadata", {}))
    if isinstance(old_inner_meta, str):
        old_inner_meta = _parse_json_text(old_inner_meta, {}) or {}

    if isinstance(old_inner_meta, dict) and old_inner_meta:
        inner_meta = _make_json_safe(old_inner_meta)
    else:
        # New format: prompt/workflow/extras live at WEBP root; marker only describes frame layout.
        inner_meta = {}
        for key, value in metadata.items():
            key = str(key)
            if key == "hbe" or key.startswith("hbe_"):
                continue
            inner_meta[key] = _make_json_safe(value)

    if media_type == "gif":
        durations = marker.get("hbe_inner_gif_durations_ms", [])
        if isinstance(durations, list):
            inner_meta["_gif_durations_ms"] = [int(v) for v in durations if isinstance(v, (int, float)) or str(v).isdigit()]
        try:
            inner_meta["_gif_loop"] = int(marker.get("hbe_inner_gif_loop", 0) or 0)
        except Exception:
            inner_meta["_gif_loop"] = 0

    return {
        "has_marker": has_marker,
        "start_index": max(0, start_index),
        "start_frame": max(1, start_frame),
        "inner_frame_count": max(0, inner_frame_count),
        "media_type": media_type,
        "source_ext": source_ext,
        "metadata_source": str(marker.get("hbe_metadata_source", "unknown")),
        "inner_metadata": inner_meta,
        "marker": marker,
    }


def _pad_webp_riff_to_min_size(path: str, min_size_bytes: int) -> int:
    """
    在 WebP RIFF 容器末尾追加一个未知但合法的自定义 chunk（HBEF）作为兼容填充。

    WebP/RIFF 解码器应忽略未知 chunk，因此不会增加可见动画帧、不会改变 duration/loop，
    也不需要为了凑文件体积重复执行 libwebp 编码。该填充只用于更稳定地跨过部分
    聊天软件在“直接动画预览”和“压缩缩略图 + 查看原图”之间的文件体积判定阈值。

    返回最终文件字节数。
    """
    min_size_bytes = max(0, int(min_size_bytes or 0))
    if min_size_bytes <= 0:
        return os.path.getsize(path)

    with open(path, "rb") as f:
        data = bytearray(f.read())

    if len(data) < 12 or data[0:4] != b"RIFF" or data[8:12] != b"WEBP":
        raise RuntimeError("兼容填充失败：输出文件不是有效的 RIFF/WebP 容器。")

    if len(data) >= min_size_bytes:
        return len(data)

    # RIFF chunk = FourCC(4) + size(4) + payload + 可选偶数字节对齐。
    payload_size = max(0, min_size_bytes - len(data) - 8)
    # 使用确定性的 0 填充；若 payload 为奇数，RIFF 需要额外 1 个对齐字节。
    chunk = bytearray(b"HBEF")
    chunk.extend(int(payload_size).to_bytes(4, "little", signed=False))
    chunk.extend(b"\x00" * payload_size)
    if payload_size % 2:
        chunk.append(0)

    data.extend(chunk)
    # RIFF size 字段不包含最前面的 'RIFF' + size 共 8 字节。
    riff_size = len(data) - 8
    if riff_size >= 2**32:
        raise RuntimeError("兼容填充失败：WebP RIFF 容器超过 4 GiB。")
    data[4:8] = int(riff_size).to_bytes(4, "little", signed=False)

    with open(path, "wb") as f:
        f.write(data)
    return len(data)




def _pad_png_to_min_size(path: str, min_size_bytes: int) -> int:
    """
    使用标准 PNG tEXt chunk 将 PNG/APNG 补到指定最小体积。

    旧实现使用私有 hbEf ancillary chunk。实际测试发现部分聊天软件在决定
    “直接显示动画/里图”还是“缩略表图 + 点击查看原图”时，会忽略未知私有 chunk，
    因而文件物理大小虽然达到阈值，客户端看到的有效 PNG 体积仍然不足。

    新实现写入未压缩标准 tEXt，并插入到 acTL（或首个 IDAT）之前。这样填充
    会作为标准 PNG 元数据参与目标客户端的 PNG 解析，同时不改变任何像素、APNG
    帧、duration、loop 或 default_image。关键字以 hbe_ 开头，重新继承元数据时会
    被 _clean_metadata_for_embedding() 自动过滤，不会递归膨胀。
    """
    min_size_bytes = max(0, int(min_size_bytes or 0))
    if min_size_bytes <= 0:
        return os.path.getsize(path)

    data = Path(path).read_bytes()
    if len(data) < 12 or data[:8] != b'\x89PNG\r\n\x1a\n':
        raise RuntimeError('兼容填充失败：输出文件不是有效的 PNG/APNG。')

    if len(data) >= min_size_bytes:
        return len(data)

    # 优先放在 acTL 之前，使文件头与“带 prompt/workflow 的已验证可用 APNG”一致。
    # 普通 PNG 没有 acTL 时则放到第一个 IDAT 之前。
    pos = 8
    insert_pos = None
    while pos + 12 <= len(data):
        length = int.from_bytes(data[pos:pos+4], 'big', signed=False)
        ctype = data[pos+4:pos+8]
        next_pos = pos + 12 + length
        if next_pos > len(data):
            break
        if ctype in {b'acTL', b'IDAT', b'IEND'}:
            insert_pos = pos
            break
        pos = next_pos
    if insert_pos is None:
        raise RuntimeError('兼容填充失败：找不到 acTL / IDAT / IEND 插入位置。')

    keyword = b'hbe_transport_padding'
    fixed_overhead = 12 + len(keyword) + 1  # chunk framing + keyword + NUL
    deficit = max(0, min_size_bytes - len(data))
    text_len = max(1, deficit - fixed_overhead)
    payload = keyword + b'\x00' + (b'P' * text_len)

    ctype = b'tEXt'
    crc = zlib.crc32(ctype)
    crc = zlib.crc32(payload, crc) & 0xffffffff
    chunk = bytearray()
    chunk.extend(len(payload).to_bytes(4, 'big', signed=False))
    chunk.extend(ctype)
    chunk.extend(payload)
    chunk.extend(crc.to_bytes(4, 'big', signed=False))

    new_data = data[:insert_pos] + chunk + data[insert_pos:]
    Path(path).write_bytes(new_data)
    return len(new_data)



def _parse_png_text_chunks_raw(path: str) -> dict:
    """读取 PNG/APNG 任意位置的 tEXt / zTXt / iTXt 文本元数据。"""
    result = {}
    try:
        data = Path(path).read_bytes()
    except Exception:
        return result
    if len(data) < 8 or data[:8] != b'\x89PNG\r\n\x1a\n':
        return result

    pos = 8
    while pos + 12 <= len(data):
        length = int.from_bytes(data[pos:pos+4], 'big', signed=False)
        ctype = data[pos+4:pos+8]
        start = pos + 8
        end = start + length
        if end + 4 > len(data):
            break
        payload = data[start:end]
        try:
            if ctype == b'tEXt':
                sep = payload.find(b'\x00')
                if sep > 0:
                    key = payload[:sep].decode('latin-1', errors='replace')
                    value = payload[sep+1:].decode('latin-1', errors='replace')
                    result[key] = value
            elif ctype == b'zTXt':
                sep = payload.find(b'\x00')
                if sep > 0 and sep + 2 <= len(payload):
                    key = payload[:sep].decode('latin-1', errors='replace')
                    method = payload[sep+1]
                    if method == 0:
                        value = zlib.decompress(payload[sep+2:]).decode('latin-1', errors='replace')
                        result[key] = value
            elif ctype == b'iTXt':
                sep = payload.find(b'\x00')
                if sep > 0 and sep + 3 <= len(payload):
                    key = payload[:sep].decode('latin-1', errors='replace')
                    compression_flag = payload[sep+1]
                    compression_method = payload[sep+2]
                    cursor = sep + 3
                    lang_end = payload.find(b'\x00', cursor)
                    if lang_end < 0:
                        raise ValueError('invalid iTXt language field')
                    cursor = lang_end + 1
                    translated_end = payload.find(b'\x00', cursor)
                    if translated_end < 0:
                        raise ValueError('invalid iTXt translated keyword field')
                    cursor = translated_end + 1
                    text_bytes = payload[cursor:]
                    if compression_flag == 1:
                        if compression_method != 0:
                            raise ValueError('unsupported iTXt compression method')
                        text_bytes = zlib.decompress(text_bytes)
                    result[key] = text_bytes.decode('utf-8', errors='replace')
        except Exception:
            pass
        pos = end + 4
        if ctype == b'IEND':
            break
    return result


def _build_ui_preview_image_result(preview_image: Image.Image, preview_prefix: str = "ComfyUI_hbe_preview") -> dict:
    """
    始终在 ComfyUI 默认 output 目录下额外写入一个小型 PNG 预览图，
    避免当最终文件保存到自定义外部目录时，前端 /view 无法读取造成 Nodes 2.0
    与经典 UI 预览加载失败。
    """
    preview_root = folder_paths.get_output_directory()
    width, height = preview_image.size
    full_output_folder, filename, counter, subfolder, _prefix = folder_paths.get_save_image_path(
        preview_prefix, preview_root, width, height
    )
    os.makedirs(full_output_folder, exist_ok=True)
    file = f"{filename}_{counter:05}_.png"
    out_path = os.path.join(full_output_folder, file)
    preview_image.convert("RGBA").save(out_path, format="PNG", optimize=False)
    return {
        "filename": file,
        "subfolder": subfolder,
        "type": "output",
        "preview_path": out_path,
    }

def _save_frames_as_apng(default_image: Image.Image, frames: List[Image.Image], durations: List[int], out_path: str,
                         pnginfo=None, loop_count: int = 0):
    if not frames:
        raise RuntimeError('至少需要 1 帧里图才能保存为 APNG。')
    if len(frames) != len(durations):
        raise RuntimeError(f'APNG 帧数与时长数量不一致：{len(frames)} / {len(durations)}')

    base_size = default_image.size
    cover = default_image.convert('RGBA')
    normalized = []
    for idx, frame in enumerate(frames):
        rgba = frame.convert('RGBA')
        if rgba.size != base_size:
            raise RuntimeError(f'APNG 第 {idx + 1} 帧尺寸不一致：{rgba.size}，预期 {base_size}')
        if normalized and ImageChops.difference(normalized[-1], rgba).getbbox() is None:
            rgba = _make_distinct_duplicate_frame(rgba, (idx % 253) + 1)
        normalized.append(rgba)

    save_kwargs = {
        'format': 'PNG',
        'save_all': True,
        'append_images': normalized,
        'duration': durations,
        'loop': max(0, int(loop_count)),
        'default_image': True,
        'optimize': False,
    }
    if pnginfo is not None:
        save_kwargs['pnginfo'] = pnginfo
    cover.save(out_path, **save_kwargs)

def _save_frames_as_webp(frames: List[Image.Image], durations: List[int], out_path: str,
                         quality: int, lossless: bool, extra_save_kwargs=None, loop_count: int = 1,
                         preserve_duplicate_frames: bool = True, verify_saved: bool = True):
    if len(frames) < 2:
        raise RuntimeError("至少需要 2 帧才能保存为动画 WebP。")
    if len(frames) != len(durations):
        raise RuntimeError(f"帧数与时长数量不一致：{len(frames)} / {len(durations)}")

    base_size = frames[0].size
    normalized = []
    for idx, frame in enumerate(frames):
        rgba = frame.convert("RGBA")
        if rgba.size != base_size:
            raise RuntimeError(f"第 {idx + 1} 帧尺寸不一致：{rgba.size}，预期 {base_size}")

        # Pillow/libwebp 会合并完全相同的连续帧。
        # 这会破坏“表图连续帧数 / 里图起始帧 / GIF 每帧 duration”的严格对应关系，
        # 甚至让保存后的实际帧数少于 HBE marker 记录的帧数。
        # 延续 1.x 已验证逻辑：只对完全相同的相邻帧做几乎不可见的 1 像素差异，
        # 强制保留真实帧边界与时间轴。
        if preserve_duplicate_frames and normalized and ImageChops.difference(normalized[-1], rgba).getbbox() is None:
            rgba = _make_distinct_duplicate_frame(rgba, (idx % 253) + 1)
        normalized.append(rgba)

    save_kwargs = {
        "format": "WEBP",
        "save_all": True,
        "append_images": normalized[1:],
        "duration": durations,
        "loop": max(0, min(65535, int(loop_count))),
        "lossless": bool(lossless),
        "method": 6,
        "exact": True,
    }
    if not lossless:
        save_kwargs["quality"] = int(quality)
    if extra_save_kwargs:
        save_kwargs.update(extra_save_kwargs)

    normalized[0].save(out_path, **save_kwargs)

    if verify_saved:
        with Image.open(out_path) as check:
            frame_count = getattr(check, "n_frames", 1)
            is_animated = bool(getattr(check, "is_animated", False))
            if frame_count != len(frames) or not is_animated:
                raise RuntimeError(f"生成的 WebP 帧数异常：期望 {len(frames)} 帧，实际 {frame_count} 帧")


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
            "继承源图工作流元数据": ("BOOLEAN", {
                "default": False,
                "label_on": "保存节点可继承源图工作流",
                "label_off": "不继承源图工作流",
                "tooltip": "仅供配套的“保存编辑图像（继承源图工作流）”节点使用。",
            }),
            "源图文件名缓存": ("STRING", {
                "default": "", "multiline": False,
                "tooltip": "由前端自动填充，不需要手动编辑。",
            }),
        })

        return {
            "required": required,
            "optional": {"输入透明遮罩": ("MASK",)},
        }

    RETURN_TYPES = ("IMAGE", "MASK", "IMAGE", "INT", "INT", "STRING", "BOOLEAN")
    RETURN_NAMES = ("RGB图像", "透明遮罩", "RGBA图像", "宽度", "高度", "源图文件名", "继承源图工作流")
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
        source_image_filename = str(_kw(kwargs, ("源图文件名缓存", "source_image_filename_cache"), "") or "")
        inherit_source_workflow = bool(_kw(kwargs, ("继承源图工作流元数据", "inherit_source_workflow_metadata"), False))

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
        return rgb, mask, rgba, out.width, out.height, source_image_filename, inherit_source_workflow


class SaveCoverInnerGifWebPFromBatch:
    """
    GIF / 动画专用节点。

    动画 WebP 专用封装策略：
    - 固定 3 帧前缀：完整表图 + 两个极小占位帧；里图从第 4 帧开始；
    - IMAGE Batch 作为里图动画帧；
    - 多帧动画使用最大有限循环 65535；
    - 不读取、也不继承源 GIF duration；统一由 FPS 构造时间轴；
    - 极少帧动画至少补足到 30 个里图帧；
    - 可对最终 RIFF 容器做无视觉影响的兼容填充，以更稳定触发聊天软件的缩略图/查看原图路径。
    默认 24 FPS。
    """

    OUTPUT_NODE = True

    def __init__(self):
        self.output_dir = folder_paths.get_output_directory()
        self.type = "output"
        self.prefix_append = ""

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "里图图片组": ("IMAGE", {
                    "tooltip": "连接 ComfyUI 加载出的 IMAGE Batch / 图片组。至少需要 2 帧；每一张 IMAGE 都按一帧动画处理。",
                }),
                "帧率(FPS)": ("FLOAT", {
                    "default": 24.0, "min": 0.1, "max": 60.0, "step": 0.1,
                    "tooltip": "统一动画帧率。默认 24 FPS，约每帧 41.7 ms。不读取也不继承原 GIF duration。",
                }),
                "动画抽帧步长": ("INT", {
                    "default": 1, "min": 1, "max": 60, "step": 1,
                    "tooltip": "1=不抽帧；2=每2帧保留1帧。抽帧后会自动延长保留帧时长，尽量保持原总播放速度。",
                }),
                "表图占位颜色": ("STRING", {
                    "default": "#FFFFFF", "multiline": False,
                    "tooltip": "当表图输入未连接时，自动使用该纯色作为表图占位。",
                }),
                "WebP质量": ("INT", {
                    "default": 82, "min": 1, "max": 100, "step": 1,
                    "tooltip": "动画 WebP 有损模式的压缩质量。",
                }),
                "无损": ("BOOLEAN", {
                    "default": False, "label_on": "开启无损", "label_off": "关闭无损",
                }),
                "元数据来源": (["图片内置元数据", "当前工作流元数据", "不保存元数据"], {
                    "default": "当前工作流元数据",
                    "tooltip": "图片组本身没有 GIF 时间轴元数据。这里只决定是否写入图片/工作流元数据，不参与帧率。",
                }),
                "文件名前缀": ("STRING", {"default": "ComfyUI_cover_inner_gif_webp"}),
                "自定义输出目录": ("STRING", {
                    "default": "", "multiline": False,
                    "tooltip": "留空时保存到 ComfyUI 默认输出目录。支持相对路径、Windows 盘符路径与 UNC 路径。",
                }),
                "里图文件名缓存": ("STRING", {
                    "default": "", "multiline": False,
                    "tooltip": "仅用于可选的图片内置元数据读取；不会用于读取 GIF 帧率。由前端自动写入。",
                }),
                "发送兼容最小体积(KiB)": ("INT", {
                    "default": 2304, "min": 0, "max": 8192, "step": 64,
                    "tooltip": "为了更稳定触发部分聊天软件的“缩略表图/点击查看原图”路径，最终 WebP 小于该体积时会追加播放器忽略的 RIFF 兼容填充。0=关闭。默认 2304 KiB，接近已验证正常样例的文件体积。",
                }),
            },
            "optional": {
                "表图": ("IMAGE",),
            },
            "hidden": {
                "prompt": "PROMPT",
                "extra_pnginfo": "EXTRA_PNGINFO",
            },
        }

    RETURN_TYPES = ("IMAGE", "STRING")
    RETURN_NAMES = ("图像", "WEBP文件路径")
    FUNCTION = "save_animated_webp"
    CATEGORY = "图像/保存"
    DESCRIPTION = "GIF/图片组专用节点：固定使用“1 张完整表图 + 2 张极小占位帧”的 3 帧前缀，里图从第 4 帧开始；IMAGE Batch 按可调 FPS 编码，默认 24 FPS，不继承原 GIF 帧率。极少帧动画会自动补足到至少 30 个里图帧，并可使用无视觉影响的 RIFF 兼容填充稳定触发缩略图/查看原图路径。"

    def save_animated_webp(self, 里图图片组, **kwargs):
        fps = float(kwargs.get("帧率(FPS)", 24.0) or 24.0)
        sample_step = max(1, int(kwargs.get("动画抽帧步长", 1) or 1))
        transport_min_kib = max(0, int(kwargs.get("发送兼容最小体积(KiB)", 2304) or 0))
        # GIF 节点固定使用 3 帧前缀：
        # 第 1 帧 = 完整表图；第 2、3 帧 = 极小占位差异帧；里图严格从第 4 帧开始。
        # 该结构按用户提供的正常样例进行对齐，可显著贴近目标软件对封面/动画 WebP 的判定方式。
        cover_count = 3
        placeholder_color = str(kwargs.get("表图占位颜色", "#FFFFFF") or "#FFFFFF")
        quality = int(kwargs.get("WebP质量", 82) or 82)
        lossless = bool(kwargs.get("无损", False))
        metadata_source = str(kwargs.get("元数据来源", "当前工作流元数据") or "当前工作流元数据")
        filename_prefix = str(kwargs.get("文件名前缀", "ComfyUI_cover_inner_gif_webp") or "ComfyUI_cover_inner_gif_webp")
        custom_output_dir = str(kwargs.get("自定义输出目录", "") or "")
        source_filename = str(kwargs.get("里图文件名缓存", "") or "")
        cover_tensor = kwargs.get("表图", None)
        prompt = kwargs.get("prompt", None)
        extra_pnginfo = kwargs.get("extra_pnginfo", None)

        self.output_dir = _normalize_output_directory(custom_output_dir, folder_paths.get_output_directory())
        inner_frames = _tensor_to_pil_frames(里图图片组)
        if len(inner_frames) < 2:
            raise ValueError(
                "“表里GIF合并编辑器”至少需要 2 帧 IMAGE Batch。"
                "若只有 1 张静态里图，请使用“表里图合并编辑器”。"
            )

        # ComfyUI IMAGE Batch 只携带图像帧，不携带可靠的 GIF duration。
        # 因此这里完全不读取源 GIF 帧率，统一由 FPS 构造时间轴。
        fps = max(0.1, min(60.0, fps))
        frame_duration_ms = max(1, int(round(1000.0 / fps)))
        inner_durations = [frame_duration_ms] * len(inner_frames)
        inner_frames, inner_durations = _subsample_animation_frames(
            inner_frames, inner_durations, sample_step
        )
        # 对极少帧动画做循环补足：至少 30 个里图帧。
        # 已验证正常样例恰好为 30 个里图帧；少于该规模时，部分聊天软件更容易
        # 走“聊天流里直接播放动画”的路径，而不是缩略表图/查看原图路径。
        min_effective_inner_frames = max(30, int(round(fps)))
        inner_frames, inner_durations = _repeat_animation_to_minimum(
            inner_frames, inner_durations, min_effective_inner_frames
        )

        cover_frames = _tensor_to_pil_frames(cover_tensor) if cover_tensor is not None else []
        cover_image = cover_frames[0] if cover_frames else None
        frames, _unused, (width, height) = _prepare_cover_inner_webp_frames(
            cover_image=cover_image,
            inner_frames=inner_frames,
            cover_frame_count=cover_count,
            placeholder_color=placeholder_color,
        )

        # GIF 节点按样例结构写入 3 帧前缀：
        # - 第 1 帧完整表图 1 ms
        # - 第 2、3 帧极小占位差异帧各 1 ms
        # - 第 4 帧开始为里图动画
        # 同时保持 65535 次循环，不使用 0 ms / loop=0 方案。
        durations = ([1] * cover_count) + list(inner_durations)
        output_loop_count = 65535

        full_output_folder, filename, counter, subfolder, filename_prefix = folder_paths.get_save_image_path(
            filename_prefix + self.prefix_append, self.output_dir, width, height
        )
        os.makedirs(full_output_folder, exist_ok=True)

        selected_metadata, marker, native_prompt, native_extra_pnginfo = _build_webp_metadata_payload(
            metadata_source=metadata_source,
            source_image_filename=source_filename,
            cover_frame_count=cover_count,
            inner_frame_count=len(inner_frames),
            prompt=prompt,
            extra_pnginfo=extra_pnginfo,
            media_type_override="animation_batch",
        )
        marker["hbe_animation_fps"] = float(fps)
        marker["hbe_animation_frame_duration_ms"] = int(frame_duration_ms)
        marker["hbe_inner_effective_durations_ms"] = [int(v) for v in inner_durations]
        marker["hbe_min_effective_inner_frames"] = int(min_effective_inner_frames)
        marker["hbe_inner_frame_count_after_repeat"] = int(len(inner_frames))
        marker["hbe_transport_min_size_kib"] = int(transport_min_kib)
        marker["hbe_transport_padding_mode"] = "riff_unknown_chunk_HBEF" if transport_min_kib > 0 else "disabled"
        marker["hbe_frame_sample_step"] = int(sample_step)
        marker["hbe_animation_loop"] = int(output_loop_count)
        marker["hbe_cover_frame_duration_ms"] = 1
        marker["hbe_cover_mode"] = "full_cover_then_two_tiny_placeholder_frames"
        marker["hbe_playback_policy"] = "sample_matched_3_prefix_frames_animation_batch"
        marker["hbe_timing_source"] = "fixed_fps_from_image_batch"

        native_prompt, native_extra_pnginfo = _metadata_to_native_prompt_and_extra(selected_metadata, marker=marker)
        native_exif = _build_native_comfy_webp_exif(
            frames[0], prompt=native_prompt, extra_pnginfo=native_extra_pnginfo
        )

        file = f"{filename}_{counter:05}_.webp"
        out_path = os.path.join(full_output_folder, file)
        _save_frames_as_webp(
            frames=frames,
            durations=durations,
            out_path=out_path,
            quality=quality,
            lossless=lossless,
            extra_save_kwargs={"exif": native_exif, "method": 4, "exact": False},
            loop_count=output_loop_count,
            preserve_duplicate_frames=True,
            verify_saved=False,
        )

        encoded_size_before_padding = os.path.getsize(out_path)
        final_size_bytes = _pad_webp_riff_to_min_size(
            out_path, transport_min_kib * 1024
        ) if transport_min_kib > 0 else encoded_size_before_padding
        native_metadata = {}
        preview_ref = _build_ui_preview_image_result(frames[0], preview_prefix="ComfyUI_hbe_gif_preview")
        ui_result = {
            **preview_ref,
            "saved_filename": file,
            "saved_subfolder": subfolder,
            "saved_type": self.type,
            "metadata_source": metadata_source,
            "inner_start_frame": int(marker.get("hbe_inner_start_frame", cover_count + 1)),
            "fps": float(fps),
            "loop": int(output_loop_count),
            "encoded_size_before_padding": int(encoded_size_before_padding),
            "final_size_bytes": int(final_size_bytes),
            "transport_min_kib": int(transport_min_kib),
            "comfyui_webp_metadata_keys": sorted(native_extra_pnginfo.keys()) if isinstance(native_extra_pnginfo, dict) else [],
            "drag_workflow_ready": bool((native_extra_pnginfo or {}).get("workflow")) if isinstance(native_extra_pnginfo, dict) else False,
        }
        if selected_metadata:
            ui_result["source_metadata_keys"] = sorted(selected_metadata.keys())

        return {
            "ui": {"images": [ui_result]},
            "result": (_pil_frames_to_image_batch([frames[0]]), out_path),
        }


class SaveCoverInnerOverlayMerged:
    """统一表里叠图节点：可输出 PNG(APNG) 或 WebP，默认 PNG。"""

    OUTPUT_NODE = True

    def __init__(self):
        self.output_dir = folder_paths.get_output_directory()
        self.type = "output"
        self.prefix_append = ""

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "里图": ("IMAGE", {
                    "tooltip": "仅支持单张静态图片。输出格式可选 PNG(APNG) 或 WebP。",
                }),
                "输出格式": (["PNG", "WEBP"], {
                    "default": "PNG",
                    "tooltip": "PNG：输出 APNG，默认图像为表图，点击查看进入里图；WEBP：输出表里叠图 WebP。",
                }),
                "表图占位颜色": ("STRING", {
                    "default": "#FFFFFF", "multiline": False,
                    "tooltip": "当表图输入未连接时，自动使用该纯色作为表图占位。",
                }),
                "发送兼容最小体积(KiB)": ("INT", {
                    "default": 2304, "min": 0, "max": 262144, "step": 1,
                    "tooltip": "PNG/APNG 与单图 WebP 共用的发送兼容体积阈值。若输出文件小于该体积，会追加不会影响显示的容器填充，以更稳定触发“文件发送时显示表图，点击查看时显示里图”的行为。填 0 表示禁用。",
                }),
                "WebP质量": ("INT", {
                    "default": 82, "min": 1, "max": 100, "step": 1,
                    "tooltip": "仅对 WEBP 生效。PNG 模式下会自动隐藏。",
                }),
                "无损": ("BOOLEAN", {
                    "default": False, "label_on": "开启无损", "label_off": "关闭无损",
                }),
                "元数据来源": (["图片内置元数据", "当前工作流元数据", "不保存元数据"], {
                    "default": "图片内置元数据",
                    "tooltip": "图片内置元数据：读取里图源文件元数据；当前工作流元数据：使用 ComfyUI 当前执行工作流。",
                }),
                "文件名前缀": ("STRING", {"default": "ComfyUI_cover_inner_overlay"}),
                "自定义输出目录": ("STRING", {
                    "default": "", "multiline": False,
                    "tooltip": "留空时保存到 ComfyUI 默认输出目录。支持相对路径、Windows 盘符路径与 UNC 路径。",
                }),
                "里图文件名缓存": ("STRING", {
                    "default": "", "multiline": False,
                    "tooltip": "由前端自动写入并始终隐藏，用于“图片内置元数据”模式。",
                }),
            },
            "optional": {
                "表图": ("IMAGE",),
            },
            "hidden": {
                "prompt": "PROMPT",
                "extra_pnginfo": "EXTRA_PNGINFO",
            },
        }

    RETURN_TYPES = ("IMAGE", "STRING")
    RETURN_NAMES = ("图像", "文件路径")
    FUNCTION = "save_overlay"
    CATEGORY = "图像/保存"
    DESCRIPTION = "Unified cover-inner overlay merge node. Outputs PNG(APNG) or WebP, default PNG. Includes color picker, workflow metadata saving, 2304 KiB transport padding, and compatibility with both classic ComfyUI and Nodes 2.0."

    def save_overlay(self, 里图, 输出格式="PNG", 表图占位颜色="#FFFFFF",
                     发送兼容最小体积_KiB=2304, WebP质量=82, 无损=False, 元数据来源="图片内置元数据",
                     文件名前缀="ComfyUI_cover_inner_overlay", 自定义输出目录="", 里图文件名缓存="", 表图=None,
                     prompt=None, extra_pnginfo=None, **kwargs):
        if "发送兼容最小体积(KiB)" in kwargs:
            发送兼容最小体积_KiB = kwargs.get("发送兼容最小体积(KiB)", 发送兼容最小体积_KiB)

        fmt = str(输出格式 or "PNG").strip().upper()
        if fmt not in {"PNG", "WEBP"}:
            fmt = "PNG"

        self.output_dir = _normalize_output_directory(自定义输出目录, folder_paths.get_output_directory())
        inner_frames = _tensor_to_pil_frames(里图)
        if len(inner_frames) != 1:
            raise ValueError(
                f'“表里叠图合并节点”只处理单张静态图片；检测到 {len(inner_frames)} 帧。'
                '若是 IMAGE Batch / GIF 帧序列，请继续使用“表里GIF合并编辑器”。'
            )

        inner_image = inner_frames[0].convert("RGBA")
        target_size = inner_image.size
        cover_frames = _tensor_to_pil_frames(表图) if 表图 is not None else []
        cover_image = cover_frames[0] if cover_frames else None
        if cover_image is None:
            rgba = _parse_hex_color(表图占位颜色, (255, 255, 255, 255))
            cover = Image.new("RGBA", target_size, rgba)
        else:
            cover = _crop_to_canvas(cover_image, target_size)

        filename_prefix = 文件名前缀 + self.prefix_append
        full_output_folder, filename, counter, subfolder, filename_prefix = folder_paths.get_save_image_path(
            filename_prefix, self.output_dir, target_size[0], target_size[1]
        )
        os.makedirs(full_output_folder, exist_ok=True)

        # 单图统一使用两张几乎相同的里图帧，避免部分前端/客户端把它当作普通静态图处理。
        inner_anim_frames = [inner_image, _make_distinct_duplicate_frame(inner_image, 1)]

        min_size_bytes = max(0, int(发送兼容最小体积_KiB or 0)) * 1024

        if fmt == "PNG":
            frame_duration_ms = 100
            durations = [frame_duration_ms, frame_duration_ms]
            selected_metadata, marker, native_prompt, native_extra_pnginfo = _build_webp_metadata_payload(
                metadata_source=元数据来源,
                source_image_filename=里图文件名缓存,
                cover_frame_count=1,
                inner_frame_count=len(inner_anim_frames),
                prompt=prompt,
                extra_pnginfo=extra_pnginfo,
                media_type_override="image",
                source_ext_override=".png",
            )
            marker["hbe_container_type"] = "apng"
            marker["hbe_inner_effective_durations_ms"] = [int(v) for v in durations]
            marker["hbe_cover_mode"] = "png_default_image_cover"
            marker["hbe_animation_loop"] = 0
            marker["hbe_playback_policy"] = "apng_default_image_then_two_inner_frames"
            marker["hbe_transport_padding_mode"] = "png_standard_tEXt_before_acTL" if min_size_bytes > 0 else "disabled"
            native_prompt, native_extra_pnginfo = _metadata_to_native_prompt_and_extra(selected_metadata, marker=marker)
            pnginfo = _build_native_pnginfo_from_prompt_extra(
                prompt=native_prompt,
                extra_pnginfo=native_extra_pnginfo,
            )

            file = f"{filename}_{counter:05}_.png"
            out_path = os.path.join(full_output_folder, file)
            _save_frames_as_apng(
                default_image=cover,
                frames=inner_anim_frames,
                durations=durations,
                out_path=out_path,
                pnginfo=pnginfo,
                loop_count=0,
            )
            final_size = _pad_png_to_min_size(out_path, min_size_bytes)

            preview_ref = _build_ui_preview_image_result(cover, preview_prefix="ComfyUI_hbe_overlay_preview")
            ui_result = {
                **preview_ref,
                "saved_filename": file,
                "saved_subfolder": subfolder,
                "saved_type": self.type,
                "output_format": "PNG",
                "metadata_source": 元数据来源,
                "default_image_cover": True,
                "animated_inner_frame_count": len(inner_anim_frames),
                "frame_duration_ms": int(frame_duration_ms),
                "final_size_bytes": int(final_size),
                "transport_min_size_kib": int(发送兼容最小体积_KiB or 0),
                "drag_workflow_ready": bool((native_extra_pnginfo or {}).get("workflow")) if isinstance(native_extra_pnginfo, dict) else False,
                "comfyui_png_metadata_keys": sorted(native_extra_pnginfo.keys()) if isinstance(native_extra_pnginfo, dict) else [],
            }
            if selected_metadata:
                ui_result["source_metadata_keys"] = sorted(selected_metadata.keys())

            preview_frames = [cover] + inner_anim_frames
            return {
                "ui": {"images": [ui_result]},
                "result": (_pil_frames_to_image_batch(preview_frames), out_path),
            }

        # WEBP 单图模式
        cover_count = 2
        frames = []
        for i in range(cover_count):
            frames.append(cover.copy() if i == 0 else _make_distinct_duplicate_frame(cover, i))
        frames.extend(inner_anim_frames)
        effective_inner_durations = [600_000, 600_000]
        durations = ([1] * cover_count) + effective_inner_durations
        output_loop_count = 1

        selected_metadata, marker, native_prompt, native_extra_pnginfo = _build_webp_metadata_payload(
            metadata_source=元数据来源,
            source_image_filename=里图文件名缓存,
            cover_frame_count=cover_count,
            inner_frame_count=len(inner_anim_frames),
            prompt=prompt,
            extra_pnginfo=extra_pnginfo,
            media_type_override="image",
        )
        marker["hbe_inner_effective_durations_ms"] = effective_inner_durations
        marker["hbe_cover_mode"] = "first_frame_poster"
        marker["hbe_animation_loop"] = int(output_loop_count)
        marker["hbe_playback_policy"] = "static_cover_then_two_inner_frames"
        marker["hbe_transport_padding_mode"] = "riff_unknown_chunk_HBEF" if min_size_bytes > 0 else "disabled"
        native_prompt, native_extra_pnginfo = _metadata_to_native_prompt_and_extra(selected_metadata, marker=marker)
        native_exif = _build_native_comfy_webp_exif(
            frames[0], prompt=native_prompt, extra_pnginfo=native_extra_pnginfo
        )

        file = f"{filename}_{counter:05}_.webp"
        out_path = os.path.join(full_output_folder, file)
        _save_frames_as_webp(
            frames=frames,
            durations=durations,
            out_path=out_path,
            quality=WebP质量,
            lossless=无损,
            extra_save_kwargs={"exif": native_exif},
            loop_count=output_loop_count,
        )
        final_size = _pad_webp_riff_to_min_size(out_path, min_size_bytes)

        preview_ref = _build_ui_preview_image_result(cover, preview_prefix="ComfyUI_hbe_overlay_preview")
        ui_result = {
            **preview_ref,
            "saved_filename": file,
            "saved_subfolder": subfolder,
            "saved_type": self.type,
            "output_format": "WEBP",
            "metadata_source": 元数据来源,
            "inner_start_frame": int(marker.get("hbe_inner_start_frame", cover_count + 1)),
            "animated_inner_frame_count": len(inner_anim_frames),
            "final_size_bytes": int(final_size),
            "transport_min_size_kib": int(发送兼容最小体积_KiB or 0),
            "drag_workflow_ready": bool((native_extra_pnginfo or {}).get("workflow")) if isinstance(native_extra_pnginfo, dict) else False,
            "comfyui_webp_metadata_keys": sorted(native_extra_pnginfo.keys()) if isinstance(native_extra_pnginfo, dict) else [],
        }
        if selected_metadata:
            ui_result["source_metadata_keys"] = sorted(selected_metadata.keys())

        return {
            "ui": {"images": [ui_result]},
            "result": (_pil_frames_to_image_batch(frames), out_path),
        }


class ReadInnerImage:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "图片文件": (_list_available_webp_images(), {
                    "image_upload": True,
                    "tooltip": "选择或上传由表里叠图节点生成的 WebP / PNG(APNG)。节点会自动判定容器并只输出其中标记的里图帧。",
                }),
            }
        }

    CATEGORY = "图像/加载"
    RETURN_TYPES = ("IMAGE",)
    RETURN_NAMES = ("里图",)
    FUNCTION = "load_inner_image"
    DESCRIPTION = "Read inner image from a generated WebP or PNG/APNG. The node automatically detects the container and extracts only the marked inner frames."

    @classmethod
    def IS_CHANGED(cls, 图片文件):
        path = _resolve_any_image_path(图片文件)
        if not path or not os.path.exists(path):
            return float("nan")
        return os.path.getmtime(path)

    def load_inner_image(self, 图片文件):
        resolved = _resolve_any_image_path(图片文件)
        if not resolved:
            raise FileNotFoundError(f"找不到图片文件：{图片文件}")
        ext = os.path.splitext(resolved)[1].lower()
        if ext not in {".webp", ".png"}:
            raise ValueError("“读取里图节点”只接受 .webp 或 .png(APNG) 文件。")

        # 只读取一次元数据，再使用 ComfyUI 原生 LoadImage 解码像素/动画帧。
        metadata = _extract_metadata_from_image(resolved)
        info = _extract_cover_inner_info(metadata)
        if not info.get("has_marker"):
            raise ValueError("该 PNG/APNG 或 WebP 不包含本插件的表里图标记，无法确定里图范围。请确认文件由本插件的表里叠图节点生成。")

        images, _masks = _load_image_tensors_with_comfy_native(图片文件)
        frame_count = int(images.shape[0]) if hasattr(images, "shape") and len(images.shape) > 0 else 1

        start_index = max(0, min(int(info.get("start_index", 0)), frame_count))
        declared_count = int(info.get("inner_frame_count", 0) or 0)
        end_index = frame_count if declared_count <= 0 else min(frame_count, start_index + declared_count)

        if start_index >= end_index:
            raise ValueError(
                f"图片中记录的里图范围无效：起始索引 {start_index}，总帧数 {frame_count}。"
            )

        # Tensor 切片是 view，不额外复制整批像素；多帧会直接作为 ComfyUI IMAGE 图片组输出。
        inner_images = images[start_index:end_index]
        return (inner_images,)


NODE_CLASS_MAPPINGS = {
    "HorizontalBandEditor": HorizontalBandEditor,
    "SaveCoverInnerOverlayMerged": SaveCoverInnerOverlayMerged,
    "SaveCoverInnerGifWebPFromBatch": SaveCoverInnerGifWebPFromBatch,
    "ReadInnerImage": ReadInnerImage,
}
NODE_DISPLAY_NAME_MAPPINGS = {
    "HorizontalBandEditor": "Horizontal Band Editor",
    "SaveCoverInnerOverlayMerged": "Cover-Inner Overlay Merge",
    "SaveCoverInnerGifWebPFromBatch": "Cover-Inner GIF Merge",
    "ReadInnerImage": "Read Inner Image",
}
