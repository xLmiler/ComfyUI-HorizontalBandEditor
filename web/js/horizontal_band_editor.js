import { app } from "../../scripts/app.js";
import { api } from "../../scripts/api.js";

const NODE_NAME = "HorizontalBandEditor";
const REGION_LABELS = [..."ABCDEFGHIJKL"];
const PREVIEW_MIN_HEIGHT = 320;
const PREVIEW_MAX_HEIGHT = 960;
const PREVIEW_DEFAULT_WIDTH = 360;
const CLASSIC_HEIGHT_ZOOM_POWER = 1.0;

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
    try { widget.hidden = Boolean(hidden); } catch (_) {}
    try {
        widget.options ??= {};
        widget.options.hidden = Boolean(hidden);
    } catch (_) {}
}

function clamp(value, min, max) {
    return Math.max(min, Math.min(max, value));
}

function isNodes20Enabled() {
    try {
        const v = app.extensionManager?.setting?.get?.("Comfy.VueNodes.Enabled");
        if (typeof v === "boolean") return v;
    } catch (_) {}
    try {
        const v = app.ui?.settings?.getSettingValue?.("Comfy.VueNodes.Enabled");
        if (typeof v === "boolean") return v;
    } catch (_) {}
    return false;
}

function getConnectedLoadImage(node) {
    if (!node?.inputs?.length || !app.graph) return null;
    for (const input of node.inputs) {
        if (!input || !["输入图像", "input_image"].includes(input.name) || input.link == null) continue;
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
    const sourceFileCacheW = getWidget(node, "源图文件名缓存", "source_image_filename_cache");

    const textWidgets = [
        bgModeW,
        bgColorW,
        getWidget(node, "文字内容", "text"),
        getWidget(node, "文字颜色", "text_color"),
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
            setWidgetHidden(bgColorW, true);
        }

        // 技术缓存字段始终隐藏，由前端自动维护。
        setWidgetHidden(sourceFileCacheW, true);

        node._hbeRecomputeBaseHeight?.();
        node._hbeSyncPreviewHeight?.();
        node.graph?.setDirtyCanvas?.(true, true);
        requestAnimationFrame(() => node._hbeDrawPreview?.());
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
        nodes20: isNodes20Enabled(),
        previewHeight: PREVIEW_MIN_HEIGHT,
        baseHeight: 0,
    };

    function applyRootHeight() {
        root.style.height = `${state.previewHeight}px`;
        root.style.maxHeight = `${state.previewHeight}px`;
        root.style.minHeight = `${state.previewHeight}px`;
    }

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

        // Nodes 2.0 使用标准 contain，确保布局稳定。
        // 经典 UI 下，节点纵向拉高代表“放大编辑视图”：
        // 在基础 contain 比例上乘以预览高度相对最小高度的缩放因子。
        // 这样纵向拉伸时图片也会等比例放大；如果宽度超过视口，则由 canvas 自然裁切，
        // 不做非等比拉伸，因此截面坐标映射仍然准确。
        const containScale = Math.min(cssW / state.img.naturalWidth, cssH / state.img.naturalHeight);
        let scale = containScale;
        if (!state.nodes20) {
            // 以“最小预览高度”时的 contain 比例作为基准，随后严格按用户拉高的比例放大。
            // 不能再使用当前 cssH 的 containScale 乘高度倍率，否则竖图会发生二次放大。
            const baseContainScale = Math.min(
                cssW / state.img.naturalWidth,
                PREVIEW_MIN_HEIGHT / state.img.naturalHeight
            );
            const heightZoom = Math.max(1, Math.pow(state.previewHeight / PREVIEW_MIN_HEIGHT, CLASSIC_HEIGHT_ZOOM_POWER));
            scale = baseContainScale * heightZoom;
        }

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

    function recomputeBaseHeight() {
        try {
            const computed = node.computeSize?.();
            const total = Array.isArray(computed) ? Number(computed[1] || 0) : 0;
            state.baseHeight = Math.max(0, total - state.previewHeight);
        } catch (_) {
            state.baseHeight = Math.max(0, state.baseHeight || 0);
        }
    }

    function syncPreviewHeight() {
        state.nodes20 = isNodes20Enabled();
        let target = PREVIEW_MIN_HEIGHT;

        if (!state.nodes20) {
            const nodeHeight = Number(node.size?.[1] || 0);
            if (nodeHeight > 0 && state.baseHeight > 0) {
                target = clamp(nodeHeight - state.baseHeight, PREVIEW_MIN_HEIGHT, PREVIEW_MAX_HEIGHT);
            }
        }

        const changed = target !== state.previewHeight;
        state.previewHeight = target;
        applyRootHeight();
        if (changed) {
            node.graph?.setDirtyCanvas?.(true, true);
            requestAnimationFrame(draw);
        }
    }

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

    node._hbeRecomputeBaseHeight = recomputeBaseHeight;
    node._hbeSyncPreviewHeight = syncPreviewHeight;

    applyRootHeight();

    const previewWidget = node.addDOMWidget("编辑预览", "horizontal_band_preview", root, {
        serialize: false,
        hideOnZoom: false,
        margin: 6,
        getHeight: () => state.previewHeight,
        getMinHeight: () => state.previewHeight,
        getMaxHeight: () => state.previewHeight,
        afterResize: () => {
            syncPreviewHeight();
            requestAnimationFrame(draw);
        },
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
        recomputeBaseHeight();
        syncPreviewHeight();
        ensureSource(true);
        draw();
    });
}

app.registerExtension({
    name: "HorizontalBandEditor.NativeUI",

    async nodeCreated(node) {
        if (node?.comfyClass !== NODE_NAME && node?.type !== NODE_NAME) return;
        if (node._hbeInstalled) return;
        node._hbeInstalled = true;

        installNativeVisibility(node);
        addPreviewWidget(node);

        const originalConnectionsChange = node.onConnectionsChange;
        node.onConnectionsChange = function (...args) {
            const result = originalConnectionsChange?.apply(this, args);
            requestAnimationFrame(() => this._hbeEnsurePreviewSource?.(true));
            return result;
        };

        const originalConfigure = node.onConfigure;
        node.onConfigure = function (...args) {
            const result = originalConfigure?.apply(this, args);
            requestAnimationFrame(() => {
                this._hbeRefreshVisibility?.();
                this._hbeEnsurePreviewSource?.(true);
                this._hbeRecomputeBaseHeight?.();
                this._hbeSyncPreviewHeight?.();
                this._hbeDrawPreview?.();
            });
            return result;
        };

        const originalResize = node.onResize;
        node.onResize = function (...args) {
            const result = originalResize?.apply(this, args);
            requestAnimationFrame(() => {
                this._hbeSyncPreviewHeight?.();
                this._hbeDrawPreview?.();
            });
            return result;
        };

        const originalRemoved = node.onRemoved;
        node.onRemoved = function (...args) {
            this._hbePreviewCleanup?.();
            return originalRemoved?.apply(this, args);
        };

        requestAnimationFrame(() => {
            const width = Math.max(Number(node.size?.[0] || PREVIEW_DEFAULT_WIDTH), PREVIEW_DEFAULT_WIDTH);
            const height = Number(node.size?.[1] || 0);
            if (node.size && node.size[0] < width) {
                node.setSize?.([width, height]);
            }
            node._hbeRecomputeBaseHeight?.();
            node._hbeSyncPreviewHeight?.();
            node._hbeEnsurePreviewSource?.(true);
            node._hbeDrawPreview?.();
        });
    },
});
