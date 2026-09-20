# ComfyUI Horizontal Band Editor

一个用于 **横向整宽选区截断 / 文字面板替换** 的 ComfyUI 自定义节点。

节点中文名：**横向区域截断 / 文字面板编辑器**

## 功能

- 节点内直接上传/选择图片。
- 在节点预览图上用鼠标或触摸笔 **纵向拖拽** 选择区域。
- 选区的横向宽度始终固定为 **整张输入图的宽度**，只需要确定上边界和下边界。
- 模式 1：`删除选区并拼接`
  - 删除整条横向区域。
  - 把原图选区上方和下方直接拼接起来。
- 模式 2：`替换为文字面板`
  - 用纯色或透明背景替换原选区。
  - 在区域内输入多行文字。
  - 默认字体为 `SimHei`（简中黑体）。
  - 支持字号、文字颜色、背景色、内边距、行距、水平/垂直对齐。
  - 自动按图片宽度换行。
  - 如果文字所需高度大于原选区高度，**输出图片会自动向下扩展高度**，保证文字不被裁掉。
- 透明支持：
  - `RGB_IMAGE`：标准 3 通道图片，兼容大多数 ComfyUI 图像节点。
  - `TRANSPARENCY_MASK`：ComfyUI 标准透明蒙版，`1 = 透明`。
  - `RGBA_IMAGE`：4 通道 RGBA 图片，可用于支持 Alpha 的保存/后处理节点。
- 输出最终 `WIDTH / HEIGHT`。

## 安装

把整个文件夹放到：

```text
ComfyUI/custom_nodes/ComfyUI-HorizontalBandEditor/
```

然后重启 ComfyUI，并在浏览器执行一次硬刷新：

```text
Ctrl + F5
```

Windows 便携版典型路径：

```text
ComfyUI_windows_portable/ComfyUI/custom_nodes/ComfyUI-HorizontalBandEditor/
```

本插件不需要额外 `pip install`。

## 使用

1. 新增节点：

```text
image/editing
└─ 横向区域截断 / 文字面板编辑器
```

2. 在 `image` 中上传或选择图片。
3. 在节点内部预览图上按住鼠标拖拽，上下确定横向条带范围。
4. 使用 `text_panel_enabled` 开关：
   - 关闭：删除选区并把上下两部分拼接。
   - 开启：把选区替换为文字面板。
5. 如果开启文字面板：
   - `panel_background = 纯色`：使用 `background_color`。
   - `panel_background = 透明`：面板底色透明，但文字仍保持正常 Alpha。
   - `text`：输入文字。
   - `font_size`：字号。
   - `text_color`：文字颜色，如 `#000000`。
   - `font_name_or_path`：默认 `SimHei`。
6. 执行工作流。

## 透明 PNG 建议

如果你后续节点明确支持 4 通道 IMAGE，可以直接使用 `RGBA_IMAGE`。

如果你希望走最标准的 ComfyUI 透明流程：

```text
RGB_IMAGE --------------------┐
                              ├─ Join Image With Alpha ── Save Image
TRANSPARENCY_MASK --(注意极性)┘
```

本插件的 `TRANSPARENCY_MASK` 遵循 `Load Image` 一样的 ComfyUI 约定：**1 表示透明**。
ComfyUI 内置 `Join Image with Alpha` 会按这一标准读取 MASK，所以 `TRANSPARENCY_MASK` 可以直接连接到它的 `alpha` 输入。

插件同时提供 `RGBA_IMAGE`，所以最省事的透明保存方式通常是直接把它接到支持 RGBA 的保存节点。

## 字体

默认值是：

```text
SimHei
```

插件会自动尝试：

- Windows：`simhei.ttf`、微软雅黑。
- Linux：Noto Sans CJK、文泉驿。
- macOS：PingFang / STHeiti。

如果服务器上没有这些字体，在 `font_name_or_path` 里填写完整字体文件路径。例如 Windows：

```text
C:\Windows\Fonts\simhei.ttf
```

注意：ComfyUI 后端运行在哪台机器，字体就必须存在于哪台机器。

## 颜色格式

支持：

```text
#RGB
#RRGGBB
#RRGGBBAA
```

纯色面板会强制背景 Alpha 为不透明；需要透明底请直接选择 `panel_background = 透明`。

## 选区数值

可视化拖拽会同步更新：

- `selection_top_px`
- `selection_bottom_px`

因此工作流保存后，重新加载仍能恢复同一像素选区。
