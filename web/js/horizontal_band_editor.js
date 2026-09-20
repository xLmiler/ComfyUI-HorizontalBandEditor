import { app } from "../../scripts/app.js";
import { api } from "../../scripts/api.js";

const NODE_NAME = "HorizontalBandEditor";

function getWidget(node, name) {
    return node.widgets?.find((w) => w.name === name);
}

function setWidgetValue(widget, value, node) {
    if (!widget) return;
    widget.value = value;
    try {
        widget.callback?.(value, app.canvas, node, [0, 0], {});
    } catch (_) {
        // 不同前端版本 callback 参数存在细微差异；value 已写入，忽略即可。
    }
    node.setDirtyCanvas?.(true, true);
}

function makeViewUrl(value) {
    if (!value) return "";
    const params = new URLSearchParams();
    params.set("filename", String(value));
    params.set("type", "input");
    params.set("subfolder", "");
    // apiURL 可兼容 ComfyUI 挂载在反向代理子路径下的场景。
    return api.apiURL(`/view?${params.toString()}`);
}

function buildEditor(node) {
    const imageWidget = getWidget(node, "image");
    const topWidget = getWidget(node, "selection_top_px");
    const bottomWidget = getWidget(node, "selection_bottom_px");
    const backgroundColorWidget = getWidget(node, "background_color");
    const textColorWidget = getWidget(node, "text_color");

    const root = document.createElement("div");
    root.style.width = "100%";
    root.style.boxSizing = "border-box";
    root.style.padding = "6px";
    root.style.userSelect = "none";

    const title = document.createElement("div");
    title.textContent = "拖拽选择横向区域（宽度始终等于整张图）";
    title.style.fontSize = "12px";
    title.style.opacity = "0.85";
    title.style.marginBottom = "6px";
    root.appendChild(title);

    const canvas = document.createElement("canvas");
    canvas.width = 640;
    canvas.height = 360;
    canvas.style.width = "100%";
    canvas.style.height = "auto";
    canvas.style.display = "block";
    canvas.style.border = "1px solid rgba(255,255,255,0.18)";
    canvas.style.borderRadius = "6px";
    canvas.style.background = "repeating-conic-gradient(#2a2a2a 0 25%, #333 0 50%) 0 / 16px 16px";
    canvas.style.cursor = "crosshair";
    canvas.style.touchAction = "none";
    root.appendChild(canvas);

    const info = document.createElement("div");
    info.style.marginTop = "5px";
    info.style.fontSize = "11px";
    info.style.opacity = "0.8";
    root.appendChild(info);

    // 颜色除了保留可序列化的字符串 widget，也提供直观的浏览器取色器。
    const colorRow = document.createElement("div");
    colorRow.style.display = "grid";
    colorRow.style.gridTemplateColumns = "1fr 1fr";
    colorRow.style.gap = "8px";
    colorRow.style.marginTop = "7px";

    function makeColorControl(labelText, widget, fallback) {
        const wrap = document.createElement("label");
        wrap.style.display = "flex";
        wrap.style.alignItems = "center";
        wrap.style.justifyContent = "space-between";
        wrap.style.gap = "6px";
        wrap.style.fontSize = "11px";
        wrap.style.opacity = "0.9";
        const label = document.createElement("span");
        label.textContent = labelText;
        const picker = document.createElement("input");
        picker.type = "color";
        picker.value = /^#[0-9a-f]{6}$/i.test(String(widget?.value || "")) ? String(widget.value) : fallback;
        picker.style.width = "38px";
        picker.style.height = "24px";
        picker.style.padding = "0";
        picker.style.border = "0";
        picker.style.background = "transparent";
        picker.addEventListener("input", () => setWidgetValue(widget, picker.value.toUpperCase(), node));
        wrap.append(label, picker);
        return { wrap, picker };
    }

    const bgColorControl = makeColorControl("面板底色", backgroundColorWidget, "#FFFFFF");
    const textColorControl = makeColorControl("文字颜色", textColorWidget, "#000000");
    colorRow.append(bgColorControl.wrap, textColorControl.wrap);
    root.appendChild(colorRow);

    const state = {
        img: null,
        dragging: false,
        anchorY: 0,
        lastImageValue: null,
        displayRect: { x: 0, y: 0, w: 1, h: 1 },
    };

    function currentSelection() {
        const h = state.img?.naturalHeight || state.img?.height || 1;
        let y1 = Math.round(Number(topWidget?.value ?? 0));
        let y2 = Math.round(Number(bottomWidget?.value ?? 1));
        y1 = Math.max(0, Math.min(h - 1, y1));
        y2 = Math.max(y1 + 1, Math.min(h, y2));
        return [y1, y2];
    }

    function draw() {
        const ctx = canvas.getContext("2d");
        const cssWidth = Math.max(260, Math.floor(root.getBoundingClientRect().width || 360));
        const dpr = Math.max(1, window.devicePixelRatio || 1);

        let cssHeight = 220;
        if (state.img?.naturalWidth && state.img?.naturalHeight) {
            cssHeight = Math.max(140, Math.min(420, cssWidth * state.img.naturalHeight / state.img.naturalWidth));
        }
        canvas.style.height = `${cssHeight}px`;
        canvas.width = Math.max(1, Math.floor(cssWidth * dpr));
        canvas.height = Math.max(1, Math.floor(cssHeight * dpr));
        ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
        ctx.clearRect(0, 0, cssWidth, cssHeight);

        if (!state.img?.complete || !state.img.naturalWidth) {
            ctx.fillStyle = "rgba(255,255,255,0.75)";
            ctx.font = "13px sans-serif";
            ctx.textAlign = "center";
            ctx.textBaseline = "middle";
            ctx.fillText("请先上传或选择图片", cssWidth / 2, cssHeight / 2);
            state.displayRect = { x: 0, y: 0, w: cssWidth, h: cssHeight };
            info.textContent = "未加载图片";
            return;
        }

        const scale = Math.min(cssWidth / state.img.naturalWidth, cssHeight / state.img.naturalHeight);
        const dw = state.img.naturalWidth * scale;
        const dh = state.img.naturalHeight * scale;
        const dx = (cssWidth - dw) / 2;
        const dy = (cssHeight - dh) / 2;
        state.displayRect = { x: dx, y: dy, w: dw, h: dh };

        ctx.drawImage(state.img, dx, dy, dw, dh);

        const [y1, y2] = currentSelection();
        const sy1 = dy + y1 / state.img.naturalHeight * dh;
        const sy2 = dy + y2 / state.img.naturalHeight * dh;

        // 选区以外稍微压暗，让横向带一眼可见。
        ctx.fillStyle = "rgba(0,0,0,0.38)";
        ctx.fillRect(dx, dy, dw, Math.max(0, sy1 - dy));
        ctx.fillRect(dx, sy2, dw, Math.max(0, dy + dh - sy2));

        ctx.fillStyle = "rgba(70, 160, 255, 0.20)";
        ctx.fillRect(dx, sy1, dw, Math.max(1, sy2 - sy1));
        ctx.strokeStyle = "rgba(100, 190, 255, 0.98)";
        ctx.lineWidth = 2;
        ctx.strokeRect(dx + 1, sy1, Math.max(1, dw - 2), Math.max(1, sy2 - sy1));

        ctx.fillStyle = "rgba(10,10,10,0.78)";
        const label = `Y: ${y1} → ${y2}  |  高度: ${y2 - y1}px`;
        ctx.font = "12px sans-serif";
        const m = ctx.measureText(label);
        const lw = m.width + 12;
        const lh = 22;
        const lx = dx + 6;
        const ly = Math.max(dy + 4, Math.min(sy1 + 4, dy + dh - lh - 4));
        ctx.fillRect(lx, ly, lw, lh);
        ctx.fillStyle = "white";
        ctx.textAlign = "left";
        ctx.textBaseline = "middle";
        ctx.fillText(label, lx + 6, ly + lh / 2);

        info.textContent = `原图 ${state.img.naturalWidth}×${state.img.naturalHeight}；选择区域 ${y2 - y1}px 高。`;
    }

    function canvasYToImageY(clientY) {
        if (!state.img?.naturalHeight) return 0;
        const rect = canvas.getBoundingClientRect();
        const cy = clientY - rect.top;
        const dr = state.displayRect;
        const clamped = Math.max(dr.y, Math.min(dr.y + dr.h, cy));
        const t = dr.h > 0 ? (clamped - dr.y) / dr.h : 0;
        return Math.round(t * state.img.naturalHeight);
    }

    function commitSelection(a, b) {
        if (!state.img?.naturalHeight) return;
        const h = state.img.naturalHeight;
        let y1 = Math.round(Math.min(a, b));
        let y2 = Math.round(Math.max(a, b));
        y1 = Math.max(0, Math.min(h - 1, y1));
        y2 = Math.max(y1 + 1, Math.min(h, y2));
        setWidgetValue(topWidget, y1, node);
        setWidgetValue(bottomWidget, y2, node);
        draw();
    }

    canvas.addEventListener("pointerdown", (e) => {
        if (!state.img?.naturalHeight) return;
        canvas.setPointerCapture?.(e.pointerId);
        state.dragging = true;
        state.anchorY = canvasYToImageY(e.clientY);
        commitSelection(state.anchorY, state.anchorY + 1);
        e.preventDefault();
    });

    canvas.addEventListener("pointermove", (e) => {
        if (!state.dragging) return;
        commitSelection(state.anchorY, canvasYToImageY(e.clientY));
        e.preventDefault();
    });

    function endDrag(e) {
        if (!state.dragging) return;
        state.dragging = false;
        try { canvas.releasePointerCapture?.(e.pointerId); } catch (_) {}
        e.preventDefault();
    }
    canvas.addEventListener("pointerup", endDrag);
    canvas.addEventListener("pointercancel", endDrag);

    function loadSelectedImage(force = false) {
        const value = imageWidget?.value;
        if (!value) {
            state.img = null;
            state.lastImageValue = null;
            draw();
            return;
        }
        if (!force && state.lastImageValue === value && state.img) {
            draw();
            return;
        }
        state.lastImageValue = value;

        const img = new Image();
        img.onload = () => {
            state.img = img;
            const h = img.naturalHeight;
            const currentTop = Number(topWidget?.value ?? 0);
            const currentBottom = Number(bottomWidget?.value ?? 1);

            // 新图片第一次载入时，如果当前选区明显无效，则默认选择中间 1/3。
            if (
                !Number.isFinite(currentTop) || !Number.isFinite(currentBottom) ||
                currentTop < 0 || currentBottom <= currentTop || currentBottom > h ||
                (currentTop === 0 && currentBottom <= 1)
            ) {
                const y1 = Math.floor(h / 3);
                const y2 = Math.max(y1 + 1, Math.ceil(h * 2 / 3));
                setWidgetValue(topWidget, y1, node);
                setWidgetValue(bottomWidget, Math.min(h, y2), node);
            } else {
                // 图片尺寸变化后把旧值夹回合法范围。
                commitSelection(currentTop, currentBottom);
            }
            draw();
            requestAnimationFrame(() => node.setSize?.([Math.max(node.size?.[0] || 360, 360), Math.max(node.size?.[1] || 520, 520)]));
        };
        img.onerror = () => {
            state.img = null;
            info.textContent = "图片预览加载失败；后端执行时仍会校验实际文件。";
            draw();
        };
        img.src = `${makeViewUrl(value)}&rand=${Date.now()}`;
    }

    // 监听内置图片下拉/上传 widget 的变化。
    if (imageWidget) {
        const originalCallback = imageWidget.callback;
        imageWidget.callback = function (...args) {
            const result = originalCallback?.apply(this, args);
            queueMicrotask(() => loadSelectedImage(true));
            return result;
        };
    }

    // 手动修改像素数值时，画布同步更新。
    for (const widget of [topWidget, bottomWidget]) {
        if (!widget) continue;
        const originalCallback = widget.callback;
        widget.callback = function (...args) {
            const result = originalCallback?.apply(this, args);
            requestAnimationFrame(draw);
            return result;
        };
    }

    for (const [widget, picker] of [[backgroundColorWidget, bgColorControl.picker], [textColorWidget, textColorControl.picker]]) {
        if (!widget) continue;
        const originalCallback = widget.callback;
        widget.callback = function (...args) {
            const result = originalCallback?.apply(this, args);
            const v = String(widget.value || "");
            if (/^#[0-9a-f]{6}$/i.test(v)) picker.value = v;
            return result;
        };
    }

    const ro = new ResizeObserver(() => draw());
    ro.observe(root);

    node._horizontalBandEditorCleanup = () => ro.disconnect();
    node._horizontalBandEditorReload = () => loadSelectedImage(true);

    requestAnimationFrame(() => loadSelectedImage(true));
    return root;
}

app.registerExtension({
    name: "OpenAI.HorizontalBandEditor",
    async beforeRegisterNodeDef(nodeType, nodeData) {
        if (nodeData.name !== NODE_NAME) return;

        const originalCreated = nodeType.prototype.onNodeCreated;
        nodeType.prototype.onNodeCreated = function () {
            const result = originalCreated?.apply(this, arguments);
            if (!this._horizontalBandEditorWidget) {
                const element = buildEditor(this);
                this._horizontalBandEditorWidget = this.addDOMWidget(
                    "horizontal_band_visual_editor",
                    "horizontal_band_visual_editor",
                    element,
                    {
                        serialize: false,
                        hideOnZoom: false,
                    }
                );
                this.setSize?.([Math.max(this.size?.[0] || 360, 360), Math.max(this.size?.[1] || 560, 560)]);
            }
            return result;
        };

        const originalConfigured = nodeType.prototype.onConfigure;
        nodeType.prototype.onConfigure = function () {
            const result = originalConfigured?.apply(this, arguments);
            requestAnimationFrame(() => this._horizontalBandEditorReload?.());
            return result;
        };

        const originalRemoved = nodeType.prototype.onRemoved;
        nodeType.prototype.onRemoved = function () {
            this._horizontalBandEditorCleanup?.();
            return originalRemoved?.apply(this, arguments);
        };
    },
});
