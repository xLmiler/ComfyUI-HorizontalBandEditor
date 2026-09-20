import { app } from "../../scripts/app.js";
import { api } from "../../scripts/api.js";

const NODE_NAME = "HorizontalBandEditor";
const NODE_MIN_W = 430;
const NODE_MIN_H = 900;

function getWidget(node, ...names) {
    return node.widgets?.find((w) => names.includes(w.name));
}

function setWidgetValue(widget, value, node) {
    if (!widget) return;
    widget.value = value;
    try {
        widget.callback?.(value, app.canvas, node, [0, 0], {});
    } catch (_) {
        // 兼容不同前端 callback 差异
    }
    node.setDirtyCanvas?.(true, true);
}

function hideWidget(widget) {
    if (!widget) return;
    widget.computeSize = () => [0, 0];
    widget.hidden = true;
    widget.visible = false;
    widget.type = "hidden";
    widget.draw = () => {};
    widget.serialize = true;
    widget.options = { ...(widget.options || {}), hidden: true };
}

function bindWidgetSync(widget, onChange) {
    if (!widget) return;
    const original = widget.callback;
    widget.callback = function (...args) {
        const result = original?.apply(this, args);
        onChange?.();
        return result;
    };
}

function makeViewUrl(value) {
    if (!value) return "";
    const params = new URLSearchParams();
    params.set("filename", String(value));
    params.set("type", "input");
    params.set("subfolder", "");
    return api.apiURL(`/view?${params.toString()}`);
}

function getConnectedPreviewFilename(node) {
    if (!node?.inputs?.length || !app.graph) return null;
    for (const input of node.inputs) {
        if (!input || !["输入图像", "input_image"].includes(input.name) || input.link == null) continue;
        const link = app.graph.links?.[input.link];
        const originId = link?.origin_id;
        if (originId == null) continue;
        const upstream = app.graph.getNodeById?.(originId);
        if (!upstream) continue;

        const imageWidget = upstream.widgets?.find((w) => w.name === "image");
        if (imageWidget?.value) {
            return {
                filename: String(imageWidget.value),
                nodeTitle: upstream.title || upstream.type || `#${originId}`,
            };
        }
    }
    return null;
}

function createFieldRow(labelText, controlEl) {
    const row = document.createElement("div");
    row.style.display = "grid";
    row.style.gridTemplateColumns = "86px 1fr";
    row.style.gap = "8px";
    row.style.alignItems = "center";
    row.style.marginBottom = "8px";

    const label = document.createElement("div");
    label.textContent = labelText;
    label.style.fontSize = "11px";
    label.style.opacity = "0.9";

    row.append(label, controlEl);
    return row;
}

function styleInput(el) {
    el.style.width = "100%";
    el.style.boxSizing = "border-box";
    el.style.height = "30px";
    el.style.borderRadius = "6px";
    el.style.border = "1px solid rgba(255,255,255,0.18)";
    el.style.background = "rgba(255,255,255,0.06)";
    el.style.color = "inherit";
    el.style.padding = "0 8px";
    el.style.fontSize = "12px";
    return el;
}

function styleTextArea(el) {
    el.style.width = "100%";
    el.style.minHeight = "120px";
    el.style.resize = "vertical";
    el.style.boxSizing = "border-box";
    el.style.borderRadius = "8px";
    el.style.border = "1px solid rgba(255,255,255,0.18)";
    el.style.background = "rgba(255,255,255,0.06)";
    el.style.color = "inherit";
    el.style.padding = "8px";
    el.style.font = "12px sans-serif";
    el.style.lineHeight = "1.5";
    return el;
}

function createSection(title, open = true) {
    const details = document.createElement("details");
    details.open = open;
    details.style.border = "1px solid rgba(255,255,255,0.10)";
    details.style.borderRadius = "8px";
    details.style.padding = "0";
    details.style.background = "rgba(255,255,255,0.03)";
    details.style.overflow = "hidden";

    const summary = document.createElement("summary");
    summary.textContent = title;
    summary.style.cursor = "pointer";
    summary.style.listStyle = "none";
    summary.style.padding = "8px 10px";
    summary.style.fontSize = "12px";
    summary.style.fontWeight = "700";
    summary.style.borderBottom = "1px solid rgba(255,255,255,0.07)";
    summary.style.userSelect = "none";
    details.appendChild(summary);

    const body = document.createElement("div");
    body.style.padding = "8px";
    body.style.display = "flex";
    body.style.flexDirection = "column";
    body.style.gap = "4px";
    details.appendChild(body);

    return { details, summary, body };
}

