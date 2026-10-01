# ComfyUI-HorizontalBandEditor

ComfyUI-HorizontalBandEditor 是一个面向图片截面编辑、表图/里图合成与里图读取的 ComfyUI 自定义节点插件。

当前版本：`1.26.0`

插件包含以下功能：

- 横向区域删除与自动拼接
- 横向文字面板替换
- PNG/APNG 表图 / 里图合成
- WebP 表图 / 里图合成
- GIF / IMAGE Batch 动画表图 / 里图 WebP 合成
- PNG/APNG 与 WebP 里图自动读取
- ComfyUI 工作流元数据写入
- 自定义输出目录
- 发送兼容体积填充
- 经典 UI 与 Nodes 2.0 兼容
- 中文 / 英文节点标题
- 旧版本工作流节点自动迁移

---

## 节点列表

| 英文名称 | 中文名称 | 分类 | 功能 |
| --- | --- | --- | --- |
| `Horizontal Band Editor` | 横向截断面板编辑器 | 图像 / 编辑 | 删除或替换多个横向截面，并重新拼接图片 |
| `Cover-Inner Overlay Merge` | 表里叠图合并节点 | 图像 / 保存 | 合成单张静态表图 / 里图，支持 PNG/APNG 和 WebP |
| `Cover-Inner GIF Merge` | 表里GIF合并编辑器 | 图像 / 保存 | 将 IMAGE Batch 作为动画里图并生成表图 / 里图 WebP |
| `Read Inner Image` | 读取里图节点 | 图像 / 加载 | 自动读取插件生成的 PNG/APNG 或 WebP 里的里图 |

---

# 安装

将插件目录放入：

```text
ComfyUI/custom_nodes/ComfyUI-HorizontalBandEditor/
```

目录结构应类似：

```text
ComfyUI-HorizontalBandEditor/
├─ __init__.py
├─ nodes.py
├─ README.md
├─ requirements.txt
├─ locales/
└─ web/
```

安装或覆盖更新后：

1. 重启 ComfyUI。
2. 浏览器执行一次强制刷新：

```text
Ctrl + F5
```

插件主要依赖 ComfyUI 环境自带的：

```text
Pillow
NumPy
PyTorch
```

通常不需要额外安装 Python 包。

---

# 界面与兼容性

插件支持：

- ComfyUI 经典节点界面
- ComfyUI Nodes 2.0
- 中文界面
- 英文界面

英文环境下显示英文节点标题；中文环境下显示对应中文标题。

节点中的动态参数会根据当前模式自动显示或隐藏，例如 `Cover-Inner Overlay Merge` 选择 `WEBP` 时才显示 WebP 质量相关参数。

---

# 1. Horizontal Band Editor / 横向截断面板编辑器

用于编辑图片中的一个或多个完整横向区域。

每个截面始终横跨整张图片宽度，只需要设置截面的上边界和下边界。

## 输入

### 输入图像

类型：

```text
IMAGE
```

可连接任意 ComfyUI IMAGE 输出，例如：

- Load Image
- VAE Decode
- 图片处理节点输出

### 输入透明遮罩

类型：

```text
MASK
```

可选。

用于保留输入图片已有的透明信息。

---

## 截面设置

最多支持 12 个横向截面：

```text
A B C D E F G H I J K L
```

### 截面数量

控制当前启用的截面数量。

范围：

```text
1 - 12
```

### 编辑截面

选择当前正在编辑的截面。

### 截面 X 上边界 / 下边界

单位：

```text
px
```

用于确定每个横向区域的位置。

节点预览区支持直接拖拽设置截面位置。

---

## 删除模式

当：

```text
启用文字面板 = 关闭
```

所有有效截面都会从原图中删除，剩余部分自动向上拼接。

例如：

```text
原图顶部
截面 A
中间区域
截面 B
原图底部
```

处理后：

```text
原图顶部
中间区域
原图底部
```

---

## 文字面板模式

当：

```text
启用文字面板 = 开启
```

截面不会被删除，而会替换成文字面板。

可设置：

| 参数 | 说明 |
| --- | --- |
| 面板背景 | `纯色` / `透明` |
| 背景颜色 | 文字面板背景色 |
| 文字内容 | 面板内显示的文本 |
| 文字颜色 | 文本颜色 |
| 字体名称或路径 | 字体名称或字体文件完整路径 |
| 字号 | 文字大小 |
| 内边距 | 文本与面板边缘之间的距离 |
| 行距 | 多行文字间距 |
| 水平对齐 | 居中 / 左对齐 / 右对齐 |
| 垂直对齐 | 居中 / 顶部 / 底部 |

当文字实际需要的高度大于原截面高度时，输出图片高度会自动增加。

---

