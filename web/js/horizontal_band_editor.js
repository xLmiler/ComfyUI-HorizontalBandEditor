import { app } from "../../scripts/app.js";
import { api } from "../../scripts/api.js";

const NODE_NAME = "HorizontalBandEditor";
const REGION_LABELS = [..."ABCDEFGHIJKL"];
const PREVIEW_MIN_HEIGHT = 220;
const PREVIEW_DEFAULT_WIDTH = 360;

function getWidget(node, ...names) {
    return node.widgets?.find((w) => names.includes(w.name));
}

function setWidgetValue(widget, value, node) {
    if (!widget) return;
    widget.value = value;
    try {
        widget.callback?.(value, app.canvas, node, [0, 0], {});
    } catch (_) {}
    node.graph?.setDirtyCanvas?.(true, true);
}

function chainWidgetCallback(widget, callback) {
    if (!widget || widget._hbeCallbackBound) return;
    widget._hbeCallbackBound = true;
    const original = widget.callback;
    widget.callback = function (...args) {
        const result = original?.apply(this, args);
        callback?.(widget.value);
        return result;
    };
}

function setWidgetHidden(widget, hidden) {
    if (!widget) return;
    const value = Boolean(hidden);

    // ComfyUI 新前端的布局核心直接检查 visibility.suppression.byExtension。
    // 优先写这里，经典 Canvas 与 Nodes 2.0 会共用同一套布局可见性。
    try {
        if (widget.visibility?.suppression) {
            widget.visibility.suppression.byExtension = value;
        }
    } catch (_) {}

    // 兼容旧前端。
    try { widget.hidden = value; } catch (_) {}
    try {
        widget.options ??= {};
        widget.options.hidden = value;
    } catch (_) {}
    try {
        if (widget._state?.options) widget._state.options.hidden = value;
    } catch (_) {}
}

function refreshWidgetLayout(node) {
    // Nodes 2.0 的 widget 列表是浅响应数组。动态修改可见性后，
    // 轻触数组尾部可确保 Vue 重新映射；顺序不会变化。
    try {
        const widgets = node.widgets;
        if (Array.isArray(widgets) && widgets.length) {
            const last = widgets.pop();
            if (last) widgets.push(last);
        }
    } catch (_) {}
    node._widgetSlotsDirty = true;
    node.graph?.setDirtyCanvas?.(true, true);
}

function fixMultilineWidgetHeight(widget, height = 88) {
    if (!widget || widget._hbeFixedMultilineHeight) return;
    widget._hbeFixedMultilineHeight = true;
    try {
        widget.options ??= {};
        widget.options.getMinHeight = () => height;
        widget.options.getMaxHeight = () => height;
        widget.options.getHeight = () => height;
    } catch (_) {}
}

function clamp(value, min, max) {
    return Math.max(min, Math.min(max, value));
}