function buildEditor(node) {
    const enableWidget = getWidget(node, "启用文字面板", "text_panel_enabled");
    const topWidget = getWidget(node, "选区上边界(px)", "selection_top_px");
    const bottomWidget = getWidget(node, "选区下边界(px)", "selection_bottom_px");
    const bgModeWidget = getWidget(node, "面板背景", "panel_background");
    const bgColorWidget = getWidget(node, "背景颜色", "background_color");
    const textWidget = getWidget(node, "文字内容", "text");
    const textColorWidget = getWidget(node, "文字颜色", "text_color");
    const fontPathWidget = getWidget(node, "字体名称或路径", "font_name_or_path");
    const fontSizeWidget = getWidget(node, "字号", "font_size");
    const paddingWidget = getWidget(node, "内边距", "padding");
    const lineSpacingWidget = getWidget(node, "行距", "line_spacing");
    const hAlignWidget = getWidget(node, "水平对齐", "horizontal_align");
    const vAlignWidget = getWidget(node, "垂直对齐", "vertical_align");

    // 当增强面板可用时，隐藏重复的原生控件；如果 JS 失效，则自动退回原生 UI。
    [bgModeWidget, bgColorWidget, textWidget, textColorWidget, fontSizeWidget, paddingWidget, lineSpacingWidget, hAlignWidget, vAlignWidget].forEach(hideWidget);

    const root = document.createElement("div");
    root.style.width = "100%";
    root.style.boxSizing = "border-box";
    root.style.padding = "8px";
    root.style.display = "flex";
    root.style.flexDirection = "column";
    root.style.gap = "8px";
    root.style.userSelect = "none";

    const title = document.createElement("div");
    title.textContent = "横向区域可视化编辑器";
    title.style.fontSize = "13px";
    title.style.fontWeight = "700";
    title.style.opacity = "0.98";
    root.appendChild(title);

    const help = document.createElement("div");
    help.textContent = "兼容两套使用方式：增强面板（当前页）与原生控件回退。先连接“加载图像”到“输入图像”，再同步预览。";
    help.style.fontSize = "11px";
    help.style.opacity = "0.78";
    root.appendChild(help);

    // 基础控制
    const basicSection = createSection("一、基础模式", true);
    root.appendChild(basicSection.details);

    const enableWrap = document.createElement("label");
    enableWrap.style.display = "flex";
    enableWrap.style.alignItems = "center";
    enableWrap.style.justifyContent = "space-between";
    enableWrap.style.gap = "8px";
    enableWrap.style.padding = "4px 0";

    const enableLabel = document.createElement("span");
    enableLabel.textContent = "启用文字面板";
    enableLabel.style.fontSize = "12px";

    const enableToggle = document.createElement("input");
    enableToggle.type = "checkbox";
    enableToggle.checked = Boolean(enableWidget?.value);
    enableToggle.style.width = "18px";
    enableToggle.style.height = "18px";
    enableToggle.addEventListener("change", () => setWidgetValue(enableWidget, enableToggle.checked, node));
    enableWrap.append(enableLabel, enableToggle);
    basicSection.body.appendChild(enableWrap);

    const modeHint = document.createElement("div");
    modeHint.style.fontSize = "11px";
    modeHint.style.opacity = "0.74";
    basicSection.body.appendChild(modeHint);

    // 预览区
    const previewSection = createSection("二、预览与选区", true);
    root.appendChild(previewSection.details);

    const buttonRow = document.createElement("div");
    buttonRow.style.display = "grid";
    buttonRow.style.gridTemplateColumns = "1fr 1fr";
    buttonRow.style.gap = "8px";

    function makeButton(label) {
        const btn = document.createElement("button");
        btn.type = "button";
        btn.textContent = label;
        btn.style.height = "32px";
        btn.style.borderRadius = "6px";
        btn.style.border = "1px solid rgba(255,255,255,0.18)";
        btn.style.background = "rgba(255,255,255,0.06)";
        btn.style.color = "inherit";
        btn.style.cursor = "pointer";
        btn.style.fontSize = "12px";
        return btn;
    }

    const btnLoad = makeButton("从输入图像同步预览");
    const btnReload = makeButton("刷新当前预览");
    buttonRow.append(btnLoad, btnReload);
    previewSection.body.appendChild(buttonRow);

    const connInfo = document.createElement("div");
    connInfo.style.fontSize = "11px";
    connInfo.style.opacity = "0.76";
    previewSection.body.appendChild(connInfo);

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
    previewSection.body.appendChild(canvas);

    const previewInfo = document.createElement("div");
    previewInfo.style.fontSize = "11px";
    previewInfo.style.opacity = "0.82";
    previewSection.body.appendChild(previewInfo);

    // 文字面板区
    const textSection = createSection("三、文字面板设置", true);
    root.appendChild(textSection.details);

    function makeSelect(options, value) {
        const select = styleInput(document.createElement("select"));
        for (const item of options) {
            const op = document.createElement("option");
            op.value = item;
            op.textContent = item;
            if (item === value) op.selected = true;
            select.appendChild(op);
        }
        return select;
    }

    function makeNumberInput(value, min, max, step = 1) {
        const el = styleInput(document.createElement("input"));
        el.type = "number";
        el.value = String(value ?? "");
        el.min = String(min);
        el.max = String(max);
        el.step = String(step);
        return el;
    }

    function makeColorComposite(initial, defaultValue) {
        const wrap = document.createElement("div");
        wrap.style.display = "grid";
        wrap.style.gridTemplateColumns = "42px 1fr";
        wrap.style.gap = "8px";
        wrap.style.alignItems = "center";

        const picker = document.createElement("input");
        picker.type = "color";
        picker.value = /^#[0-9a-f]{6}$/i.test(String(initial || "")) ? String(initial) : defaultValue;
        picker.style.width = "38px";
        picker.style.height = "28px";
        picker.style.padding = "0";
        picker.style.border = "0";
        picker.style.background = "transparent";

        const text = styleInput(document.createElement("input"));
        text.type = "text";
        text.placeholder = defaultValue;
        text.value = String(initial || defaultValue).toUpperCase();

        function normalize(raw) {
            let v = String(raw || "").trim().toUpperCase();
            if (!v.startsWith("#")) v = `#${v}`;
            return /^#[0-9A-F]{6}$/.test(v) ? v : null;
        }

        return {
            wrap,
            picker,
            text,
            get value() {
                return normalize(text.value) || defaultValue;
            },
            set value(v) {
                const n = normalize(v) || defaultValue;
                picker.value = n;
                text.value = n;
            },
        };
    }

    const bgModeSelect = makeSelect(["纯色", "透明"], String(bgModeWidget?.value || "纯色"));
    bgModeSelect.addEventListener("change", () => setWidgetValue(bgModeWidget, bgModeSelect.value, node));
    textSection.body.appendChild(createFieldRow("面板背景", bgModeSelect));

    const bgColorComp = makeColorComposite(bgColorWidget?.value, "#FFFFFF");
    bgColorComp.wrap.append(bgColorComp.picker, bgColorComp.text);
    bgColorComp.picker.addEventListener("input", () => {
        bgColorComp.text.value = bgColorComp.picker.value.toUpperCase();
        setWidgetValue(bgColorWidget, bgColorComp.picker.value.toUpperCase(), node);
    });
    bgColorComp.text.addEventListener("change", () => {
        bgColorComp.value = bgColorComp.text.value;
        setWidgetValue(bgColorWidget, bgColorComp.value, node);
    });
    textSection.body.appendChild(createFieldRow("背景颜色", bgColorComp.wrap));

    const textColorComp = makeColorComposite(textColorWidget?.value, "#000000");
    textColorComp.wrap.append(textColorComp.picker, textColorComp.text);
    textColorComp.picker.addEventListener("input", () => {
        textColorComp.text.value = textColorComp.picker.value.toUpperCase();
        setWidgetValue(textColorWidget, textColorComp.picker.value.toUpperCase(), node);
    });
    textColorComp.text.addEventListener("change", () => {
        textColorComp.value = textColorComp.text.value;
        setWidgetValue(textColorWidget, textColorComp.value, node);
    });
    textSection.body.appendChild(createFieldRow("文字颜色", textColorComp.wrap));

    const textArea = styleTextArea(document.createElement("textarea"));
    textArea.value = String(textWidget?.value || "");
    textArea.placeholder = "在这里输入文字";
    textArea.addEventListener("input", () => setWidgetValue(textWidget, textArea.value, node));
    textSection.body.appendChild(createFieldRow("文字内容", textArea));

    const typographySection = createSection("四、高级排版设置", false);
    root.appendChild(typographySection.details);

    const fontSizeInput = makeNumberInput(fontSizeWidget?.value ?? 48, 1, 1024, 1);
    fontSizeInput.addEventListener("change", () => setWidgetValue(fontSizeWidget, Number(fontSizeInput.value || 48), node));
    typographySection.body.appendChild(createFieldRow("字号", fontSizeInput));

    const paddingInput = makeNumberInput(paddingWidget?.value ?? 24, 0, 2048, 1);
    paddingInput.addEventListener("change", () => setWidgetValue(paddingWidget, Number(paddingInput.value || 24), node));
    typographySection.body.appendChild(createFieldRow("内边距", paddingInput));

    const lineSpacingInput = makeNumberInput(lineSpacingWidget?.value ?? 8, 0, 1024, 1);
    lineSpacingInput.addEventListener("change", () => setWidgetValue(lineSpacingWidget, Number(lineSpacingInput.value || 8), node));
    typographySection.body.appendChild(createFieldRow("行距", lineSpacingInput));

    const hAlignSelect = makeSelect(["居中", "左对齐", "右对齐"], String(hAlignWidget?.value || "居中"));
    hAlignSelect.addEventListener("change", () => setWidgetValue(hAlignWidget, hAlignSelect.value, node));
    typographySection.body.appendChild(createFieldRow("水平对齐", hAlignSelect));

    const vAlignSelect = makeSelect(["居中", "顶部", "底部"], String(vAlignWidget?.value || "居中"));
    vAlignSelect.addEventListener("change", () => setWidgetValue(vAlignWidget, vAlignSelect.value, node));
    typographySection.body.appendChild(createFieldRow("垂直对齐", vAlignSelect));

    const fontTip = document.createElement("div");
    fontTip.style.fontSize = "11px";
    fontTip.style.opacity = "0.72";
    fontTip.textContent = `字体路径仍保留在原生控件中，当前值：${String(fontPathWidget?.value || "SimHei")}`;
    typographySection.body.appendChild(fontTip);

    const footerSection = createSection("五、兼容说明", false);
    root.appendChild(footerSection.details);
    const footerText = document.createElement("div");
    footerText.style.fontSize = "11px";
    footerText.style.opacity = "0.74";
    footerText.innerHTML = [
        "1. 当前增强面板用于新版 UI。<br>",
        "2. 若前端脚本未加载，原生控件仍可直接使用。<br>",
        "3. 本版本已移除节点内置上传控件，因此不会再出现双预览。",
    ].join("");
    footerSection.body.appendChild(footerText);

    const state = {
        img: null,
        dragging: false,
        anchorY: 0,
        lastFilename: null,
        displayRect: { x: 0, y: 0, w: 1, h: 1 },
    };

    function updateDynamicVisibility() {
        const enabled = Boolean(enableWidget?.value);
        enableToggle.checked = enabled;
        textSection.details.style.display = enabled ? "block" : "none";
        typographySection.details.style.display = enabled ? "block" : "none";
        modeHint.textContent = enabled
            ? "当前模式：将选区替换为文字面板。文字设置与高级排版区已展开。"
            : "当前模式：删除选区，并将上下图像直接拼接。文字相关设置已自动隐藏。";
        const bgMode = String(bgModeWidget?.value || "纯色");
        bgColorComp.wrap.parentElement.style.display = bgMode === "透明" ? "none" : "grid";
    }

    function refreshConnectionInfo() {
        const found = getConnectedPreviewFilename(node);
        connInfo.textContent = found
            ? `当前预览来源：${found.nodeTitle} → ${found.filename}`
            : "当前未检测到可读取文件名的上游“加载图像”节点。";
    }

    function currentSelection() {
        const h = state.img?.naturalHeight || state.img?.height || 1;
        let y1 = Math.round(Number(topWidget?.value ?? 0));
        let y2 = Math.round(Number(bottomWidget?.value ?? 1));
        y1 = Math.max(0, Math.min(h - 1, y1));
        y2 = Math.max(y1 + 1, Math.min(h, y2));
        return [y1, y2];
    }

    function drawPreview() {
        const ctx = canvas.getContext("2d");
        const cssWidth = Math.max(320, Math.floor(root.getBoundingClientRect().width || 400));
        const dpr = Math.max(1, window.devicePixelRatio || 1);

        let cssHeight = 240;
        if (state.img?.naturalWidth && state.img?.naturalHeight) {
            cssHeight = Math.max(170, Math.min(520, (cssWidth * state.img.naturalHeight) / state.img.naturalWidth));
        }
        canvas.style.height = `${cssHeight}px`;
        canvas.width = Math.max(1, Math.floor(cssWidth * dpr));
        canvas.height = Math.max(1, Math.floor(cssHeight * dpr));
        ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
        ctx.clearRect(0, 0, cssWidth, cssHeight);

        if (!state.img?.complete || !state.img?.naturalWidth) {
            ctx.fillStyle = "rgba(255,255,255,0.75)";
            ctx.font = "13px sans-serif";
            ctx.textAlign = "center";
            ctx.textBaseline = "middle";
            ctx.fillText("请先从输入图像同步预览", cssWidth / 2, cssHeight / 2);
            state.displayRect = { x: 0, y: 0, w: cssWidth, h: cssHeight };
            previewInfo.textContent = "未加载预览图像";
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
        const sy1 = dy + (y1 / state.img.naturalHeight) * dh;
        const sy2 = dy + (y2 / state.img.naturalHeight) * dh;

        ctx.fillStyle = "rgba(0,0,0,0.38)";
        ctx.fillRect(dx, dy, dw, Math.max(0, sy1 - dy));
        ctx.fillRect(dx, sy2, dw, Math.max(0, dy + dh - sy2));
        ctx.fillStyle = "rgba(70, 160, 255, 0.20)";
        ctx.fillRect(dx, sy1, dw, Math.max(1, sy2 - sy1));
        ctx.strokeStyle = "rgba(100, 190, 255, 0.98)";
        ctx.lineWidth = 2;
        ctx.strokeRect(dx + 1, sy1, Math.max(1, dw - 2), Math.max(1, sy2 - sy1));

        const label = `Y: ${y1} → ${y2} ｜ 高度 ${y2 - y1}px`;
        ctx.fillStyle = "rgba(10,10,10,0.78)";
        ctx.font = "12px sans-serif";
        const m = ctx.measureText(label);
        const lx = dx + 6;
        const ly = Math.max(dy + 4, Math.min(sy1 + 4, dy + dh - 26));
        ctx.fillRect(lx, ly, m.width + 12, 22);
        ctx.fillStyle = "white";
        ctx.textAlign = "left";
        ctx.textBaseline = "middle";
        ctx.fillText(label, lx + 6, ly + 11);

        previewInfo.textContent = `预览图尺寸 ${state.img.naturalWidth}×${state.img.naturalHeight}；当前选区高度 ${y2 - y1}px。`;
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
        drawPreview();
    }

    function loadPreviewByFilename(filename, force = false) {
        if (!filename) {
            state.img = null;
            state.lastFilename = null;
            drawPreview();
            refreshConnectionInfo();
            return;
        }
        if (!force && state.lastFilename === filename && state.img) {
            drawPreview();
            refreshConnectionInfo();
            return;
        }
        state.lastFilename = filename;

        const img = new Image();
        img.onload = () => {
            state.img = img;
            const h = img.naturalHeight;
            const currentTop = Number(topWidget?.value ?? 0);
            const currentBottom = Number(bottomWidget?.value ?? 1);
            if (!Number.isFinite(currentTop) || !Number.isFinite(currentBottom) || currentTop < 0 || currentBottom <= currentTop || currentBottom > h || (currentTop === 0 && currentBottom <= 1)) {
                const y1 = Math.floor(h / 3);
                const y2 = Math.max(y1 + 1, Math.ceil((h * 2) / 3));
                setWidgetValue(topWidget, y1, node);
                setWidgetValue(bottomWidget, Math.min(h, y2), node);
            }
            drawPreview();
            refreshConnectionInfo();
            requestAnimationFrame(() => node.setSize?.([Math.max(node.size?.[0] || NODE_MIN_W, NODE_MIN_W), Math.max(node.size?.[1] || NODE_MIN_H, NODE_MIN_H)]));
        };
        img.onerror = () => {
            state.img = null;
            previewInfo.textContent = "预览图像加载失败；后端执行时仍会使用“输入图像”处理。";
            refreshConnectionInfo();
            drawPreview();
        };
        img.src = `${makeViewUrl(filename)}&rand=${Date.now()}`;
    }

    function syncPreviewFromConnection(force = true) {
        const found = getConnectedPreviewFilename(node);
        if (!found?.filename) {
            previewInfo.textContent = "未找到可读取文件名的上游“加载图像”节点；若上游不是 Load Image，则只能使用原生控件处理。";
            refreshConnectionInfo();
            return;
        }
        loadPreviewByFilename(found.filename, force);
    }

    btnLoad.addEventListener("click", () => syncPreviewFromConnection(true));
    btnReload.addEventListener("click", () => syncPreviewFromConnection(true));

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

    bindWidgetSync(enableWidget, updateDynamicVisibility);
    bindWidgetSync(bgModeWidget, () => { bgModeSelect.value = String(bgModeWidget?.value || "纯色"); updateDynamicVisibility(); });
    bindWidgetSync(bgColorWidget, () => { bgColorComp.value = String(bgColorWidget?.value || "#FFFFFF"); });
    bindWidgetSync(textColorWidget, () => { textColorComp.value = String(textColorWidget?.value || "#000000"); });
    bindWidgetSync(textWidget, () => { if (textArea.value !== String(textWidget?.value || "")) textArea.value = String(textWidget?.value || ""); });
    bindWidgetSync(fontSizeWidget, () => { fontSizeInput.value = String(fontSizeWidget?.value ?? 48); });
    bindWidgetSync(paddingWidget, () => { paddingInput.value = String(paddingWidget?.value ?? 24); });
    bindWidgetSync(lineSpacingWidget, () => { lineSpacingInput.value = String(lineSpacingWidget?.value ?? 8); });
    bindWidgetSync(hAlignWidget, () => { hAlignSelect.value = String(hAlignWidget?.value || "居中"); });
    bindWidgetSync(vAlignWidget, () => { vAlignSelect.value = String(vAlignWidget?.value || "居中"); });
    [topWidget, bottomWidget].forEach((w) => bindWidgetSync(w, drawPreview));

    const ro = new ResizeObserver(() => drawPreview());
    ro.observe(root);

    node._horizontalBandEditorCleanup = () => ro.disconnect();
    node._horizontalBandEditorReload = () => {
        updateDynamicVisibility();
        refreshConnectionInfo();
        fontTip.textContent = `字体路径仍保留在原生控件中，当前值：${String(fontPathWidget?.value || "SimHei")}`;
        syncPreviewFromConnection(false);
    };

    requestAnimationFrame(() => node._horizontalBandEditorReload?.());
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
                this._horizontalBandEditorWidget = this.addDOMWidget("horizontal_band_visual_editor", "horizontal_band_visual_editor", element, {
                    serialize: false,
                    hideOnZoom: false,
                });
                this.setSize?.([Math.max(this.size?.[0] || NODE_MIN_W, NODE_MIN_W), Math.max(this.size?.[1] || NODE_MIN_H, NODE_MIN_H)]);
            }
            return result;
        };

        const originalConfigured = nodeType.prototype.onConfigure;
        nodeType.prototype.onConfigure = function () {
            const result = originalConfigured?.apply(this, arguments);
            requestAnimationFrame(() => this._horizontalBandEditorReload?.());
            return result;
        };

        const originalConnectionsChange = nodeType.prototype.onConnectionsChange;
        nodeType.prototype.onConnectionsChange = function () {
            const result = originalConnectionsChange?.apply(this, arguments);
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