## 调色盘

以下参数支持颜色选择器：

```text
背景颜色
文字颜色
```

也可以直接输入十六进制颜色：

```text
#FFFFFF
#000000
#FF88CC
```

---

## 预览区域

节点底部带有图片预览与截面编辑区域。

支持：

- 拖动截面上边缘
- 拖动截面下边缘
- 拖动整个截面
- 点击截面切换当前编辑对象
- 在空白位置拖动创建当前截面
- 节点缩放时同步调整预览区域

---

## 输出

节点输出：

| 输出 | 类型 | 说明 |
| --- | --- | --- |
| RGB图像 | IMAGE | RGB 输出 |
| 透明遮罩 | MASK | 对应透明区域遮罩 |
| RGBA图像 | IMAGE | 带透明信息的图像 |
| 宽度 | INT | 输出宽度 |
| 高度 | INT | 输出高度 |
| 源图文件名 | STRING | 前端检测到的源图片文件名 |
| 继承源图工作流 | BOOLEAN | 当前工作流继承状态 |

---

# 2. Cover-Inner Overlay Merge / 表里叠图合并节点

用于合成单张静态表图和单张静态里图。

支持两种输出格式：

```text
PNG
WEBP
```

默认：

```text
PNG
```

该节点仅处理单张静态里图。

多帧 IMAGE Batch 应使用 `Cover-Inner GIF Merge / 表里GIF合并编辑器`。

---

## 输入

### 里图

类型：

```text
IMAGE
```

必填。

必须为单张图片。

### 表图

类型：

```text
IMAGE
```

可选。

如果未连接表图，则使用 `表图占位颜色` 创建与里图尺寸相同的纯色表图。

如果表图与里图尺寸不同，表图会缩放裁剪到里图尺寸。

---

## 输出格式

### PNG

实际输出为 APNG。

结构：

```text
默认静态图像：表图
动画帧 1：里图
动画帧 2：几乎相同的里图
```

APNG 使用默认图像作为表图，里图作为动画内容。

两张里图帧之间保留极小像素差异，避免编码器将重复帧合并。

PNG 模式下里图动画帧时长固定为：

```text
100 ms / 帧
```

---

### WEBP

结构：

```text
第 1 帧：表图
第 2 帧：表图的极小差异帧
第 3 帧：里图
第 4 帧：里图的极小差异帧
```

WebP 表图前缀固定为 2 帧。

两张里图帧的长停留时间固定为：

```text
600000 ms
```

WebP 单图模式使用有限循环：

```text
loop = 1
```

---

## 参数

### 输出格式

```text
PNG
WEBP
```

默认：

```text
PNG
```

### 表图占位颜色

表图未连接时使用的颜色。

默认：

```text
#FFFFFF
```

节点提供调色盘和十六进制颜色输入。

### 发送兼容最小体积(KiB)

默认：

```text
2304 KiB
```

当输出文件小于该体积时，插件会向容器中写入不影响可见内容的兼容填充数据，使最终文件达到指定最小体积。

设置为：

```text
0
```

可关闭体积填充。

PNG/APNG 使用 PNG ancillary chunk 填充；WebP 使用 RIFF 自定义 chunk 填充。

### WebP质量

仅在：

```text
输出格式 = WEBP
```

时显示。

范围：

```text
1 - 100
```

默认：

```text
82
```

### 无损

仅用于 WebP。

开启后使用 WebP 无损编码。

### 元数据来源

可选：

```text
图片内置元数据
当前工作流元数据
不保存元数据
```

#### 图片内置元数据

读取里图源图片已有的元数据并写入输出文件。

#### 当前工作流元数据

保存当前 ComfyUI prompt / workflow 信息。

#### 不保存元数据

不写入额外工作流元数据。

### 文件名前缀

默认：

```text
ComfyUI_cover_inner_overlay
```

### 自定义输出目录

留空时输出到 ComfyUI 默认：

```text
output/
```

支持：

- 相对路径
- Windows 盘符绝对路径
- UNC 路径

---

## 前端预览

最终文件可以保存到自定义目录。

为了兼容 ComfyUI 经典 UI 和 Nodes 2.0 的图片预览，插件会在 ComfyUI 默认 `output` 目录额外保存一张轻量 PNG 预览图。

该预览图仅用于节点界面显示，不替代最终输出文件。

---

## 输出

| 输出 | 类型 | 说明 |
| --- | --- | --- |
| 图像 | IMAGE | 合成后的内部帧组 |
| 文件路径 | STRING | 实际保存的 PNG 或 WebP 文件路径 |

---

# 3. Cover-Inner GIF Merge / 表里GIF合并编辑器

用于将多帧 IMAGE Batch 作为里图动画，并生成动画 WebP。