function normalizeHexColor(value, fallback = "#FFFFFF") {
    const text = String(value ?? "").trim();
    const full = text.match(/^#?([0-9a-fA-F]{6})$/);
    if (full) return `#${full[1].toUpperCase()}`;
    const short = text.match(/^#?([0-9a-fA-F]{3})$/);
    if (short) {
        const s = short[1].toUpperCase();
        return `#${s[0]}${s[0]}${s[1]}${s[1]}${s[2]}${s[2]}`;
    }
    if (fallback && String(fallback).trim() !== String(value ?? "").trim()) {
        return normalizeHexColor(fallback, "#FFFFFF");
    }
    return "#FFFFFF";
}

function moveWidgetAfter(node, widget, afterWidget) {
    try {
        const list = node?.widgets;
        if (!Array.isArray(list) || !widget || !afterWidget || widget === afterWidget) return;
        const from = list.indexOf(widget);
        const after = list.indexOf(afterWidget);
        if (from < 0 || after < 0) return;
        list.splice(from, 1);
        const target = list.indexOf(afterWidget);
        list.splice(target + 1, 0, widget);
    } catch (_) {}
}

function createColorPickerWidget(node, sourceWidget, label, fallback = "#FFFFFF") {
    if (!node || !sourceWidget) return null;
    if (sourceWidget._hbeColorWidget) return sourceWidget._hbeColorWidget;

    const root = document.createElement("div");
    root.style.width = "100%";
    root.style.boxSizing = "border-box";
    root.style.display = "flex";
    root.style.alignItems = "center";
    root.style.gap = "8px";
    root.style.padding = "2px 0";

    const caption = document.createElement("div");
    caption.textContent = label;
    caption.style.flex = "0 0 86px";
    caption.style.fontSize = "12px";
    caption.style.opacity = "0.9";
    caption.style.whiteSpace = "nowrap";

    const colorInput = document.createElement("input");
    colorInput.type = "color";
    colorInput.style.flex = "0 0 42px";
    colorInput.style.width = "42px";
    colorInput.style.height = "28px";
    colorInput.style.padding = "0";
    colorInput.style.border = "1px solid rgba(255,255,255,0.12)";
    colorInput.style.borderRadius = "6px";
    colorInput.style.background = "transparent";
    colorInput.style.cursor = "pointer";

    const textInput = document.createElement("input");
    textInput.type = "text";
    textInput.placeholder = "#FFFFFF";
    textInput.style.flex = "1 1 auto";
    textInput.style.minWidth = "0";
    textInput.style.height = "28px";
    textInput.style.boxSizing = "border-box";
    textInput.style.padding = "4px 8px";
    textInput.style.borderRadius = "6px";
    textInput.style.border = "1px solid rgba(255,255,255,0.12)";
    textInput.style.background = "var(--comfy-input-bg, rgba(0,0,0,0.28))";
    textInput.style.color = "var(--input-text, inherit)";

    root.append(caption, colorInput, textInput);

    const syncFromValue = (value, commit = false) => {
        const normalized = normalizeHexColor(value, fallback);
        if (colorInput.value !== normalized) colorInput.value = normalized;
        if (textInput.value !== normalized) textInput.value = normalized;
        if (commit && sourceWidget.value !== normalized) setWidgetValue(sourceWidget, normalized, node);
    };

    colorInput.addEventListener("input", () => syncFromValue(colorInput.value, true));
    textInput.addEventListener("change", () => syncFromValue(textInput.value, true));
    textInput.addEventListener("blur", () => syncFromValue(textInput.value, true));
    textInput.addEventListener("keydown", (event) => {
        if (event.key === "Enter") {
            syncFromValue(textInput.value, true);
            textInput.blur();
        }
    });

    chainWidgetCallback(sourceWidget, () => syncFromValue(sourceWidget.value, false));

    const widget = node.addDOMWidget(label, `hbe_color_${label}`, root, {
        serialize: false,
        hideOnZoom: false,
        getMinHeight: () => 34,
        getMaxHeight: () => 34,
        getHeight: () => 34,
    });
    widget.serialize = false;
    sourceWidget._hbeColorWidget = widget;
    widget._hbeSourceWidget = sourceWidget;

    moveWidgetAfter(node, widget, sourceWidget);
    setWidgetHidden(sourceWidget, true);
    syncFromValue(sourceWidget.value, false);
    return widget;
}


function getConnectedLoadImageByInputNames(node, inputNames) {
    if (!node?.inputs?.length || !app.graph) return null;
    for (const input of node.inputs) {
        if (!input || !inputNames.includes(input.name) || input.link == null) continue;
        const link = app.graph.links?.[input.link];
        const upstream = link?.origin_id != null ? app.graph.getNodeById?.(link.origin_id) : null;
        if (!upstream) continue;
        const imageWidget = upstream.widgets?.find((w) => w.name === "image");
        if (imageWidget?.value) {
            return {
                filename: String(imageWidget.value),
                title: upstream.title || upstream.type || "加载图像",
                upstream,
                imageWidget,
            };
        }
    }
    return null;
}

function getConnectedLoadImage(node) {
    return getConnectedLoadImageByInputNames(node, ["输入图像", "input_image"]);
}

function makeViewUrl(filename) {
    const params = new URLSearchParams();
    params.set("filename", String(filename || ""));
    params.set("type", "input");
    params.set("subfolder", "");
    return api.apiURL(`/view?${params.toString()}`);
}

function installNativeVisibility(node) {
    const countW = getWidget(node, "截面数量", "region_count");
    const editW = getWidget(node, "编辑截面", "active_region");
    const enableTextW = getWidget(node, "启用文字面板", "text_panel_enabled");
    const bgModeW = getWidget(node, "面板背景", "panel_background");
    const bgColorW = getWidget(node, "背景颜色", "background_color");
    const textContentW = getWidget(node, "文字内容", "text");
    const textColorW = getWidget(node, "文字颜色", "text_color");
    const sourceFileCacheW = getWidget(node, "源图文件名缓存", "source_image_filename_cache");

    const bgColorPickerW = createColorPickerWidget(node, bgColorW, "背景颜色", "#FFFFFF");
    const textColorPickerW = createColorPickerWidget(node, textColorW, "文字颜色", "#000000");

    // multiline STRING 本身也是 growable DOM widget。若不限制高度，开启文字面板后
    // 它会和编辑预览共同瓜分节点拉伸出来的 freeWidgetSpace。
    // 固定文字编辑框高度，让底部预览成为唯一的自由增长区域。
    fixMultilineWidgetHeight(textContentW, 88);

    const textWidgets = [
        bgModeW,
        bgColorPickerW,
        textContentW,
        textColorPickerW,
        getWidget(node, "字体名称或路径", "font_name_or_path"),
        getWidget(node, "字号", "font_size"),
        getWidget(node, "内边距", "padding"),
        getWidget(node, "行距", "line_spacing"),
        getWidget(node, "水平对齐", "horizontal_align"),
        getWidget(node, "垂直对齐", "vertical_align"),
    ].filter(Boolean);

    const regionWidgets = new Map();
    for (const label of REGION_LABELS) {
        regionWidgets.set(label, {
            top: getWidget(node, `截面${label}上边界(px)`, label === "A" ? "选区上边界(px)" : `region_${label.toLowerCase()}_top`),
            bottom: getWidget(node, `截面${label}下边界(px)`, label === "A" ? "选区下边界(px)" : `region_${label.toLowerCase()}_bottom`),
        });
    }

    let lastCount = clamp(Number(countW?.value ?? 1), 1, REGION_LABELS.length);

    function refresh() {
        let count = clamp(Number(countW?.value ?? 1), 1, REGION_LABELS.length);
        const currentLabel = REGION_LABELS.includes(String(editW?.value)) ? String(editW.value) : "A";
        let currentIndex = REGION_LABELS.indexOf(currentLabel);
        if (currentIndex < 0) currentIndex = 0;

        if (currentIndex >= count) {
            currentIndex = count - 1;
            setWidgetValue(editW, REGION_LABELS[currentIndex], node);
        }

        for (let i = 0; i < REGION_LABELS.length; i++) {
            const pair = regionWidgets.get(REGION_LABELS[i]);
            const show = i === currentIndex && i < count;
            setWidgetHidden(pair?.top, !show);
            setWidgetHidden(pair?.bottom, !show);
        }

        const textEnabled = Boolean(enableTextW?.value);
        for (const widget of textWidgets) setWidgetHidden(widget, !textEnabled);
        if (textEnabled && String(bgModeW?.value || "纯色") === "透明") {
            setWidgetHidden(bgColorPickerW, true);
        }

        // 技术缓存字段始终隐藏，由前端自动维护。
        setWidgetHidden(sourceFileCacheW, true);

        refreshWidgetLayout(node);
        requestAnimationFrame(() => {
            // 重新安排固定 widget 与唯一的 growable 预览。
            try { node.arrange?.(); } catch (_) {}
            node._hbeDrawPreview?.();
        });
    }

    chainWidgetCallback(countW, () => {
        const newCount = clamp(Number(countW?.value ?? 1), 1, REGION_LABELS.length);
        if (newCount > lastCount) {
            setWidgetValue(editW, REGION_LABELS[newCount - 1], node);
        } else if (REGION_LABELS.indexOf(String(editW?.value || "A")) >= newCount) {
            setWidgetValue(editW, REGION_LABELS[newCount - 1], node);
        }
        lastCount = newCount;
        refresh();
    });

    chainWidgetCallback(editW, () => {
        const idx = REGION_LABELS.indexOf(String(editW?.value || "A"));
        const count = clamp(Number(countW?.value ?? 1), 1, REGION_LABELS.length);
        if (idx >= count) setWidgetValue(countW, idx + 1, node);
        refresh();
    });

    chainWidgetCallback(enableTextW, refresh);
    chainWidgetCallback(bgModeW, refresh);

    for (const pair of regionWidgets.values()) {
        chainWidgetCallback(pair.top, () => node._hbeDrawPreview?.());
        chainWidgetCallback(pair.bottom, () => node._hbeDrawPreview?.());
    }

    node._hbeRefreshVisibility = refresh;
    node._hbeRegionWidgets = regionWidgets;
    node._hbeCountWidget = countW;
    node._hbeEditWidget = editW;
    node._hbeSourceFileCacheWidget = sourceFileCacheW;
    refresh();
}

function addPreviewWidget(node) {
    if (node._hbePreviewWidget) return;

    const root = document.createElement("div");
    root.style.width = "100%";
    root.style.height = "100%";
    root.style.minHeight = `${PREVIEW_MIN_HEIGHT}px`;
    root.style.boxSizing = "border-box";
    root.style.padding = "6px";
    root.style.display = "flex";
    root.style.flexDirection = "column";
    root.style.gap = "5px";
    root.style.overflow = "hidden";

    const header = document.createElement("div");
    header.style.display = "flex";
    header.style.justifyContent = "space-between";
    header.style.alignItems = "center";
    header.style.gap = "8px";
    header.style.fontSize = "11px";
    header.style.opacity = "0.82";
    header.style.flex = "0 0 auto";

    const title = document.createElement("span");
    title.textContent = "编辑预览";
    title.style.fontWeight = "600";
    const status = document.createElement("span");
    status.textContent = "等待输入图像";
    status.style.overflow = "hidden";
    status.style.textOverflow = "ellipsis";
    status.style.whiteSpace = "nowrap";
    header.append(title, status);

    const canvas = document.createElement("canvas");
    canvas.width = 640;
    canvas.height = 360;
    canvas.style.width = "100%";
    canvas.style.height = "100%";
    canvas.style.minHeight = "0";
    canvas.style.flex = "1 1 auto";
    canvas.style.display = "block";
    canvas.style.borderRadius = "6px";
    canvas.style.border = "1px solid rgba(255,255,255,0.15)";
    canvas.style.background = "repeating-conic-gradient(#292929 0 25%, #343434 0 50%) 0 / 16px 16px";
    canvas.style.cursor = "crosshair";
    canvas.style.touchAction = "none";

    const hint = document.createElement("div");
    hint.textContent = "拖拽空白位置重设当前截面；拖动边缘调高低；拖动内部可整体移动；点击其他截面可切换。";
    hint.title = hint.textContent;
    hint.style.fontSize = "10px";
    hint.style.opacity = "0.64";
    hint.style.lineHeight = "1.2";
    hint.style.flex = "0 0 auto";
    hint.style.whiteSpace = "nowrap";
    hint.style.overflow = "hidden";
    hint.style.textOverflow = "ellipsis";

    root.append(header, canvas, hint);

    const state = {
        img: null,
        filename: null,
        loadToken: 0,
        displayRect: { x: 0, y: 0, w: 1, h: 1 },
        dragMode: null,
        dragRegionIndex: 0,
        anchorY: 0,
        originalTop: 0,
        originalBottom: 1,
    };


    function getCount() {
        return clamp(Number(node._hbeCountWidget?.value ?? 1), 1, REGION_LABELS.length);
    }

    function getSelectedIndex() {
        const idx = REGION_LABELS.indexOf(String(node._hbeEditWidget?.value || "A"));
        return clamp(idx < 0 ? 0 : idx, 0, getCount() - 1);
    }

    function getPair(index) {
        return node._hbeRegionWidgets?.get(REGION_LABELS[index]);
    }

    function getRegion(index) {
        const pair = getPair(index);
        const h = state.img?.naturalHeight || 1;
        let top = clamp(Math.round(Number(pair?.top?.value ?? 0)), 0, Math.max(0, h - 1));
        let bottom = clamp(Math.round(Number(pair?.bottom?.value ?? 0)), 0, h);
        return { top, bottom, valid: bottom > top };
    }

    function setRegion(index, top, bottom) {
        const pair = getPair(index);
        const h = state.img?.naturalHeight || 1;
        top = clamp(Math.round(top), 0, Math.max(0, h - 1));
        bottom = clamp(Math.round(bottom), 0, h);
        if (bottom <= top) bottom = Math.min(h, top + 1);
        if (bottom <= top) top = Math.max(0, bottom - 1);
        setWidgetValue(pair?.top, top, node);
        setWidgetValue(pair?.bottom, bottom, node);
        draw();
    }

    function selectRegion(index) {
        index = clamp(index, 0, getCount() - 1);
        setWidgetValue(node._hbeEditWidget, REGION_LABELS[index], node);
        node._hbeRefreshVisibility?.();
    }

    function resizeCanvas() {
        const rect = canvas.getBoundingClientRect();
        const cssW = Math.max(160, Math.floor(rect.width || 1));
        const cssH = Math.max(120, Math.floor(rect.height || 1));
        const dpr = Math.max(1, window.devicePixelRatio || 1);
        const pixelW = Math.max(1, Math.floor(cssW * dpr));
        const pixelH = Math.max(1, Math.floor(cssH * dpr));
        if (canvas.width !== pixelW || canvas.height !== pixelH) {
            canvas.width = pixelW;
            canvas.height = pixelH;
        }
        return { cssW, cssH, dpr };
    }

    function draw() {
        const { cssW, cssH, dpr } = resizeCanvas();
        const ctx = canvas.getContext("2d");
        ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
        ctx.clearRect(0, 0, cssW, cssH);

        if (!state.img?.complete || !state.img.naturalWidth) {
            ctx.fillStyle = "rgba(255,255,255,0.72)";
            ctx.font = "12px sans-serif";
            ctx.textAlign = "center";
            ctx.textBaseline = "middle";
            ctx.fillText("请直接连接 ComfyUI 的“加载图像”节点", cssW / 2, cssH / 2);
            state.displayRect = { x: 0, y: 0, w: cssW, h: cssH };
            return;
        }

        // 完全使用 ComfyUI 原生预览的思路：
        // widget 获得多少实际空间，图片就在这个空间内等比例 contain。
        // 因此节点横向/纵向缩放时，经典 UI 与 Nodes 2.0 都会同步改变图片尺寸。
        const scale = Math.min(cssW / state.img.naturalWidth, cssH / state.img.naturalHeight);

        const dw = state.img.naturalWidth * scale;
        const dh = state.img.naturalHeight * scale;
        const dx = (cssW - dw) / 2;
        const dy = (cssH - dh) / 2;
        state.displayRect = { x: dx, y: dy, w: dw, h: dh };
        ctx.save();
        ctx.beginPath();
        ctx.rect(0, 0, cssW, cssH);
        ctx.clip();
        ctx.drawImage(state.img, dx, dy, dw, dh);
        ctx.restore();

        const count = getCount();
        const selected = getSelectedIndex();
        for (let i = 0; i < count; i++) {
            const region = getRegion(i);
            if (!region.valid) continue;
            const y1 = dy + (region.top / state.img.naturalHeight) * dh;
            const y2 = dy + (region.bottom / state.img.naturalHeight) * dh;
            const active = i === selected;

            ctx.fillStyle = active ? "rgba(76,166,255,0.28)" : "rgba(255,190,70,0.18)";
            ctx.fillRect(dx, y1, dw, Math.max(1, y2 - y1));
            ctx.strokeStyle = active ? "rgba(105,195,255,0.98)" : "rgba(255,205,105,0.88)";
            ctx.lineWidth = active ? 2 : 1;
            ctx.strokeRect(dx + 0.5, y1, Math.max(1, dw - 1), Math.max(1, y2 - y1));

            const label = REGION_LABELS[i];
            ctx.font = "bold 11px sans-serif";
            ctx.textAlign = "left";
            ctx.textBaseline = "top";
            ctx.fillStyle = "rgba(0,0,0,0.72)";
            ctx.fillRect(dx + 4, y1 + 4, 22, 18);
            ctx.fillStyle = "white";
            ctx.fillText(label, dx + 11, y1 + 7);
        }

        const current = getRegion(selected);
        status.textContent = current.valid
            ? `截面 ${REGION_LABELS[selected]} · ${current.top}–${current.bottom}px`
            : `截面 ${REGION_LABELS[selected]} · 尚未设置`;
    }

    function clientYToImageY(clientY) {
        if (!state.img?.naturalHeight) return 0;
        const rect = canvas.getBoundingClientRect();
        const y = clientY - rect.top;
        const dr = state.displayRect;
        const local = clamp(y, dr.y, dr.y + dr.h);
        const t = dr.h > 0 ? (local - dr.y) / dr.h : 0;
        return Math.round(t * state.img.naturalHeight);
    }

    function imageTolerancePx() {
        const dr = state.displayRect;
        const h = state.img?.naturalHeight || 1;
        return Math.max(2, Math.round((8 / Math.max(1, dr.h)) * h));
    }

    canvas.addEventListener("pointerdown", (event) => {
        if (!state.img?.naturalHeight) return;
        canvas.setPointerCapture?.(event.pointerId);
        const y = clientYToImageY(event.clientY);
        const tol = imageTolerancePx();
        const count = getCount();
        let hit = -1;
        let hitMode = null;

        for (let i = count - 1; i >= 0; i--) {
            const r = getRegion(i);
            if (!r.valid) continue;
            if (Math.abs(y - r.top) <= tol) { hit = i; hitMode = "top"; break; }
            if (Math.abs(y - r.bottom) <= tol) { hit = i; hitMode = "bottom"; break; }
            if (y > r.top && y < r.bottom) { hit = i; hitMode = "move"; break; }
        }

        if (hit >= 0) {
            selectRegion(hit);
            const r = getRegion(hit);
            state.dragRegionIndex = hit;
            state.dragMode = hitMode;
            state.anchorY = y;
            state.originalTop = r.top;
            state.originalBottom = r.bottom;
        } else {
            const idx = getSelectedIndex();
            state.dragRegionIndex = idx;
            state.dragMode = "new";
            state.anchorY = y;
            state.originalTop = y;
            state.originalBottom = Math.min(state.img.naturalHeight, y + 1);
            setRegion(idx, y, Math.min(state.img.naturalHeight, y + 1));
        }
        event.preventDefault();
    });

    canvas.addEventListener("pointermove", (event) => {
        if (!state.dragMode || !state.img?.naturalHeight) return;
        const y = clientYToImageY(event.clientY);
        const idx = state.dragRegionIndex;
        const h = state.img.naturalHeight;

        if (state.dragMode === "new") {
            setRegion(idx, Math.min(state.anchorY, y), Math.max(state.anchorY + 1, y));
        } else if (state.dragMode === "top") {
            const r = getRegion(idx);
            setRegion(idx, Math.min(y, r.bottom - 1), r.bottom);
        } else if (state.dragMode === "bottom") {
            const r = getRegion(idx);
            setRegion(idx, r.top, Math.max(r.top + 1, y));
        } else if (state.dragMode === "move") {
            const delta = y - state.anchorY;
            const regionHeight = state.originalBottom - state.originalTop;
            let top = state.originalTop + delta;
            top = clamp(top, 0, Math.max(0, h - regionHeight));
            setRegion(idx, top, top + regionHeight);
        }
        event.preventDefault();
    });

    function endDrag(event) {
        if (!state.dragMode) return;
        state.dragMode = null;
        try { canvas.releasePointerCapture?.(event.pointerId); } catch (_) {}
        event.preventDefault();
    }
    canvas.addEventListener("pointerup", endDrag);
    canvas.addEventListener("pointercancel", endDrag);


    function ensureSource(force = false) {
        const connected = getConnectedLoadImage(node);
        const cacheW = node._hbeSourceFileCacheWidget;

        if (!connected?.filename) {
            if (state.filename !== null) {
                state.filename = null;
                state.img = null;
                status.textContent = "未检测到直接连接的加载图像";
                if (cacheW) setWidgetValue(cacheW, "", node);
                draw();
            }
            return;
        }
        if (cacheW && cacheW.value !== connected.filename) setWidgetValue(cacheW, connected.filename, node);
        if (!force && connected.filename === state.filename && state.img) return;

        state.filename = connected.filename;
        const token = ++state.loadToken;
        status.textContent = `加载预览：${connected.filename}`;
        const img = new Image();
        img.onload = () => {
            if (token !== state.loadToken) return;
            state.img = img;
            draw();
        };
        img.onerror = () => {
            if (token !== state.loadToken) return;
            state.img = null;
            status.textContent = "预览加载失败；后端处理仍可正常执行";
            draw();
        };
        img.src = `${makeViewUrl(connected.filename)}&rand=${Date.now()}`;
    }

    const previewWidget = node.addDOMWidget("编辑预览", "horizontal_band_preview", root, {
        serialize: false,
        hideOnZoom: false,
        margin: 6,
        // 与 ComfyUI 原生 ImagePreviewWidget 相同：只声明最小高度。
        // 不声明固定高度/最大高度，也不从 node.size 反推自身高度。
        // 经典 UI 与 Nodes 2.0 都会把节点剩余高度分配给这个 widget。
        getMinHeight: () => PREVIEW_MIN_HEIGHT,
        afterResize: () => requestAnimationFrame(draw),
        onDraw: () => ensureSource(false),
    });
    previewWidget.serialize = false;
    node._hbePreviewWidget = previewWidget;
    node._hbeDrawPreview = draw;
    node._hbeEnsurePreviewSource = ensureSource;

    const resizeObserver = new ResizeObserver(() => requestAnimationFrame(draw));
    resizeObserver.observe(root);
    node._hbePreviewCleanup = () => resizeObserver.disconnect();

    requestAnimationFrame(() => {
        ensureSource(true);
        draw();
    });
}



function _hbeReadUint16(view, offset, littleEndian) {
    if (offset < 0 || offset + 2 > view.byteLength) throw new Error("EXIF uint16 越界");
    return view.getUint16(offset, littleEndian);
}

function _hbeReadUint32(view, offset, littleEndian) {
    if (offset < 0 || offset + 4 > view.byteLength) throw new Error("EXIF uint32 越界");
    return view.getUint32(offset, littleEndian);
}

function _hbeParseExifKeyValue(exifBytes) {
    const result = {};
    let bytes = exifBytes;
    if (bytes.length >= 6 && String.fromCharCode(...bytes.slice(0, 6)) === "Exif\0\0") {
        bytes = bytes.slice(6);
    }
    if (bytes.length < 8) return result;

    const view = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength);
    const order = String.fromCharCode(bytes[0], bytes[1]);
    const little = order === "II";
    if (!little && order !== "MM") return result;

    const ifdOffset = _hbeReadUint32(view, 4, little);
    if (ifdOffset + 2 > bytes.length) return result;
    const count = _hbeReadUint16(view, ifdOffset, little);
    const decoder = new TextDecoder("utf-8");

    for (let i = 0; i < count; i++) {
        const entry = ifdOffset + 2 + i * 12;
        if (entry + 12 > bytes.length) break;
        const type = _hbeReadUint16(view, entry + 2, little);
        const numValues = _hbeReadUint32(view, entry + 4, little);
        if (type !== 2 || numValues <= 1) continue;

        let raw;
        if (numValues <= 4) {
            raw = bytes.slice(entry + 8, entry + 8 + numValues - 1);
        } else {
            const valueOffset = _hbeReadUint32(view, entry + 8, little);
            if (valueOffset + numValues - 1 > bytes.length) continue;
            raw = bytes.slice(valueOffset, valueOffset + numValues - 1);
        }
        const value = decoder.decode(raw);
        const colon = value.indexOf(":");
        if (colon <= 0) continue;
        result[value.slice(0, colon)] = value.slice(colon + 1);
    }
    return result;
}

async function _hbeReadWebpMetadata(file) {
    const buffer = await file.arrayBuffer();
    const bytes = new Uint8Array(buffer);
    if (bytes.length < 12) return {};
    if (String.fromCharCode(...bytes.slice(0, 4)) !== "RIFF" || String.fromCharCode(...bytes.slice(8, 12)) !== "WEBP") {
        return {};
    }

    const view = new DataView(buffer);
    let offset = 12;
    while (offset + 8 <= bytes.length) {
        const chunkType = String.fromCharCode(...bytes.slice(offset, offset + 4));
        const chunkLength = view.getUint32(offset + 4, true);
        const dataStart = offset + 8;
        const dataEnd = dataStart + chunkLength;
        if (dataEnd > bytes.length) break;
        if (chunkType === "EXIF") {
            return _hbeParseExifKeyValue(bytes.slice(dataStart, dataEnd));
        }
        // RIFF/WebP 规范要求奇数长度 chunk 额外补 1 byte。
        offset = dataEnd + (chunkLength % 2);
    }
    return {};
}

function installWebpWorkflowDropCompatibility() {
    if (app._hbeWebpHandleFilePatched || typeof app.handleFile !== "function") return;
    app._hbeWebpHandleFilePatched = true;
    const originalHandleFile = app.handleFile;

    app.handleFile = async function (file, openSource, options) {
        const name = String(file?.name || "");
        const isWebp = file?.type === "image/webp" || name.toLowerCase().endsWith(".webp");
        if (isWebp) {
            try {
                const metadata = await _hbeReadWebpMetadata(file);
                const workflowText = metadata.workflow || metadata.Workflow;
                if (workflowText) {
                    const workflow = typeof workflowText === "string" ? JSON.parse(workflowText) : workflowText;
                    const fileName = name.replace(/\.\w+$/, "");
                    // 只在原生 WebP workflow 读取失败风险最大的场景介入。
                    // loadGraphData 是 ComfyUI 自己用于恢复完整 workflow 的入口。
                    await this.loadGraphData(workflow, true, true, fileName, { openSource });
                    return;
                }
            } catch (error) {
                console.warn("[ComfyUI-HorizontalBandEditor] WebP workflow 兼容读取失败，回退 ComfyUI 原生处理：", error);
            }
        }
        return originalHandleFile.call(this, file, openSource, options);
    };
}

app.registerExtension({
    name: "HorizontalBandEditor.NativeUI",

    async setup() {
        // 当前某些 ComfyUI frontend 版本对 WebP workflow 拖入仍存在兼容问题。
        // 这里只补 WebP 文件读取，不影响 PNG/JSON/普通图片的原生处理。
        installWebpWorkflowDropCompatibility();
    },

    async nodeCreated(node) {
        const comfyClass = node?.comfyClass || node?.type;
        if (comfyClass !== NODE_NAME && comfyClass !== COVER_WEBP_NODE_NAME) return;
        if (node._hbeInstalled) return;
        node._hbeInstalled = true;

        if (comfyClass === NODE_NAME) {
            installNativeVisibility(node);
            addPreviewWidget(node);
        } else if (comfyClass === COVER_WEBP_NODE_NAME) {
            installCoverInnerWebPNode(node);
        }

        const originalConnectionsChange = node.onConnectionsChange;
        node.onConnectionsChange = function (...args) {
            const result = originalConnectionsChange?.apply(this, args);
            requestAnimationFrame(() => {
                this._hbeEnsurePreviewSource?.(true);
                this._hbeCoverInnerRefresh?.();
            });
            return result;
        };

        const originalConfigure = node.onConfigure;
        node.onConfigure = function (...args) {
            const result = originalConfigure?.apply(this, args);
            requestAnimationFrame(() => {
                this._hbeRefreshVisibility?.();
                this._hbeEnsurePreviewSource?.(true);
                this._hbeCoverInnerRefresh?.();
                this._hbeDrawPreview?.();
            });
            return result;
        };

        const originalResize = node.onResize;
        node.onResize = function (...args) {
            const result = originalResize?.apply(this, args);
            requestAnimationFrame(() => {
                this._hbeDrawPreview?.();
                this._hbeCoverInnerRefresh?.();
            });
            return result;
        };

        const originalRemoved = node.onRemoved;
        node.onRemoved = function (...args) {
            this._hbePreviewCleanup?.();
            return originalRemoved?.apply(this, args);
        };

        requestAnimationFrame(() => {
            if (comfyClass === NODE_NAME) {
                const width = Math.max(Number(node.size?.[0] || PREVIEW_DEFAULT_WIDTH), PREVIEW_DEFAULT_WIDTH);
                const height = Number(node.size?.[1] || 0);
                if (node.size && node.size[0] < width) {
                    node.setSize?.([width, height]);
                }
            }
            node._hbeEnsurePreviewSource?.(true);
            node._hbeCoverInnerRefresh?.();
            node._hbeDrawPreview?.();
        });
    },
});


const COVER_WEBP_NODE_NAME = "SaveCoverInnerWebPWithSourceWorkflow";

function installCoverInnerWebPNode(node) {
    const placeholderColorW = getWidget(node, "表图占位颜色", "表图占位颜色");
    const placeholderColorPickerW = createColorPickerWidget(node, placeholderColorW, "表图占位颜色", "#FFFFFF");
    const innerSourceFileW = getWidget(node, "里图文件名缓存", "inner_source_image_filename_cache");

    function refresh() {
        setWidgetHidden(innerSourceFileW, true);
        setWidgetHidden(placeholderColorW, true);
        setWidgetHidden(placeholderColorPickerW, false);

        const innerConnected = getConnectedLoadImageByInputNames(node, ["里图", "inner_image"]);
        if (innerSourceFileW) {
            const nextValue = innerConnected?.filename || "";
            if (innerSourceFileW.value !== nextValue) setWidgetValue(innerSourceFileW, nextValue, node);
        }

        refreshWidgetLayout(node);
        requestAnimationFrame(() => {
            try { node.arrange?.(); } catch (_) {}
            node.graph?.setDirtyCanvas?.(true, true);
        });
    }

    node._hbeCoverInnerRefresh = refresh;
    refresh();
}