该节点不直接读取 GIF 文件的原始 duration，而是将 ComfyUI IMAGE Batch 中的每张图片视为一帧，并使用节点设置的 FPS 重新建立动画时间轴。

---

## 输入

### 里图图片组

类型：

```text
IMAGE
```

至少需要：

```text
2 帧
```

输入可以来自：

- GIF 加载节点输出
- 图片序列
- IMAGE Batch
- 其他批量图片节点

### 表图

类型：

```text
IMAGE
```

可选。

未连接时使用 `表图占位颜色`。

---

## 动画结构

输出 WebP 的前缀固定为：

```text
第 1 帧：完整表图
第 2 帧：极小占位差异帧
第 3 帧：极小占位差异帧
第 4 帧开始：里图动画
```

前 3 帧持续时间均为：

```text
1 ms
```

里图从第 4 帧开始。

动画循环：

```text
65535
```

---

## 帧率(FPS)

默认：

```text
24 FPS
```

范围：

```text
0.1 - 60 FPS
```

每帧持续时间由 FPS 计算：

```text
1000 / FPS
```

例如：

```text
24 FPS ≈ 41.7 ms / 帧
30 FPS ≈ 33.3 ms / 帧
```

源 GIF 的原始帧时长不会被继承。

---

## 动画抽帧步长

默认：

```text
1
```

含义：

```text
1 = 不抽帧
2 = 每 2 帧保留 1 帧
3 = 每 3 帧保留 1 帧
```

抽帧时，被跳过帧的持续时间会累加到保留帧，以尽量维持总播放时长。

---

## 极少帧动画补帧

当输入动画帧数过少时，节点会循环重复已有帧，使有效里图动画至少达到：

```text
30 帧
```

如果当前 FPS 高于 30，则最小有效帧数会采用当前 FPS 对应的整数值。

例如：

```text
24 FPS -> 至少 30 个里图帧
60 FPS -> 至少 60 个里图帧
```

补帧不会生成新的画面内容，只会重复已有动画帧。

---

## 表图占位颜色

表图未连接时使用。

默认：

```text
#FFFFFF
```

支持调色盘与十六进制输入。

---

## WebP质量

默认：

```text
82
```

范围：

```text
1 - 100
```

---

## 无损

开启后使用 WebP 无损编码。

---

## 发送兼容最小体积(KiB)

默认：

```text
2304 KiB
```

当编码后的 WebP 小于该体积时，会在 RIFF 容器中追加兼容填充数据。

填充不会增加动画帧，也不会改变 FPS、循环次数或可见画面。

设置为：

```text
0
```

可关闭。

---

## 元数据来源

可选：

```text
图片内置元数据
当前工作流元数据
不保存元数据
```

GIF / IMAGE Batch 本身不提供可靠的 GIF 时间轴元数据，因此该设置只控制输出文件中的 ComfyUI / 图片元数据，不影响 FPS。

---

## 文件名前缀

默认：

```text
ComfyUI_cover_inner_gif_webp
```

---

## 自定义输出目录

留空时保存到 ComfyUI 默认输出目录。

支持 Windows 绝对路径和相对路径。

---

## 输出

| 输出 | 类型 | 说明 |
| --- | --- | --- |
| 图像 | IMAGE | 表图首帧预览 |
| WEBP文件路径 | STRING | 实际生成的动画 WebP 路径 |

---

# 4. Read Inner Image / 读取里图节点

用于读取本插件生成的表图 / 里图文件，并只输出其中的里图部分。

支持：

```text
.webp
.png
```

PNG 文件可以是插件生成的 APNG。

---

## 图片文件

选择或上传插件生成的：

- PNG/APNG
- WebP
- 动画 WebP

节点会读取文件中的 HBE 元数据标记，并自动确定：

- 里图起始位置
- 里图帧数量
- 容器格式

---

## 单图 PNG/APNG

`Cover-Inner Overlay Merge` 的 PNG 模式会保存 2 张里图动画帧。

读取节点会输出这 2 张里图帧组成的 IMAGE Batch。

---

## 单图 WebP

`Cover-Inner Overlay Merge` 的 WebP 模式会保存 2 张里图帧。

读取节点会跳过表图前缀，只输出对应的里图 IMAGE Batch。

---

## 动画 WebP

`Cover-Inner GIF Merge` 生成的文件会保留完整里图动画帧。

读取节点会跳过 3 帧表图前缀，直接输出动画里图部分。

输出仍然是 ComfyUI 的：

```text
IMAGE Batch
```

因此可以继续连接其他批处理节点。

---

## 文件要求

读取节点依赖插件写入的 HBE 标记。

普通 PNG / WebP 文件如果没有对应标记，节点无法确定里图范围。

---

# 元数据与工作流

表里图保存节点会在输出文件中写入 HBE 标记，用于记录：

- 文件是否为表里图
- 里图起始帧
- 里图帧数量
- 容器类型
- 动画 FPS
- 动画持续时间
- 循环方式
- 发送兼容体积设置
- 元数据来源

当 `元数据来源` 选择：

```text
当前工作流元数据
```

时，会同时保存 ComfyUI 当前工作流数据。

PNG/APNG 使用 PNG 文本元数据。

WebP 使用 WebP EXIF 元数据。

插件前端包含 WebP 工作流读取兼容处理，用于补充部分 ComfyUI 版本对 WebP workflow 拖入读取不完整的问题。

---

# 发送兼容体积填充

`Cover-Inner Overlay Merge` 和 `Cover-Inner GIF Merge` 都支持：

```text
发送兼容最小体积(KiB)
```

默认：

```text
2304
```

当文件低于指定体积时：

### PNG/APNG

在 `IEND` 前写入插件私有 ancillary chunk。

### WebP

在 RIFF 容器中写入插件自定义 chunk。

填充数据不会改变：

- 图片尺寸
- 可见像素
- 里图内容
- 动画 FPS
- 动画帧数
- 循环方式

---

# 输出目录

保存节点支持：

```text
自定义输出目录
```

留空：

```text
ComfyUI/output/
```

Windows 示例：

```text
C:\Images\Output
```

相对路径示例：

```text
cover_inner
```

最终文件仍保存到指定目录；节点前端预览使用单独的小型 PNG 预览文件。

---

# 旧工作流自动迁移

从旧版本升级到当前版本时，插件会在 ComfyUI 加载工作流之前自动迁移旧节点类型。

以下旧节点会自动转换：

```text
SaveCoverInnerWebPWithSourceWorkflow
    -> SaveCoverInnerOverlayMerged

SaveCoverInnerPngWithSourceWorkflow
    -> SaveCoverInnerOverlayMerged

ReadWebPInnerImage
    -> ReadInnerImage
```

旧 WebP 节点迁移后会自动设置：

```text
输出格式 = WEBP
```

旧 PNG 节点迁移后会自动设置：

```text
输出格式 = PNG
```

迁移过程会保留：

- 节点 ID
- 节点位置
- 节点尺寸
- 输入连接
- 输出连接
- mode / bypass 状态
- 自定义标题
- 输出路径
- 元数据来源
- WebP 质量
- 无损设置
- 发送兼容体积
- 表图占位颜色

当前版本后端只注册现行节点，旧节点不会出现在新增节点菜单中。

旧工作流加载并重新保存后，工作流中的节点类型会保存为当前节点类型。

---

# 推荐工作流

## 静态表图 + 静态里图

```text
Load Image（里图） ───────┐
                          ├─ Cover-Inner Overlay Merge
Load Image（表图，可选） ─┘
```

输出格式可选：

```text
PNG
WEBP
```

---

## 表图 + GIF / 动画

```text
GIF / IMAGE Batch ───────┐
                         ├─ Cover-Inner GIF Merge
Load Image（表图，可选） ─┘
```

默认：

```text
24 FPS
2304 KiB
```

---

## 读取里图

```text
插件生成的 PNG / WebP
          ↓
Read Inner Image
          ↓
IMAGE Batch
```

---

## 横向截面编辑

```text
Load Image
    ↓
Horizontal Band Editor
    ↓
IMAGE / MASK / RGBA
```

---

# 注意事项

## 表图与里图尺寸

表图会按照里图尺寸进行缩放裁剪。

最终输出尺寸以里图尺寸为准。

## IMAGE Batch

`IMAGE` 在 ComfyUI 中可以包含一个或多个批次帧。

- `Cover-Inner Overlay Merge` 只接受单张 IMAGE
- `Cover-Inner GIF Merge` 至少需要 2 帧 IMAGE Batch
- `Read Inner Image` 可以输出多帧 IMAGE Batch

## 透明图片

PNG/APNG 支持透明通道。

WebP 也以 RGBA 方式处理输入帧。

## 自定义输出目录预览

当最终文件保存到 ComfyUI 默认目录以外的位置时，插件会在默认 `output` 目录生成独立预览 PNG，以确保经典 UI 和 Nodes 2.0 可以正常显示节点预览。

---

# 目录说明

```text
ComfyUI-HorizontalBandEditor/
├─ __init__.py
├─ nodes.py
├─ README.md
├─ requirements.txt
├─ locales/
│  ├─ zh/
│  └─ zh-CN/
└─ web/
   └─ js/
      └─ horizontal_band_editor.js
```

---

# License

许可证信息见项目目录中的：

```text
LICENSE
```
